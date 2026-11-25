#!/usr/bin/env python3
"""The polar cap's archive: the earlier runs' charts, taken from the history.

THE OWNER'S WORD (25 November 2026): only the polar cap carries archived
runs.  The seasonal snowfall maps do NOT - the earlier run and the current
one differ by a few tenths of an inch and the comparison drew that as a
whole map of colour, which reads as "these runs are nothing alike".  That
tool (tools/build_map_archive.py) stays in the repository, but nothing of
its output is published.

THE ARCHIVE IS NOT A NEW DATA ROUTE.  Every chart here was already drawn
and published once; this reads those drawings back out of the git history
and keeps them, so the reader can go back to an earlier run of the same
model.  The daily cycles of the GEFSv12 and the EC46 differ by a day of
lead, so two of them really are close to each other - which is why the
archive belongs here and not on the seasonal maps.

    python3 tools/build_polar_archive.py [--repo DIR]

It writes:
    docs/assets/polar/archive/<model>/<init>/polar_cap_<model>.png
    docs/assets/polar/archive/<model>/<init>/polar_sectors_<model>.png
    docs/assets/polar/archive/index.json
"""

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(ROOT, "docs", "assets", "polar", "archive")
MODELS = ("gefsv12", "ec46", "ecmwf-seas5")


def git(repo, *args):
    out = subprocess.run(["git", "-C", repo] + list(args),
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return out.stdout


def model_init(repo, commit, model):
    """The model's own cycle at that commit, read from the registry there."""
    txt = git(repo, "show", "%s:docs/data/models.json" % commit)
    if not txt:
        return None
    try:
        reg = json.loads(txt)
    except Exception:
        return None
    models = reg.get("models", reg if isinstance(reg, list) else [])
    for m in models:
        if m.get("id") == model:
            return m.get("init") or None
    return None


def label(init):
    """'2026-11-23' -> '23 November 2026';  '2026-11' -> 'November 2026'."""
    if not init or len(init) < 7:
        return init or ""
    months = ("January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December")
    try:
        m = int(init[5:7])
    except ValueError:
        return init
    if len(init) >= 10:
        try:
            return "%d %s %s" % (int(init[8:10]), months[m - 1], init[:4])
        except ValueError:
            return init
    return "%s %s" % (months[m - 1], init[:4])


def build(repo):
    reg = json.load(open(os.path.join(repo, "docs", "data", "models.json")))
    models = reg.get("models", reg if isinstance(reg, list) else [])
    current = {m["id"]: m.get("init") for m in models}

    index = {}
    for model in MODELS:
        cap = "docs/assets/polar/polar_cap_%s.png" % model
        sec = "docs/assets/polar/polar_sectors_%s.png" % model
        log = git(repo, "log", "--format=%H", "--", cap)
        if not log:
            continue
        # the newest commit that carries each cycle's chart
        seen = {}
        for commit in log.split():
            init = model_init(repo, commit, model)
            if not init or init in seen:
                continue
            if init == current.get(model):
                continue        # the current one is live already
            seen[init] = commit
        if not seen:
            continue
        entries = []
        for init, commit in sorted(seen.items(), reverse=True):
            outdir = os.path.join(ARCHIVE, model, init)
            os.makedirs(outdir, exist_ok=True)
            item = {"init": init, "label": label(init)}
            for key, path in (("cap", cap), ("sectors", sec)):
                # the chart is binary, so the blob is read as bytes
                raw = subprocess.run(["git", "-C", repo, "show",
                                      "%s:%s" % (commit, path)],
                                     capture_output=True).stdout
                if not raw:
                    continue
                name = os.path.basename(path)
                with open(os.path.join(outdir, name), "wb") as fh:
                    fh.write(raw)
                item[key] = "assets/polar/archive/%s/%s/%s" % (model, init, name)
            if "cap" not in item:
                continue
            entries.append(item)
            print("   %-14s %-12s %s" % (model, init, item["cap"]))
        if entries:
            index[model] = entries
    os.makedirs(ARCHIVE, exist_ok=True)
    with open(os.path.join(ARCHIVE, "index.json"), "w") as fh:
        json.dump(index, fh, indent=1)
    n = sum(len(v) for v in index.values())
    print("the polar archive holds %d earlier runs for %d models" % (n, len(index)))
    return index


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=ROOT)
    args = ap.parse_args()
    build(os.path.abspath(args.repo))
