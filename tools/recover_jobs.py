#!/usr/bin/env python3
"""Recover the fetched data after the sandbox has been wiped.

WHY
---
The working tree is wiped from time to time and the model data comes back
empty: `data/models/**` is gitignored (it is bulky and re-fetchable), so a
reset costs a fresh queue on the Copernicus store - and the store's queue is
slow and shared with every other user.

But a queued job keeps its RESULT on the store for a while after the data
has been requested, and the job ids are small.  So the job ids are written
into a tracked manifest, and this script walks the manifest after a reset:

  * the target file already exists  -> skipped, nothing to do;
  * the job still has a result       -> downloaded again, NO queue time;
  * the job is gone                  -> the request is re-submitted from
                                         the manifest (one job at a time,
                                         the store's queue discipline).

Usage:
    python3 tools/recover_jobs.py                 # every entry
    python3 tools/recover_jobs.py ecmwf-seas5     # one model
    python3 tools/recover_jobs.py --dry-run       # report only
"""
import os
import sys
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(ROOT, "data", "fetch_manifest.json")

sys.path.insert(0, ROOT)
from cds_direct import CDSDirect, QueueFull, NoData       # noqa: E402


def load():
    if not os.path.exists(MANIFEST):
        print("no manifest at %s - nothing to recover" % MANIFEST)
        return []
    with open(MANIFEST) as f:
        return json.load(f).get("jobs", [])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    dry = "--dry-run" in sys.argv

    jobs = load()
    if args:
        jobs = [j for j in jobs if j.get("model") in args or j.get("tag") in args]

    if not jobs:
        print("nothing to do.")
        return 0

    cds = CDSDirect()          # reads .cdsapirc
    missing, done, failed = [], [], []

    for j in jobs:
        target = os.path.join(ROOT, j["target"])
        jid = j.get("job")
        label = j.get("model") or j.get("tag") or j["target"]

        if os.path.exists(target) and os.path.getsize(target) > 1000:
            done.append(label)
            continue

        if jid:
            try:
                print("-- %s: the job %s may still have its result" % (label, jid))
                cds.download_job(jid, target)
                if os.path.exists(target) and os.path.getsize(target) > 1000:
                    done.append(label)
                    print("   recovered from the job (no queue time)")
                    continue
            except Exception as e:
                print("   the job did not give it back: %s" % str(e)[:160])
                missing.append(label)
        else:
            missing.append(label)

        if dry or not j.get("request"):
            continue

        # the job is gone: ask the store again, one at a time
        print("-- %s: re-submitting the request" % label)
        try:
            cds.retrieve(j["dataset"], j["request"], target)
            if os.path.exists(target) and os.path.getsize(target) > 1000:
                done.append(label)
                print("   fetched again")
            else:
                failed.append(label)
        except QueueFull:
            print("   the queue is full - try again later")
            failed.append(label)
        except NoData as e:
            print("   the archive has no data for it: %s" % str(e)[:120])
            failed.append(label)
        except Exception as e:
            print("   failed: %s" % str(e)[:160])
            failed.append(label)
        time.sleep(4)

    print("")
    print("present : %d  (%s)" % (len(done), ", ".join(done) or "-"))
    print("to pull : %d  (%s)" % (len(missing), ", ".join(missing) or "-"))
    print("failed  : %d  (%s)" % (len(failed), ", ".join(failed) or "-"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
