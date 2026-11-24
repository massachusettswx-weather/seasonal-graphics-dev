"""The GEFSv12's OWN analysis (lead f000) - the model's analysis of its init.

The polar section joins the CORe's analysis to the model's forecast.  The
owner's question (23 Nov 2026) is whether the reanalysis and the model's
analysis really differ, because the chart reads as one continuous forecast
from the reanalysis into the model's.

The GEFS's f000 IS the model's own analysis of its init time, so it can be
put beside the CORe's analysis of the same instant: two analyses of the
same atmosphere, from two systems, with no interpolation anywhere.

This imports the running fetcher's machinery - it does not edit it.

Outputs:
  data/polar_gefs_f000.json   {date, hour, members, mean}
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import fetch_polar_gefs as G  # noqa: E402
from polar_cap import G0, zonal_mean  # noqa: E402

OUT_DIR = os.path.join(ROOT, "data")
LEVELS = [10, 30, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]
MEMBERS = ["gec00"] + ["gep%02d" % i for i in range(1, 31)]


def cap_mean(blob, tmp):
    """The polar-cap mean of one HGT message, in m2/s2."""
    import eccodes
    with open(tmp, "wb") as f:
        f.write(blob)
    out = None
    with open(tmp, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:                       # noqa: BLE001
                break
            if gid is None:
                break
            try:
                la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                lats = np.unique(la)[::-1]
                lons = np.unique(lo)
                v = v.reshape(len(lats), len(lons))
                out = float(zonal_mean(v * G0, lats))
            finally:
                eccodes.codes_release(gid)
    return out


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else "20261121"
    hour = sys.argv[2] if len(sys.argv) > 2 else "00"
    G.DATE, G.HOUR = date, hour
    G.HOSTS = G.live_hosts()
    print("   the cycle: %s %sZ   the hosts: %s" % (date, hour, G.HOSTS),
          flush=True)
    blobs = G.lead_members(MEMBERS, 0)
    vals = {}
    tmp = os.path.join(ROOT, "data", "_core_f000_tmp.grb")  # gitignored
    vals = {}
    for m in MEMBERS:
        row = {}
        for lev in LEVELS:
            if lev not in blobs.get(m, {}):
                continue
            try:
                row[str(lev)] = cap_mean(blobs[m][lev], tmp)
            except Exception as e:                   # noqa: BLE001
                print("   %s %d hPa: FAILED (%s)" % (m, lev, str(e)[:60]))
        if row:
            vals[m] = row
    if os.path.exists(tmp):
        os.remove(tmp)
    if not vals:
        print("   no member answered - nothing written")
        return
    # the ensemble mean and the spread at every level
    mean, spread = {}, {}
    for lev in LEVELS:
        col = [v.get(str(lev)) for v in vals.values() if v.get(str(lev)) is not None]
        if not col:
            continue
        arr = np.array(col, float)
        mean[str(lev)] = float(arr.mean())
        spread[str(lev)] = float(arr.max() - arr.min())
    print("   %d members" % len(vals))
    for lev in LEVELS:
        if str(lev) in mean:
            print("      %4d hPa   mean %10.1f   spread %6.1f"
                  % (lev, mean[str(lev)], spread[str(lev)]))
    out = os.path.join(OUT_DIR, "polar_analysis_gefsv12_%s%s.json"
                       % (date, hour))
    json.dump({"date": date, "hour": hour, "levels": LEVELS,
               "members": vals, "mean": mean, "spread": spread},
              open(out, "w"), indent=1, sort_keys=True)
    print("   written: %s" % out)


if __name__ == "__main__":
    main()
