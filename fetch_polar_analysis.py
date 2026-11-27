"""The ECMWF's own ANALYSIS, day by day, for the polar sections.

WHY IT IS NEEDED (27 November 2026).  The section's reanalysis half is
NOAA's CORe, and CORe runs about two days behind the day it is fetched
for.  A medium-range product's forecast begins tomorrow, so the
reanalysis stops short of it and the section would carry a band of
nothing where the two halves meet.

The gap is closed with the ECMWF's OWN ANALYSIS: the 0-hour step of the
open data is the state the run started from, and it agrees with the CORe's
polar-cap mean at 10 hPa to about 23 m - the same order as the difference
between the two centres.  So the chart can say "the reanalysis to the
25th, the ECMWF's analysis to the 27th, the forecast from the 28th", and
a reader can see exactly where the observation ends.

THE CACHE ACCUMULATES.  The open data keeps about four days, so the
analysis of a day is only there for four days - but the seasonal's own
analysis day is the first of its month, and that is twenty-five days
before the seasonal is published.  The cache therefore keeps what it has
fetched, and the daily job tops it up.

BOTH CYCLES ARE KEPT.  A run is initialised at 00Z or at 12Z, and the
analysis it started from is the 0-hour step of that cycle - so the cache
holds the 12Z and the 00Z analysis of a day separately, and the chart
takes the one that matches the run it is drawing.  The open data only
publishes ELEVEN levels (there is no 30 hPa, measured on 27 November
2026), so a record carries the levels it has and the plotter draws the
section on the levels the three sides share.

    python3 fetch_polar_analysis.py            # top the cache up
    python3 fetch_polar_analysis.py --days 10  # a longer window

It writes:
    data/polar_model_analysis.json
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from fetch_polar_eps import file_url, reduce_message, session  # noqa: E402
from polar_cap import LEVELS, SECTORS                              # noqa: E402

OUT = os.path.join(DATA, "polar_model_analysis.json")
# HOW MANY DAYS OF ANALYSIS ARE KEPT.  The cache has to hold the seasonal's
# own analysis day - the first of its month - until the seasonal is
# published a month later, and a little more than that for safety.  Ninety
# days is three months, and the file is about 260 kB at that size.
KEEP = 90
# the cycles of a day that are cached: the 12Z one is preferred, because
# the reanalysis half of the section is measured at 12Z
CYCLES = ("12z", "00z")


def load():
    if not os.path.exists(OUT):
        return {}
    try:
        with open(OUT) as fh:
            d = json.load(fh)
    except Exception:                                    # noqa: BLE001
        return {}
    return d if isinstance(d, dict) else {}


def save(cache):
    # the cache only ever holds a fixed number of days: the oldest go
    days = sorted(cache)
    for d in days[:-KEEP]:
        cache.pop(d)
    with open(OUT + ".tmp", "w") as fh:
        json.dump(cache, fh, indent=1)
    os.replace(OUT + ".tmp", OUT)
    print("   the analysis cache: %d day(s) -> %s"
          % (len(cache), os.path.relpath(OUT, HERE)), flush=True)


def put(cache, day, cyc, rec):
    """Put one cycle's analysis into the cache, and keep the day's own
    fields pointing at the cycle that is preferred.

    The day's fields are a copy of the preferred cycle's, so a reader that
    does not know about the cycles still finds the analysis where it
    expects it.
    """
    entry = cache.get(day)
    if not isinstance(entry, dict):
        entry = {}
    cycles = entry.get("cycles")
    if not isinstance(cycles, dict):
        cycles = {}
    cycles[cyc] = rec
    entry["cycles"] = cycles
    for key in ("values", "sectors", "levels", "cycle", "hour", "source"):
        entry[key] = rec.get(key)
    cache[day] = entry
    return entry


def put_values(cache, day, cyc, levels, cap, sectors):
    """Put one analysis into the cache from level -> value maps.

    The EPS's own fetcher reads the control's analysis and keeps it in its
    own state file; this is how that analysis is also kept in the shared
    cache, so that the chart of ANY model can close its seam with the
    ECMWF's own analysis of the day.
    """
    rec = {
        "values": [float(cap[str(l)]) for l in levels],
        "sectors": {name: [float(row[str(l)]) for l in levels]
                    for name, row in sectors.items()},
        "levels": [int(l) for l in levels],
        "cycle": cyc,
        "hour": "%02d" % int(cyc[:2]),
        "source": "the ECMWF's own analysis, the 0-hour step of the open "
                  "data's %s cycle" % cyc,
    }
    put(cache, day, cyc, rec)
    return rec


def fetch_day(day, cyc):
    """One day's ECMWF analysis -> {values, sectors, ...}, or None.

    The 0-hour step of the "oper" stream is the run's own analysis: the
    state the forecast started from.
    """
    url = file_url(day, cyc, "oper", 0, "index")
    r = session().get(url, timeout=180)
    if r.status_code != 200:
        return None
    rows = []
    for line in r.text.splitlines():
        try:
            d = json.loads(line)
        except Exception:                                # noqa: BLE001
            continue
        if d.get("param") != "z":
            continue
        try:
            lev = int(d.get("levelist"))
        except Exception:                                # noqa: BLE001
            continue
        if lev in LEVELS:
            rows.append((lev, int(d["_offset"]), int(d["_length"])))
    if not rows:
        return None
    grib = file_url(day, cyc, "oper", 0, "grib2")
    out, sec, grid = {}, {n: {} for n in SECTORS}, [None, None, 0, 0]
    for lev, off, length in rows:
        rr = session().get(grib, headers={"Range": "bytes=%d-%d"
                                          % (off, off + length - 1)},
                           timeout=180)
        if rr.status_code not in (200, 206):
            return None
        cap, s = reduce_message(rr.content, 1.0, grid)
        out[lev] = float(cap)
        for name in SECTORS:
            sec[name][lev] = float(s[name])
    if not out:
        return None
    # THE LEVELS THE OPEN DATA CARRIES, NOT THE HOUSE'S TWELVE.  The
    # open data does not publish 30 hPa (measured on 27 November 2026),
    # so the analysis comes with the eleven levels it has, and the
    # plotter draws the section on the levels both sides share.
    have = sorted(out)
    return {
        "values": [out[l] for l in have],
        "sectors": {name: [sec[name][l] for l in have] for name in SECTORS},
        "levels": have,
        "cycle": cyc,
        "hour": "%02d" % int(cyc[:2]),
        "source": "the ECMWF's own analysis, the 0-hour step of the open "
                  "data's %s cycle" % cyc,
    }


def fetch_day_into(cache, day, cyc):
    """One day's, one cycle's analysis -> into the cache.  -> True when it
    was fetched."""
    rec = fetch_day(day, cyc)
    if not rec:
        return False
    put(cache, day, cyc, rec)
    print("   the %s %s analysis: the 10 hPa polar-cap mean is %.1f"
          % (day, cyc, rec["values"][0]), flush=True)
    return True


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=6,
                    help="how many days back to look for")
    args = ap.parse_args()

    cache = load()
    today = datetime.now(timezone.utc).date()
    got = 0
    for back in range(0, args.days):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        entry = cache.get(d) or {}
        cycles = entry.get("cycles") or {}
        for cyc in CYCLES:
            if cyc in cycles and (cycles[cyc] or {}).get("values"):
                continue                      # this cycle is already cached
            try:
                if fetch_day_into(cache, d, cyc):
                    got += 1
            except Exception as e:                        # noqa: BLE001
                print("   the %s %s analysis FAILED: %r" % (d, cyc, e),
                      flush=True)
    save(cache)
    print("   %d new cycle(s)" % got, flush=True)


if __name__ == "__main__":
    main()
