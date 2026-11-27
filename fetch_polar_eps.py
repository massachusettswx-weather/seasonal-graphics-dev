"""ECMWF EPS - the medium-range ensemble, read from ECMWF's own open data.

THE EPS IS THE 15-DAY ENSEMBLE: ECMWF's operational ensemble prediction
system - the control forecast plus fifty perturbed members - at BOTH cycles
of the run, 00Z and 12Z.  This script pulls it and reduces it to the same
two series the polar-cap sections are drawn from: the area-weighted polar
cap (60-90N) mean and the North Pacific and North Atlantic sector means, at
the ten pressure levels the section is drawn on.

    python3 fetch_polar_eps.py

WHY THE OPEN DATA AND NOT THE CLIMATE STORE.  The ECDS store's
`s2s-forecasts` dataset serves the EXTENDED-range ensemble and nothing
else: measured 27 Nov 2026, a request for the short window 24_48 of the
2026-11-25 00Z run came back with 101 members - that is ECMWF's 46-day
ensemble, the EC46's own members - and every `system` variant (1, 2, 1+2,
7) was refused by the job.  The form has no `system` field, so the medium
range itself cannot be asked for there.

ECMWF's OPEN DATA serves the EPS as it is: the deterministic forecast (the
control member) in the "oper" stream and the fifty perturbed members in the
"enfo" stream, both at 0.25 degrees, at 00Z and 12Z, out to 360 hours.  The
files are large (about 4.5 GB a step, every member and every field), but
each one comes with an INDEX file that says where every message sits in it,
so only the messages that are wanted - the geopotential at the ten levels -
are fetched, with a byte range each.

    https://storage.googleapis.com/ecmwf-open-data/<date>/<cycle>/ifs/0p25/
        oper/<date><hh>000000-<step>h-oper-fc.grib2   (+ .index)
        enfo/<date><hh>000000-<step>h-enfo-ef.grib2   (+ .index)

WHAT IS WRITTEN.  The series goes to data/polar_eps_z.json under the key
"eps", with the sector means beside it, and the state of the work into
data/polar_eps_jobs.json - so a restart picks up where it stopped instead of
fetching the same step twice.  Both files are in git.
"""
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import SECTORS, sector_mean, zonal_mean      # noqa: E402

OUT = os.path.join(DATA, "polar_eps_z.json")
STATE = os.path.join(DATA, "polar_eps_jobs.json")
# the shared cache the plotter reads; the series is merged into it under its
# own key, and every other model's record is left exactly as it was found
CACHE = os.path.join(DATA, "polar_model_z.json")
TAG = "eps"

BUCKET = "https://storage.googleapis.com/ecmwf-open-data"
# the levels the section is drawn on - the ten the climate store serves
LEVELS = [10, 50, 100, 200, 300, 500, 700, 850, 925, 1000]
# the days of the run: fifteen, which is all the EPS has
DAYS = 15
# the cycles of the run: the main 00Z suite and the main 12Z suite
CYCLES = ("00z", "12z")
# how many steps are fetched at once
WORKERS = 4
# the open data keeps about four days, so the search walks back that far
LOOKBACK_DAYS = 6


def g():
    """The standard gravity, for the geopotential HEIGHT the open data
    publishes: gh is in metres, the section wants m2/s2."""
    return 9.80665


# --------------------------------------------------------------------------
def session():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": "seasonal-graphics/1.0 (polar EPS)"})
    return s


def bucket_list(prefix, delimiter="/", limit=1000):
    """The names (or prefixes) under a path in the open-data bucket."""
    u = "https://storage.googleapis.com/storage/v1/b/ecmwf-open-data/o"
    out = []
    token = None
    while True:
        par = {"prefix": prefix, "maxResults": limit}
        if delimiter:
            par["delimiter"] = delimiter
        if token:
            par["pageToken"] = token
        r = session().get(u, params=par, timeout=120)
        if r.status_code != 200:
            break
        j = r.json()
        for p in j.get("prefixes", []):
            out.append(p if isinstance(p, str) else p.get("prefix", ""))
        for o in j.get("items", []):
            out.append(o.get("name", ""))
        token = j.get("nextPageToken")
        if not token:
            break
    return out


