"""NOAA's CORe at 3-hourly resolution - the analysis at every three hours.

Why (23 Nov 2026, the owner's question):  the chart joins the reanalysis to
the model's forecast, and it reads as ONE CONTINUOUS FORECAST - the
reanalysis's half runs straight into the model's.  Two things hide the
real difference:

  * the DAILY file holds the day's MEAN (stepRange 0-21), so the chart's
    analysis half ends with a day's mean while the forecast half starts at
    an instant up to 25 hours later, on days when the stratosphere was
    falling 400-700 m2/s2;
  * the chart's first colour band is +-0.2 sigma, and the real difference
    between two analyses of the same atmosphere is about 0.18 sigma.

The bucket's 3-hourly tree is the SAME product - same system, same levels,
same grid - and it is current (it holds the analysis up to the present
hour).  The day's mean in the daily file is the mean of the day's eight
3-hourly analyses, which is how the two are checked against each other.

The pull reads the same way as the daily one: the `.idx` inventory and a
byte range for each message, so a stamp costs a megabyte instead of forty.

Inputs:
  data/polar_core_3hourly.json   the stamps that have been pulled
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import G0, zonal_mean  # noqa: E402

BUCKET = ("https://storage.googleapis.com/noaa-nws-ncep-core/grib/3hour/pgb/"
          "%s/%s/pgb.%s")
OUT = os.path.join(DATA, "polar_core_3hourly.json")

# the levels the polar section draws
LEVELS = [10, 30, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]
# The geopotential height.  NOAA's `.idx` writes it as "HGT" but the GRIB
# message itself carries the shortName "gh", and EVERY level in the file
# holds eleven variables - so a decoder that filters on the level alone
# reads the stream function and gets a number that is millions of times
# too large.
HEIGHT_NAMES = ("gh", "HGT", "Geopotential height")
# A polar-cap mean of the geopotential that is not inside this is a
# decoding fault, not a value.  The bound is wide because the quantity
# itself varies by three orders of magnitude with the level: about
# 290,000 m2/s2 at 10 hPa and about 200 m2/s2 at 1000 hPa.
SANITY = (0.0, 1.0e6)
# the eight analyses of a day
HOURS = ["00", "03", "06", "09", "12", "15", "18", "21"]


def url(stamp):
    """'2026112100' -> the 3-hourly file's URL."""
    return BUCKET % (stamp[:4], stamp[4:6], stamp)


