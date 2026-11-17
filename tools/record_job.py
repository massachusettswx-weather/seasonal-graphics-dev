#!/usr/bin/env python3
"""Record a CDS job id against the file it produced.

The job ids are what make a wipe cheap: a job keeps its RESULT on the store
long after the request was made, so `tools/recover_jobs.py` can download it
again without queueing.  That only works if the id is written down at the
moment the job is made.

    from tools.record_job import record
    record("data/models/ecmwf-seas5/snowfall_monthly.grib", jid)

or from the shell:

    python3 tools/record_job.py <target> <job id>
"""
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(ROOT, "data", "fetch_manifest.json")


def record(target, job, dataset=None, request=None, model=None):
    """Write the job id into the tracked manifest.  Never raises."""
    if not job:
        return False
    target = target.replace(ROOT + "/", "")
    data = {"jobs": []}
    if os.path.exists(MANIFEST):
        try:
            with open(MANIFEST) as f:
                data = json.load(f)
        except Exception:
            data = {"jobs": []}
    jobs = data.get("jobs", [])
    for j in jobs:
        if j.get("target") == target:
            j["job"] = job
            if dataset:
                j["dataset"] = dataset
            if request:
                j["request"] = request
            if model:
                j["model"] = model
            break
    else:
        entry = {"model": model or os.path.basename(os.path.dirname(target)),
                 "target": target, "job": job,
                 "note": "recorded after the fact"}
        if dataset:
            entry["dataset"] = dataset
        if request:
            entry["request"] = request
        jobs.append(entry)
    data["jobs"] = jobs
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, MANIFEST)
    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("usage: record_job.py <target> <job id>")
        sys.exit(1)
    print("recorded" if record(sys.argv[1], sys.argv[2]) else "nothing recorded")
