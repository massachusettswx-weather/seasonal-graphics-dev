#!/usr/bin/env python3
"""Point the seasonal pulls at the init the release calendar says they are on.

THE OWNER'S WORD (27 November 2026): "we really need to start working on
getting ready to receive the December seasonals whenever the first seasonal
comes in to December 10th... we can enact schedules for whenever is the
nominal dissemination time of seasonal guidance".

THE PROBLEM THIS SOLVES.  The daily pulls are pointed at an init by two
files that were written by hand for the November rollover:

    data/daily_centres.json          the 10 hPa wind pulls
    data/snow_daily_centres.json     the snowfall pulls

They carried "year": 2026, "month": 11.  Without them being moved, a
December release would be fetched for November - the archive would refuse
the request, or the panels would be drawn from the old init and the cards
would claim the new one.

THE RULE IS NOT WRITTEN DOWN HERE.  init_info holds the release calendar
- the ECMWF publishes on the 6th of the month and every other centre on
the 10th - so a centre is on this month's init from its release day and
on last month's before it.  This script asks that module, so the December
rollover is a one-step move and nothing has to be edited by hand.

    python3 tools/seasonal_init_plan.py            # show the plan
    python3 tools/seasonal_init_plan.py --apply    # write the two files
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import init_info                                          # noqa: E402

DATA = os.path.join(ROOT, "data")
# the 10 hPa wind pulls: the ECMWF is deliberately absent - the SPV
# charts are drawn from the other centres' daily series
DAILY = ["cmcc-sps4", "dwd-gcfs2", "eccc-canesm5", "eccc-gem5",
         "ukmo-gloseas6", "meteo-france-s9"]
# the snowfall pulls: the ECMWF is in this one
SNOW = ["ecmwf-seas5"] + DAILY
# how many days each pull asks for: a year, trimmed later by each model's
# own end of run
N_DAYS = 365


def centre_of(tag):
    """The CDS centre a tag belongs to, as the pull files want it."""
    return {"meteo-france-s9": "meteo_france"}.get(
        tag, init_info.centre_of(tag))


def system_of(tag):
    """The CDS system number of a tag."""
    return int(init_info.CENTRES[tag][1])


def entry(tag):
    init = init_info.newest_init(tag)
    y, m = init.split("-")
    return {"tag": tag, "centre": centre_of(tag), "system": system_of(tag),
            "year": int(y), "month": int(m), "n_days": N_DAYS}


def read_json(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:                                    # noqa: BLE001
        return []


def write_json(path, rows):
    with open(path, "w") as fh:
        json.dump(rows, fh, indent=1)
    print("   %s: %d centre(s)" % (os.path.relpath(path, ROOT), len(rows)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="write the two centre files")
    args = ap.parse_args()

    print("== the seasonal release calendar")
    moved, waiting = [], []
    for tag in SNOW:
        newest = init_info.newest_init(tag)
        have = init_info.recorded_init(tag)
        day = init_info.RELEASE_DAY.get(init_info.centre_of(tag),
                                         init_info.DEFAULT_RELEASE_DAY)
        if newest != have:
            moved.append((tag, have, newest))
            print("   %-18s %s -> %s   (released on the %s)"
                  % (tag, have, newest, day))
        else:
            waiting.append(tag)
            print("   %-18s %s            (already on it)"
                  % (tag, have))
    if not moved:
        print("   every centre is already on the init the calendar says")
    else:
        print("   %d centre(s) have moved" % len(moved))

    daily = [entry(t) for t in DAILY]
    snow = [entry(t) for t in SNOW]
    if not args.apply:
        print("== the plan (nothing written)")
        for tag, rows in (("data/daily_centres.json", daily),
                          ("data/snow_daily_centres.json", snow)):
            print("   %s:" % tag)
            for r in rows:
                print("      %-18s %s %04d-%02d"
                      % (r["tag"], r["centre"], r["year"], r["month"]))
        return 0

    print("== writing the centre files")
    write_json(os.path.join(DATA, "daily_centres.json"), daily)
    write_json(os.path.join(DATA, "snow_daily_centres.json"), snow)
    return 0


if __name__ == "__main__":
    sys.exit(main())
