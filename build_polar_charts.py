"""Rebuild every polar-cap time-height section that has data behind it.

The publisher calls this after the data changes.  The systems are NOT taken
from whatever happens to be in data/polar_model_z.json: they are the three
the section is for - the seasonal run, the sub-seasonal GEFS and the ECMWF
extended range - and a system with no series is not drawn.

  * plot_polar_cap.py removes the chart it would have drawn rather than
    leave one with no data behind it;
  * a chart that belongs to a system that is no longer shown (the METFR
    system 9 section, which the user took out on 14 Nov 2026) is removed
    here, so it cannot be left behind on the site.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output", "polar_cap")

# The systems the polar-cap section is for, in the order the page shows them.
#
# 14 Nov 2026: the user asked for the ECMWF extended range (the EC46) to be
# added, and for the METFR system 9 section to come out - so the list is
# the whole of it, and nothing is drawn that is not on it.
MODELS = [
    ("ecmwf-seas5", "ECMWF SEAS5", "SEAS5"),
    ("gefsv12", "NOAA GEFSv12 (35-day extended)", "GEFSv12"),
    ("ec46", "ECMWF EC46", "EC46"),
]

# the charts that used to be here and are not any more
RETIRED = ["meteo-france-s9"]


def tags():
    """-> (the tags that have a series on disk, is there a series file at all)."""
    import json
    out = []
    any_file = False
    for p in (os.path.join(HERE, "data", "polar_model_z.json"),
              os.path.join(HERE, "data", "polar_ec46_z.json")):
        if not os.path.exists(p):
            continue
        any_file = True
        try:
            d = json.load(open(p))
        except Exception as e:
            print("   the polar series file could not be read: %s" % str(e)[:90])
            continue
        for k in d:
            if k not in out:
                out.append(k)
    return out, any_file


def remove_retired():
    """Take out the charts of the systems that are no longer shown."""
    for tag in RETIRED:
        for p in (os.path.join(OUT, "polar_cap_%s.png" % tag),
                  os.path.join(HERE, "docs", "assets", "polar",
                               "polar_cap_%s.png" % tag)):
            if os.path.exists(p):
                os.remove(p)
                print("   the retired chart removed: %s" % p)


def main():
    remove_retired()
    have, any_file = tags()
    for tag, label, short in MODELS:
        if tag not in have:
            # No series on this machine.  The chart that is already published
            # is left alone: the series files are working data that is not
            # in the repo, and a section with real data behind it is better
            # than no section at all.  The retired systems are removed by
            # name above, so nothing is published that was taken out.
            print("   no series for %s yet" % tag)
            continue
        args = [sys.executable, "-u", "plot_polar_cap.py", tag, label]
        if short:
            args.append(short)
        r = subprocess.run(args, cwd=HERE, capture_output=True, text=True)
        out = (r.stdout or "").strip().splitlines()
        for line in out[-3:]:
            print("   %s" % line)
        if r.returncode != 0:
            print("   the %s section failed: %s"
                  % (tag, (r.stderr or "").strip().splitlines()[-1][:160]))
        # the same section split into the North Pacific and the North
        # Atlantic, when the sector means are on disk
        args2 = [sys.executable, "-u", "plot_polar_sectors.py", tag, label]
        if short:
            args2.append(short)
        r2 = subprocess.run(args2, cwd=HERE, capture_output=True, text=True)
        out2 = (r2.stdout or "").strip().splitlines()
        for line in out2[-2:]:
            print("   %s" % line)


if __name__ == "__main__":
    main()
