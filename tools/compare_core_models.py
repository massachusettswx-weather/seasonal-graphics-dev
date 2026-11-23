"""The reanalysis against the models' own analyses, at the SAME instant.

The owner's question (23 Nov 2026): *"just need the past 6hr CORe analysis
to differ from GEFSv12, SEAS5, EC46 analyses if they do because it looks
like one continuous forecast from reanalysis to model forecasts"*.

So this puts, side by side and at the same instant:

  * NOAA's CORe analysis (the 3-hourly tree - the same product as the
    daily file, whose day's mean is the mean of the day's eight 3-hourly
    analyses);
  * the GEFSv12's own analysis of its init (lead f000, the ensemble mean);
  * the EC46's and the SEAS5's first forecast points, which are the
    closest thing each of those products carries to an analysis.

and it says how far apart they are, in m2/s2 and in the chart's own sigma.

Inputs:
  data/polar_core_3hourly.json   the CORe at 3-hourly resolution
  data/polar_gefs_f000.json       the GEFS's own analysis
  data/polar_model_z.json         the GEFS's and the SEAS5's series
  data/polar_ec46_z.json          the EC46's series
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import plot_polar_cap as P  # noqa: E402
from polar_cap import daily_climate  # noqa: E402

CORE3H = os.path.join(ROOT, "data", "polar_core_3hourly.json")
F000 = os.path.join(ROOT, "data", "polar_gefs_f000.json")


def core_at(stamp, level=10):
    """The CORe's analysis at one 3-hourly stamp."""
    if not os.path.exists(CORE3H):
        return None
    rec = json.load(open(CORE3H)).get(stamp)
    if not rec:
        return None
    v = rec.get(str(level))
    return float(v) if v is not None else None


def sigma_on(day, level=10):
    """The chart's own daily sigma at 10 hPa on a day."""
    cmonths, clevs, cmean, csigma = P.load_clim_monthly(P.CLIM_CORE)
    cols = [clevs.index(level)]
    _, s = daily_climate([day], cmonths, cmean[:, cols], csigma[:, cols])
    return float(s[0, 0])


def series(tag):
    mt, mv, sl = P.load_series(P.cache_for(tag), tag)
    j = [int(x) for x in sl].index(10)
    return {t[:10]: float(mv[k, j]) for k, t in enumerate(mt)}


def stamp_of(day, hour):
    """'2026-11-21' + '00' -> '2026112100'."""
    return day.replace("-", "") + hour


def main():
    gefs = series("gefsv12")
    ec46 = series("ec46")
    seas5 = series("ecmwf-seas5")
    f000 = json.load(open(F000)) if os.path.exists(F000) else None

    rows = []
    # 1. the GEFS's own analysis against the CORe's analysis of the same instant
    if f000:
        d = f000["date"]
        hour = f000["hour"]
        day = "%s-%s-%s" % (d[:4], d[4:6], d[6:8])
        c = core_at(stamp_of(day, hour))
        if c is not None:
            rows.append(("GEFSv12 analysis (f000, %d members)" % len(f000["members"]),
                         day, hour, float(f000["mean"]), c))
    # 2. each model's first forecast point against the CORe's analysis of
    #    the same instant
    for tag, s, label in (("gefsv12", gefs, "GEFSv12 day 1 (f012)"),
                           ("ec46", ec46, "EC46 day 1 (f024)"),
                           ("ecmwf-seas5", seas5, "SEAS5 day 1")):
        if not s:
            continue
        first = sorted(s)[0]
        hour = "00" if tag == "ec46" else ("12" if tag != "ecmwf-seas5" else "12")
        c = core_at(stamp_of(first, hour))
        if c is not None:
            rows.append((label, first, hour, s[first], c))

    print("%-28s %-12s %-6s %12s %12s %10s %9s"
          % ("what", "the day", "hour", "the model", "the CORe", "difference",
             "sigma"))
    print("-" * 96)
    for label, day, hour, model, core in rows:
        d = model - core
        s = sigma_on(day)
        print("%-28s %-12s %-6s %12.1f %12.1f %10.1f %9.3f"
              % (label, day, hour + "Z", model, core, d, d / s))
    print()
    print("the chart's own sigma at 10 hPa on 21 Nov: %8.1f m2/s2"
          % sigma_on("2026-11-21"))
    print("the chart's first colour band: +-0.2 sigma, so a difference below "
          "0.2 sigma cannot change a pixel")


if __name__ == "__main__":
    main()
