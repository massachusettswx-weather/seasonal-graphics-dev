#!/usr/bin/env python3
"""Carry the ECMWF's SEAS5 field over to the interactive map.

WHY
---
The static pages and the interactive map are two renderings of ONE
dataset.  The static panels are PNGs and the map is a set of rasters, but
both are drawn from the same forecast and the same hindcast climate, so
a centre that is on the static pages has, in principle, everything the
map needs.

The catch is that the map's exporter reads the centre's GRIB out of
data/models/<tag>/, and that folder is GITIGNORED: a sandbox rebuild
takes it away.  So the map loses a centre the static pages still carry,
and the only way to get it back is a fresh request to the archive - hours
of queue time for data that is already in the repository.

For the ECMWF it IS already in the repository.  The SEAS5 fetch wrote:

    data/seas5_<init>_snow_em.npz   the ensemble mean, six lead months,
                                     the model's own 1 degree grid
    data/seas5_<init>_snow_hc.npz   the model's own hindcast climate

and BOTH ARE COMMITTED TO GIT.  They are the same numbers the static
panels are drawn from (the same fetch, the same init), so the map can be
built from them directly - no queue, no request, no waiting.

WHAT THIS DOES
--------------
It writes the pair into data/models/ecmwf-seas5/ in the convention the
exporter already understands:

    data/models/ecmwf-seas5/snowfall_monthly.npz
    data/models/ecmwf-seas5/snowfall_hindcast.npz

so the exporter picks them up with no change at all, and the field it
paints is the model's OWN grid, exactly as it would have been from the
GRIB.

THE ARITHMETIC IS THE EXPORTER'S
--------------------------------
The exporter computes, for a monthly-mean field:

    field = rate * days * 86400 * 1000 / 25.4 * SNOW_RATIO

where the rate is in m w.e. s-1, so this is millimetres of water
equivalent per month, turned into inches and then into inches of snow
depth (the house 10:1 ratio).  The npz carries the same rate, so the
same arithmetic applies and the result is the same field - that is what
makes the map and the static panels the same map.

The HINDCAST CLIMATE is the same kind of field: a rate in m w.e. s-1 for
the same month, and it is the model's OWN climate, which is the only
honest baseline for the anomaly.

Usage:
    python3 tools/carry_over_seas5.py             # carry over what is there
    python3 tools/carry_over_seas5.py --init 202611
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
MDIR = os.path.join(DATA, "models")
TAG = "ecmwf-seas5"

sys.path.insert(0, ROOT)
import plot_snow_models as PSM            # noqa: E402
import init_info                          # noqa: E402


def find_sources(init=None):
    """-> (forecast npz, climate npz) or (None, None)."""
    if init:
        cands = [init]
    else:
        # every committed SEAS5 forecast, newest first
        cands = []
        for fn in sorted(os.listdir(DATA)):
            if fn.startswith("seas5_") and fn.endswith("_snow_em.npz"):
                cands.append(fn[len("seas5_"):-len("_snow_em.npz")])
        cands.sort(reverse=True)
    for c in cands:
        f = os.path.join(DATA, "seas5_%s_snow_em.npz" % c)
        h = os.path.join(DATA, "seas5_%s_snow_hc.npz" % c)
        if os.path.exists(f) and os.path.exists(h):
            return f, h, c
    return None, None, None


def months_from_steps(init, steps):
    """The (year, month) each lead month represents.

    The same rule the GRIB reader uses: a monthly mean covers
    [dataDate, valid), so the month it represents is the month that
    contains (valid - 1 day).
    """
    from datetime import datetime as _dt, timedelta as _td
    # the init may be written 202611 or 2026-11
    digits = init.replace("-", "")
    y, m = int(digits[:4]), int(digits[4:6])
    d0 = _dt(y, m, 1)
    out = []
    for s in steps:
        v = d0 + _td(hours=int(s)) - _td(days=1)
        out.append((v.year, v.month))
    return out


def write_npz(path, months, rates, lat, lon, meta):
    """The convention the exporter reads: months, values, lat, lon, meta.

    `values` is (members, months, lat, lon) - the ENSEMBLE MEAN, so it
    is written as a single member.  The mean of one member is the mean.
    """
    vals = np.asarray(rates, float)[None, ...]     # (1, months, lat, lon)
    np.savez_compressed(
        path,
        months=np.array(["%04d-%02d" % (y, m) for (y, m) in months]),
        member_numbers=np.array([0]),
        values=vals.astype(np.float32),
        lat=np.asarray(lat, float),
        lon=np.asarray(lon, float),
        meta=np.array(json.dumps(meta)),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default=None,
                    help="the init to carry over, e.g. 202611 (default: the "
                         "newest committed one)")
    ap.add_argument("--force", action="store_true",
                    help="carry over even if the GRIB is already on disk")
    args = ap.parse_args()

    f, h, c = find_sources(args.init)
    if f is None:
        print("no committed SEAS5 field to carry over "
              "(data/seas5_*_snow_em.npz)")
        return 1

    d = os.path.join(MDIR, TAG)
    os.makedirs(d, exist_ok=True)
    out_f = os.path.join(d, "snowfall_monthly.npz")
    out_h = os.path.join(d, "snowfall_hindcast.npz")

    if os.path.exists(out_f) and not args.force:
        print("%s is already there - nothing to do (use --force to redo it)"
              % out_f)
        return 0

    em = np.load(f)
    hc = np.load(h)
    lat, lon = np.asarray(em["lat"], float), np.asarray(em["lon"], float)
    rates = np.asarray(em["rates"], float)
    hc_rates = np.asarray(hc["rates"], float)

    # the init the file belongs to, and the months it covers.  The file's
    # name carries it as 202611; the state file writes it as 2026-11.
    y, m = int(c[:4]), int(c[4:6])
    init = "%04d-%02d" % (y, m)
    months = months_from_steps(init, em["steps"])
    hc_months = months_from_steps(init, hc["steps"])

    print("carrying over %s (%s)" % (TAG, init))
    print("  %s: %d lead months, %d x %d grid" %
          (os.path.basename(f), len(months), len(lat), len(lon)))
    print("  the months: %s" % ", ".join("%04d-%02d" % m for m in months))

    write_npz(out_f, months, rates, lat, lon,
              dict(tag=TAG, init=init, kind="carried-over",
                   source=os.path.relpath(f, ROOT), members=51))
    write_npz(out_h, hc_months, hc_rates, lat, lon,
              dict(tag=TAG, init=init, kind="hindcast-climate",
                   source=os.path.relpath(h, ROOT)))
    for p in (out_f, out_h):
        print("  wrote %s (%.0f kB)" %
              (os.path.relpath(p, ROOT), os.path.getsize(p) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