def file_url(day, cyc, stream, step, kind):
    """The URL of one file (or its index).

    The name carries the run's own timestamp: the date, the cycle's hour,
    then 0000 - so the 00Z cycle of 20261127 is 20261127000000 and the 12Z
    cycle of the same day is 20261127120000.
    """
    tag = "oper-fc" if stream == "oper" else "enfo-ef"
    return "%s/%s/%s/ifs/0p25/%s/%s%s0000-%dh-%s%s" % (
        BUCKET, day, cyc, stream, day, cyc[:2], step, tag,
        ".index" if kind == "index" else ".grib2")


def head_ok(url):
    """-> True when the file is there."""
    try:
        r = session().head(url, timeout=60, allow_redirects=True)
        return r.status_code == 200
    except Exception:                                # noqa: BLE001
        return False


def newest_run():
    """The newest run the open data has, and the cycles it has.

    The run date is the one whose BOTH cycles are published: the owner asked
    for the 00Z suite and the 12Z suite of the same run, and the 12Z cycle
    of a day appears some hours after its 00Z cycle.  When the day's 12Z
    cycle is not out yet, the day before is used - both of its cycles are
    there, and it is the newest run that has both.
    """
    today = datetime.now(timezone.utc).date()
    for back in range(0, LOOKBACK_DAYS):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        cycles = []
        for cyc in CYCLES:
            if head_ok(file_url(d, cyc, "enfo", 36, "index")):
                cycles.append(cyc)
        if len(cycles) == len(CYCLES):
            return d, cycles
        if back == 0:
            print("   the newest run %s has only the %s cycle(s) - the day "
                  "before is used" % (d, " and ".join(cycles) or "none"),
                  flush=True)
    return None, []


def day_steps(cyc):
    """-> {day number (1..15): the step that lands on that day at 12Z}.

    The 12Z step of a day is the one the house's other daily series use.
    For the 00Z cycle it is 36 hours on (a day and a half, so 12Z on the
    day after the run) and for the 12Z cycle it is 24 hours on - so both
    cycles' day k falls on the SAME calendar day, which is what lets the
    two be averaged together.
    """
    hour = int(cyc[:2])
    out = {}
    for k in range(1, DAYS + 1):
        step = 24 * k
        while (step + hour) % 24 != 12:
            step += 1
        out[k] = min(step, 360)
    return out


# --------------------------------------------------------------------------
def reduce_message(buf, scale, grid=None):
    """One GRIB message -> (the polar cap mean, {sector: mean}).

    The message is the global field at one level for one member; the
    reductions are the house's own (polar_cap.zonal_mean and
    polar_cap.sector_mean), so the EPS's series is cut exactly like the
    EC46's and the GEFS's.

    THE GRID IS THE SAME for every message of a step - the run is on one
    grid - so the latitude and longitude arrays (a million numbers each)
    are read ONCE and then handed over in the `grid` box.  They are the
    biggest thing the decode does, and reading them again for every member
    of every level is pure waste.

    THE SHAPE COMES FROM THE ARRAYS, not from the "Ni" and "Nj" keys:
    these messages are GRIB2 and carry neither of those (measured: both
    read back as 0), so the grid is read as the number of distinct
    latitudes and longitudes the message itself carries.
    """
    import eccodes
    gid = eccodes.codes_new_from_message(buf)
    if gid is None:
        raise ValueError("the message did not open")
    try:
        v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
        if grid is not None and grid[0] is not None:
            la, lo, nj, ni = grid[0], grid[1], grid[2], grid[3]
        else:
            la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
            lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
            nj = int(np.unique(la).size)
            ni = int(np.unique(lo).size)
            if grid is not None:
                grid[0], grid[1], grid[2], grid[3] = la, lo, nj, ni
        if v.size != nj * ni:
            raise ValueError("the message does not fit the grid (%d points, "
                             "%d x %d)" % (v.size, nj, ni))
        field = v.reshape(nj, ni)
        lats = la.reshape(nj, ni)[:, 0]
        lons = lo.reshape(nj, ni)[0, :]
        field = field * scale
        cap = zonal_mean(field, lats)
        sec = {}
        for name, (a, b) in SECTORS.items():
            sec[name] = sector_mean(field, lats, lons, a, b)
        return cap, sec
    finally:
        eccodes.codes_release(gid)


