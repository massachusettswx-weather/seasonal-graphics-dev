#!/usr/bin/env python3
"""Write the tracked fetch manifest: what data the site needs and how to get
it back after the sandbox has been wiped.

The model data itself is gitignored (it is bulky), so after a reset the
pipeline has nothing to draw.  Re-requesting it costs a queue slot on the
Copernicus store, and the store's queue is slow and shared.

This manifest is the answer to "what did we have, and how do I get it
again".  It is regenerated from the TRACKED files - the model registry
`data/models_fetched.json`, the daily job registry `data/daily_jobs.json`
and the stray job-id files - so it cannot drift away from what the pipeline
actually uses.

Each entry carries:
    target    where the file belongs (relative to the repo root)
    dataset   the CDS dataset the request belongs to
    request   the request body, so it can be re-submitted verbatim
    job       the job id, when one is known - the RESULT of a job can often
              be downloaded again long after the request was made, which
              skips the queue entirely

Run it after any fetch:  python3 tools/write_fetch_manifest.py
"""
import os
import sys
import json
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "fetch_manifest.json")

GC = "grib"
SEASONAL = "seasonal-monthly-single-levels"

# tag, centre, system, expected lead months - the same table the fetcher
# uses, for the case where the registry does not have the model yet
SYSTEMS = [
    ("ecmwf-seas5",     "ecmwf",       "51",  7),
    ("ukmo-gloseas6",   "ukmo",        "610", 6),
    ("eccc-canesm5",    "eccc",        "4",   7),
    ("eccc-gem5",       "eccc",        "5",   7),
    ("cmcc-sps4",       "cmcc",        "4",   7),
    ("dwd-gcfs2",       "dwd",         "22",  7),
    ("meteo-france-s9", "meteo_france", "9",  6),
    ("jma-jra3",        "jma",         "4",   6),
    ("bom-access-s2",   "bom",         "2",   6),
]


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def model_table():
    """tag -> {centre, system, init, leads} from the registry, with the
    hard-coded table as the fallback for a model that is not there yet."""
    reg = read_json(os.path.join(DATA, "models_fetched.json"), {}) or {}
    out = {}
    for tag, centre, system, leads in SYSTEMS:
        rec = reg.get(tag, {}) or {}
        init = rec.get("init")
        out[tag] = {
            "centre": rec.get("centre", centre),
            "system": str(rec.get("system", system)),
            "init": init,
            "leads": int(rec.get("leads") or rec.get("expected_leads") or leads),
        }
    return out


def stray_job_ids():
    """the older scripts wrote the job id into a text file - keep them."""
    found = {}
    for path in sorted(glob.glob(os.path.join(DATA, "*job*.txt"))):
        name = os.path.basename(path)
        with open(path) as f:
            for line in f:
                jid = line.split()[0] if line.split() else ""
                if len(jid) > 30 and jid.count("-") >= 4:
                    found.setdefault(name, jid)
    return found


def carry_over(previous, entries):
    """Keep the job ids that are already recorded.

    The manifest is regenerated from the registry, but the job id is only
    known once the job has been made - so a regeneration must NOT throw the
    recorded ids away.  They are the thing that makes a wipe cheap.
    """
    old = {j.get("target"): j for j in previous or []}
    for e in entries:
        prev = old.get(e.get("target"))
        if not prev:
            continue
        for k in ("job", "request", "dataset"):
            if not e.get(k) and prev.get(k):
                e[k] = prev[k]
    return entries


def main():
    jobs = []
    table = model_table()
    previous = read_json(OUT, {}) or {}

    for tag, m in sorted(table.items()):
        if not m["init"]:
            continue
        year, month = m["init"].split("-")
        leads = [str(k) for k in range(1, m["leads"] + 1)]
        base = {
            "originating_centre": m["centre"],
            "system": m["system"],
            "variable": "snowfall",
            "year": year,
            "month": month,
            "leadtime_month": leads,
            "data_format": GC,
        }
        for product, fname in (("monthly_mean", "snowfall_monthly.grib"),
                               ("hindcast_climate_mean", "snowfall_hindcast.grib")):
            req = dict(base)
            req["product_type"] = product
            jobs.append({
                "model": tag,
                "target": "data/models/%s/%s" % (tag, fname),
                "dataset": SEASONAL,
                "request": req,
                "note": "the model's own %s" % (
                    "forecast" if product == "monthly_mean"
                    else "hindcast climate (the anomaly baseline)"),
            })

    # the daily 10 hPa wind jobs: the registry is tracked, so the ids are
    # known even after the data is gone
    daily = read_json(os.path.join(DATA, "daily_jobs.json"), {}) or {}
    for j in daily.get("jobs", []) or []:
        target = j.get("target") or ("data/models/%s/u10_daily.grib" % j.get("tag"))
        jobs.append({
            "model": j.get("tag"),
            "target": target,
            "dataset": SEASONAL.replace("single-levels", "pressure-levels"),
            "request": j.get("request"),
            "job": j.get("job"),
            "note": "the daily 10 hPa wind chunk",
        })

    for name, jid in stray_job_ids().items():
        jobs.append({
            "model": name.replace("_job", "").replace(".txt", ""),
            "target": "data/%s" % name,
            "job": jid,
            "note": "a job id kept from an earlier fetch",
        })

    manifest = {
        "note": "what the site needs, and how to get it back. "
                "regenerate with tools/write_fetch_manifest.py",
        "jobs": carry_over(previous.get("jobs", []), jobs),
    }
    with open(OUT, "w") as f:
        json.dump(manifest, f, indent=1)
    print("wrote %s (%d entries)" % (OUT, len(jobs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