def get(url, start=None, end=None, tries=4, timeout=180):
    import requests
    headers = {}
    if start is not None:
        headers["Range"] = "bytes=%d-%d" % (start, end - 1)
    last = ""
    for k in range(tries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code in (200, 206):
                return r
            last = "HTTP %d" % r.status_code
        except Exception as e:                      # noqa: BLE001
            last = "%s: %s" % (type(e).__name__, str(e)[:80])
    raise RuntimeError("%s -> %s" % (url, last))


def inventory(stamp):
    """-> [(offset, var, level)] of every message of one file."""
    text = get(url(stamp) + ".idx").text
    rows = []
    for line in text.splitlines():
        p = line.split(":")
        if len(p) < 5:
            continue
        try:
            off = int(p[1])
        except ValueError:
            continue
        rows.append((off, p[3], p[4]))
    return rows


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
                snm = eccodes.codes_get(gid, "shortName")
                if snm not in HEIGHT_NAMES:
                    continue
                la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                lats = np.unique(la)[::-1]
                lons = np.unique(np.asarray(
                    eccodes.codes_get_array(gid, "longitudes"), float))
                v = v.reshape(len(lats), len(lons))
                val = float(zonal_mean(v * G0, lats))
                if SANITY[0] <= val <= SANITY[1]:
                    out = val
            finally:
                eccodes.codes_release(gid)
    return out


def cap_mean_all(blob, levels, tmp):
    """-> {level: the polar-cap mean} for every wanted level in a file.

    The fallback for a stamp whose INVENTORY is empty: NOAA publishes some
    of the three-hourly files with a zero-byte `.idx` (the 00Z stamp of
    18 Nov 2026, for one), so there are no byte ranges to read and the
    whole file is decoded instead.  It costs forty megabytes instead of
    one, and it is exact - the same messages, the same polar-cap mean.
    """
    import eccodes
    with open(tmp, "wb") as f:
        f.write(blob)
    out = {}
    with open(tmp, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:                       # noqa: BLE001
                break
            if gid is None:
                break
            try:
                try:
                    tol = eccodes.codes_get(gid, "typeOfLevel")
                    lev = int(eccodes.codes_get(gid, "level"))
                    snm = eccodes.codes_get(gid, "shortName")
                except Exception:                   # noqa: BLE001
                    continue
                if tol != "isobaricInhPa" or lev not in levels:
                    continue
                if snm not in HEIGHT_NAMES:
                    continue
                la = np.asarray(eccodes.codes_get_array(gid, "latitudes"),
                                float)
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                lats = np.unique(la)[::-1]
                lons = np.unique(np.asarray(
                    eccodes.codes_get_array(gid, "longitudes"), float))
                v = v.reshape(len(lats), len(lons))
                val = float(zonal_mean(v * G0, lats))
                if SANITY[0] <= val <= SANITY[1]:
                    out[lev] = val
                else:
                    print("   %s %d hPa: the value %s is out of range"
                          % (stamp, lev, "%.3g" % val), flush=True)
            finally:
                eccodes.codes_release(gid)
    return out


def one_stamp(stamp, levels=LEVELS):
    """-> {level: the polar-cap mean} for one 3-hourly analysis."""
    try:
        rows = inventory(stamp)
    except Exception as e:                           # noqa: BLE001
        # the tree does not hold every three hours of the last day yet
        print("   %s : not published (%s)" % (stamp, str(e)[:60]))
        return {}
    if not rows:
        # an EMPTY inventory: NOAA wrote a zero-byte .idx for this stamp.
        # The file itself is complete, so the whole thing is decoded.
        print("   %s : the inventory is empty - decoding the whole file"
              % stamp, flush=True)
        tmp = os.path.join(DATA, "_core3h_%s.grb" % stamp)
        try:
            r = get(url(stamp) + ".grb")
            out = cap_mean_all(r.content, levels, tmp)
        except Exception as e:                       # noqa: BLE001
            print("   %s : the whole file failed (%s)" % (stamp, str(e)[:60]))
            out = {}
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return out
    jobs = []
    for i, (off, var, lev) in enumerate(rows):
        if var != "HGT":
            continue
        mb = lev.split(" mb")[0]
        if not mb.isdigit() or int(mb) not in levels:
            continue
        end = rows[i + 1][0] if i + 1 < len(rows) else None
        jobs.append((int(mb), off, end))
    out = {}
    tmp = os.path.join(DATA, "_core3h_%s.grb" % stamp)
    for mb, off, end in jobs:
        if end is None:
            r = get(url(stamp) + ".grb", off, off + 4000000)
        else:
            r = get(url(stamp) + ".grb", off, end)
        try:
            out[mb] = cap_mean(r.content, tmp)
        except Exception as e:                       # noqa: BLE001
            print("   %s %d hPa: FAILED (%s)" % (stamp, mb, str(e)[:70]))
    if os.path.exists(tmp):
        os.remove(tmp)
    return out


def stamps_for(days, hours=HOURS):
    """The stamps of the given days ('20261121')."""
    out = []
    for d in days:
        for h in hours:
            out.append(d + h)
    return out


def ensure(days, levels=None):
    """-> the cache, with every stamp of these days present.

    The cache keeps what it has, so a day that is already there costs
    nothing.  This is what the chart builder calls when its own window is
    not covered - the pull needs no key and no queue, and it is the only
    way the reanalysis half can be drawn at an INSTANT.
    """
    levels = levels or LEVELS
    out = {}
    if os.path.exists(OUT):
        try:
            out = json.load(open(OUT))
        except Exception:                           # noqa: BLE001
            out = {}
    stamps = []
    for d in days:
        stamps.extend(stamps_for([d]) if len(d) == 8 else [d])
    # an EMPTY record is a failed fetch that was cached by an earlier
    # version of this script - it must be treated as missing, or the
    # window is never completed and the chart falls back to the daily file
    todo = [s for s in stamps if not (out.get(s) or {})]
    if not todo:
        return out
    print("   %d stamps to pull (%d levels each)" % (len(todo), len(levels)),
          flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for stamp, rec in zip(todo, ex.map(lambda s: one_stamp(s, levels), todo)):
            if not rec:
                continue
            out[stamp] = {str(k): v for k, v in rec.items()}
            print("   %s : %d levels" % (stamp, len(rec)), flush=True)
            json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
    return out


def main():
    args = sys.argv[1:]
    levels = LEVELS
    if "--level" in args:
        i = args.index("--level")
        levels = [int(x) for x in args[i + 1].split(",")]
        del args[i:i + 2]
    days = args or ["20261121"]
    out = ensure(days, levels)
    print("   written: %s" % OUT)
    check_daily(out)


def check_daily(out):
    """The day's mean of the 3-hourly analyses against the daily file.

    If the two agree, the daily file's day's mean IS the mean of the day's
    eight 3-hourly analyses - the same product, and the 3-hourly tree can
    stand in for the daily one wherever an instant is wanted.
    """
    daily = os.path.join(DATA, "polar_core_recent.npz")
    if not os.path.exists(daily):
        return
    d = np.load(daily, allow_pickle=True)
    levels = [int(x) for x in d["levels"]]
    times = [str(t) for t in d["times"]]
    vals = np.asarray(d["values"], float)
    i10 = levels.index(10)
    for day in sorted(set(t[:10].replace("-", "") for t in times)):
        hours = [day + h for h in HOURS if (day + h) in out
                 and "10" in out[day + h]]
        if len(hours) < 8:
            continue
        mean3 = float(np.mean([out[h]["10"] for h in hours]))
        rows = [k for k, t in enumerate(times) if t[:10].replace("-", "") == day]
        if not rows:
            continue
        print("   %s : the daily file %10.1f   the 3-hourly mean %10.1f   "
              "diff %+7.1f m2/s2"
              % (day, vals[rows[-1], i10], mean3, mean3 - vals[rows[-1], i10]))


if __name__ == "__main__":
    main()