def fetch_step(day, cyc, step):
    """One step of one cycle -> (the cap mean per level, the sector means,
    the number of members behind them).

    The control member comes from the "oper" stream and the fifty perturbed
    members from the "enfo" stream; every message is fetched with a byte
    range at the offset the index gives, and the members are averaged - the
    section shows the ENSEMBLE MEAN.
    """
    s = session()
    out = {}
    members = 0
    # THE MEAN IS OVER EVERY MEMBER: the control (the "oper" stream) and
    # the fifty perturbations (the "enfo" stream) together.  The
    # accumulation is over BOTH streams - the control is one member out of
    # fifty-one, and dropping it would quietly change the product.
    acc = {lev: [] for lev in LEVELS}
    secacc = {lev: {name: [] for name in SECTORS} for lev in LEVELS}
    grid = [None, None, 0, 0]
    for stream, param, scale in (("oper", "z", 1.0),
                                  ("enfo", "gh", g())):
        url = file_url(day, cyc, stream, step, "index")
        r = s.get(url, timeout=180)
        if r.status_code != 200:
            raise RuntimeError("the index %s is not there (HTTP %d)"
                               % (url, r.status_code))
        rows = []
        for line in r.text.splitlines():
            try:
                d = json.loads(line)
            except Exception:                        # noqa: BLE001
                continue
            if d.get("param") != param:
                continue
            try:
                lev = int(d.get("levelist"))
            except Exception:                        # noqa: BLE001
                continue
            if lev not in LEVELS:
                continue
            rows.append((lev, int(d["_offset"]), int(d["_length"])))
        grib = file_url(day, cyc, stream, step, "grib2")
        for lev, off, length in rows:
            rr = s.get(grib, headers={"Range": "bytes=%d-%d"
                                      % (off, off + length - 1)}, timeout=180)
            if rr.status_code not in (200, 206):
                raise RuntimeError("the message %s (%d bytes) came back HTTP %d"
                                   % (grib, length, rr.status_code))
            cap, sec = reduce_message(rr.content, scale, grid)
            acc[lev].append(cap)
            for name in SECTORS:
                secacc[lev][name].append(sec[name])
    for lev in LEVELS:
        if not acc[lev]:
            raise RuntimeError("the step %d h has no %d hPa field"
                               % (step, lev))
        out[lev] = (float(np.mean(acc[lev])),
                    {name: float(np.mean(secacc[lev][name]))
                     for name in SECTORS})
        members = max(members, len(acc[lev]))
    return out, members


# --------------------------------------------------------------------------
def main():
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"steps": {}}
    done = st.setdefault("steps", {})

    day, cycles = newest_run()
    if not day:
        print("   no ECMWF run in the open data")
        return
    print("   the EPS run: %s, the %s cycles" % (day, " and ".join(cycles)),
          flush=True)

    # THE STEPS: one per day of each cycle.  The step that lands on a day
    # at 12Z is the one the house's daily series use.
    tasks = []
    for cyc in cycles:
        for k, step in sorted(day_steps(cyc).items()):
            key = "%s/%s/%d" % (day, cyc, step)
            if done.get(key, {}).get("ok"):
                continue
            tasks.append((cyc, k, step, key))
    print("   %d steps to fetch (%d of them already done)"
          % (len(tasks), sum(1 for c in cycles for k, s2 in day_steps(c).items()
                             if done.get("%s/%s/%d" % (day, c, s2), {}).get("ok"))),
          flush=True)
    if not tasks:
        print("   every step is already fetched")
        return

    results = {}
    # THE STATE IS WRITTEN UNDER A LOCK: the steps are fetched in threads
    # and they all write the same file, and two of them writing it at once
    # would leave a half-written file behind.
    lock = threading.Lock()

    def work(t):
        cyc, k, step, key = t
        print("   the %s cycle, day %d (step %d h) ..." % (cyc, k, step),
              flush=True)
        try:
            vals, members = fetch_step(day, cyc, step)
        except Exception as e:                        # noqa: BLE001
            # A STEP THAT FAILS IS REPORTED, not swallowed: the work is
            # in a thread, and an exception in a thread is held until the
            # results are read - so without this the log would show the
            # step starting and nothing else.
            print("      FAILED: %r" % (e,), flush=True)
            raise
        cap, sec = {}, {}
        for lev in LEVELS:
            cap[lev], sec[lev] = vals[lev]
        # THE VALUES GO INTO THE STATE FILE, not just a "done" mark: a
        # restart must not fetch a step again, and the series is written
        # from the state - so the numbers have to be in it.
        done[key] = {"ok": True, "step": step, "day": k, "cycle": cyc,
                     "members": members,
                     "cap": {str(lev): cap[lev] for lev in LEVELS},
                     "sectors": {name: {str(lev): sec[lev][name]
                                        for lev in LEVELS}
                                 for name in SECTORS}}
        with lock:
            with open(STATE + ".tmp", "w") as f:
                json.dump(st, f, indent=1)
            os.replace(STATE + ".tmp", STATE)
        print("      done: %d members" % members, flush=True)
        return key

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for key in ex.map(work, tasks):
            results[key] = True

    # THE SERIES: the days of the run, the pooled mean of the cycles.
    init = datetime.strptime(day, "%Y%m%d").date()

    def series_of(key):
        rec = done.get(key) or {}
        if not rec.get("cap"):
            return None
        cap = [rec["cap"][str(lev)] for lev in LEVELS]
        sec = {name: [rec["sectors"][name][str(lev)] for lev in LEVELS]
               for name in SECTORS}
        return cap, sec, rec.get("members") or 0

    # the day's own name: the day after the run's date, as the EC46's
    # series names it (the init is day 0), and the 12Z hour the house's
    # other daily series use.
    days = {}
    for cyc in cycles:
        for k, step in sorted(day_steps(cyc).items()):
            key = "%s/%s/%d" % (day, cyc, step)
            if not (done.get(key) or {}).get("cap"):
                continue
            t = (init + timedelta(days=k)).strftime("%Y-%m-%d")
            days.setdefault(t, []).append(key)

    if not days:
        print("   no step came back with a usable series")
        return

    out_times = []
    out_values = []
    out_sectors = {name: [] for name in SECTORS}
    members = []
    for day_str in sorted(days):
        rows = [series_of(k) for k in days[day_str]]
        rows = [r for r in rows if r]
        if not rows:
            continue
        out_times.append("%s 12" % day_str)
        out_values.append(list(np.mean([r[0] for r in rows], axis=0)))
        for name in SECTORS:
            out_sectors[name].append(list(np.mean([r[1][name] for r in rows],
                                                   axis=0)))
        members.append(min(r[2] for r in rows))

    if len(out_times) < 3:
        print("   only %d days came back - not enough to draw"
              % len(out_times))
        return
    # A SHORT SERIES DOES NOT REPLACE A COMPLETE ONE.  The new run's pull
    # is still in progress (the open data publishes a step at a time), and
    # a half-pulled run must not put a four-day series where a fifteen-day
    # one was: the file keeps the last complete series until the new one is
    # whole.
    if len(out_times) < DAYS:
        old = (json.load(open(OUT)).get(TAG) or {}) if os.path.exists(OUT) else {}
        if len(old.get("times") or []) >= DAYS:
            print("   the new run has only %d of %d days - the series stays "
                  "as it was (the %s run)"
                  % (len(out_times), DAYS, old.get("run")), flush=True)
            return
        print("   the new run has only %d of %d days - nothing is published"
              % (len(out_times), DAYS), flush=True)
        return

    rec = {"times": out_times, "values": out_values,
           "sectors": out_sectors, "levels": list(LEVELS),
           "run": "%s-%s-%s %s" % (day[0:4], day[4:6], day[6:8],
                                   "+".join("%sZ" % c[:2].upper()
                                            for c in cycles)),
           "cycles": ["%sZ" % c[:2].upper() for c in cycles],
           "frequency": "daily", "members": min(members) if members else 0,
           "source": "ECMWF open data: the control forecast and the fifty "
                     "perturbed members of the %s run" % day}
    series = json.load(open(OUT)) if os.path.exists(OUT) else {}
    series[TAG] = rec
    with open(OUT + ".tmp", "w") as f:
        json.dump(series, f, indent=1)
    os.replace(OUT + ".tmp", OUT)

    # and into the shared cache, under the same key the plotter reads
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            cache = json.load(f)
    cache[TAG] = {"times": rec["times"], "values": rec["values"],
                  "levels": list(LEVELS), "run": rec["run"],
                  "frequency": rec.get("frequency", "daily"),
                  "members": rec.get("members", 0),
                  "cycles": rec.get("cycles")}
    if rec.get("sectors"):
        cache[TAG]["sectors"] = rec["sectors"]
    with open(CACHE + ".tmp", "w") as f:
        json.dump(cache, f)
    os.replace(CACHE + ".tmp", CACHE)

    print("   the EPS series: %s" % OUT, flush=True)
    print("   the run %s, %d days, %s members, the %s cycles"
          % (rec["run"], len(rec["times"]), rec["members"],
             " and ".join(rec["cycles"])), flush=True)


if __name__ == "__main__":
    main()
