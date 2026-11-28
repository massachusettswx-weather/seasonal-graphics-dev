"""ECMWF EPS - the medium-range ensemble, read from ECMWF's own open data.

THE EPS IS THE 15-DAY ENSEMBLE: ECMWF's operational ensemble prediction
system - the control forecast plus fifty perturbed members - at BOTH cycles
of the run, 00Z and 12Z.  This script pulls it and reduces it to the same
two series the polar-cap sections are drawn from: the area-weighted polar
cap (60-90N) mean and the North Pacific and North Atlantic sector means, at
the ten pressure levels the section is drawn on.

    python3 fetch_polar_eps.py                # both cycles of the newest run
    python3 fetch_polar_eps.py --cycle 00z    # the 00Z cycle on its own
    python3 fetch_polar_eps.py --cycle 12z    # the 12Z cycle on its own

The OWNER'S WINDOWS (27 November 2026): the 00Z cycle is published between
07:00 and 08:30 UTC and the 12Z cycle between 19:00 and 20:30 UTC, each
on its own.  A cycle is therefore published on its own, and the chart says
which cycle it is showing.

THE MODEL'S OWN ANALYSIS FILLS THE SEAM.  NOAA's CORe reanalysis runs two
days behind the day it is fetched for, so the reanalysis half of the
section stops two days short of the forecast and the chart would carry a
white band where the two halves meet.  The 0-hour step of the open data is
ECMWF's own ANALYSIS (checked: it agrees with the CORe's polar-cap mean at
10 hPa to about 23 m, the same order as the difference between the two
centres), so the run's analysis - and, if the reanalysis is further
behind, the day before's - is used to close the gap.  The chart then says
which days are reanalysis and which are the model's analysis.

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
import argparse
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
# the reanalysis the section is measured with, and the last day it holds -
# the model's own analysis is used for the days after it
CORE_RECENT = os.path.join(DATA, "polar_core_recent.npz")


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


class MissingStep(Exception):
    """The store has the index of a step but not the data behind it yet."""


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


def cycle_complete(day, cyc):
    """-> True when the cycle is fully published.

    BOTH the index and the data are checked, for every step the cycle
    needs.  The open data publishes a run's index before its data - the
    index is a couple of megabytes, the data is gigabytes - so a cycle
    can be named and still have nothing behind it, which is how the
    2026-11-27 12Z cycle was picked on the evening of the 27th and turned
    out to have only some of its steps.
    """
    steps = sorted(set(list(day_steps(cyc).values())) | {0})
    for step in steps:
        for stream in ("oper", "enfo"):
            if not head_ok(file_url(day, cyc, stream, step, "index")):
                return False
            if not head_ok(file_url(day, cyc, stream, step, "grib2")):
                return False
    return True


def cycle_present(day, cyc):
    """-> True when the cycle has begun to be published.

    The open data puts a cycle up a step at a time - the first step about
    7.7 hours after the init, the last one about 8.5 hours after it - so
    a cycle that has its first step is one the pull can work on while the
    rest arrives.
    """
    for step in (24, 0):
        for stream in ("oper", "enfo"):
            if not head_ok(file_url(day, cyc, stream, step, "index")):
                return False
            if not head_ok(file_url(day, cyc, stream, step, "grib2")):
                return False
    return True


def newest_run(want, complete=False):
    """The newest run the open data has, and the cycles it has.

    `want` is "00z", "12z" or "both".  The run date is the newest whose
    wanted cycles are there.  When the day's 12Z cycle is not out yet, the
    day before is used - it is the newest run that has what is asked for.

    `complete` asks for the cycles to be WHOLE (every step published),
    not merely begun; the publisher uses that to decide whether there is
    anything new to draw.
    """
    wanted = CYCLES if want == "both" else (want,)
    today = datetime.now(timezone.utc).date()
    for back in range(0, LOOKBACK_DAYS):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        cycles = []
        for cyc in wanted:
            ok = (cycle_complete(d, cyc) if complete
                  else cycle_present(d, cyc))
            if ok:
                cycles.append(cyc)
        if len(cycles) == len(wanted):
            return d, cycles
        if back == 0:
            print("   the newest run %s has only the %s cycle(s) of the %s "
                  "wanted - the day before is used"
                  % (d, " and ".join(cycles) or "none", " and ".join(wanted)),
                  flush=True)
    return None, []


def core_last_day():
    """The last day the reanalysis file holds, or "" when there is none."""
    if not os.path.exists(CORE_RECENT):
        return ""
    try:
        d = np.load(CORE_RECENT, allow_pickle=True)
        times = [str(t) for t in d["times"]]
    except Exception:                                # noqa: BLE001
        return ""
    return times[-1][:10] if times else ""


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
        if r.status_code == 404:
            raise MissingStep("the index of the %s %s step %d h is not "
                              "there yet" % (day, cyc, step))
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
            if rr.status_code == 404:
                raise MissingStep("the data of the %s %s step %d h is not "
                                  "there yet (%s)"
                                  % (day, cyc, step, grib))
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


def fetch_analysis(day, cyc):
    """ECMWF's own ANALYSIS of one run -> (the cap mean per level, the
    sector means).

    It is the 0-hour step of the "oper" stream: the state the run started
    from, which is the ECMWF's analysis of that hour.  It is used for the
    days the reanalysis does not reach - NOAA's CORe runs about two days
    behind the day it is fetched for, so without this the section would
    carry a white band where the reanalysis ends and the forecast begins.

    Only the control is read: at 0 hours every member of the ensemble is
    the same analysis, so the ensemble mean of it is the analysis.
    """
    s = session()
    step = 0
    url = file_url(day, cyc, "oper", step, "index")
    r = s.get(url, timeout=180)
    if r.status_code == 404:
        raise MissingStep("the index of the %s %s analysis is not there yet"
                          % (day, cyc))
    if r.status_code != 200:
        raise RuntimeError("the index %s is not there (HTTP %d)"
                           % (url, r.status_code))
    rows = []
    for line in r.text.splitlines():
        try:
            d = json.loads(line)
        except Exception:                            # noqa: BLE001
            continue
        if d.get("param") != "z":
            continue
        try:
            lev = int(d.get("levelist"))
        except Exception:                            # noqa: BLE001
            continue
        if lev in LEVELS:
            rows.append((lev, int(d["_offset"]), int(d["_length"])))
    grib = file_url(day, cyc, "oper", step, "grib2")
    out = {}
    grid = [None, None, 0, 0]
    for lev, off, length in rows:
        rr = s.get(grib, headers={"Range": "bytes=%d-%d"
                                  % (off, off + length - 1)}, timeout=180)
        if rr.status_code == 404:
            raise MissingStep("the %s %s analysis is not there yet"
                              % (day, cyc))
        if rr.status_code not in (200, 206):
            raise RuntimeError("the message %s (%d bytes) came back HTTP %d"
                               % (grib, length, rr.status_code))
        cap, sec = reduce_message(rr.content, 1.0, grid)
        out[lev] = (float(cap), {name: float(sec[name]) for name in SECTORS})
    missing = [l for l in LEVELS if l not in out]
    if missing:
        raise RuntimeError("the %s %s analysis has no %s hPa field"
                           % (day, cyc, missing[0]))
    return out


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="the ECMWF EPS for the polar cap")
    ap.add_argument("--cycle", default="both", choices=("00z", "12z", "both"),
                    help="which cycle of the run to publish")
    ap.add_argument("--wait-minutes", type=int, default=0,
                    help="how long to wait for the steps the open data has "
                         "not put up yet")
    args = ap.parse_args()

    st = json.load(open(STATE)) if os.path.exists(STATE) else {"steps": {}}
    done = st.setdefault("steps", {})

    day, cycles = newest_run(args.cycle)
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
        except MissingStep as e:
            # A STEP THE OPEN DATA HAS NOT PUT UP YET IS NOT A FAILURE:
            # the run is published a file at a time, and the step comes
            # with the next run of the fetcher.  The series keeps the last
            # whole one until the new one is whole.
            print("      not there yet: %s" % e, flush=True)
            # THE MARK IS PUT UNDER THE LOCK, with the write.  The lock
            # keeps two threads from writing the file at once, but the
            # DUMP walks the steps dict - and a mark put in by another
            # thread WHILE this one is dumping made the dump die with
            # "dictionary changed size during iteration" (28 November
            # 2026, the 12Z cycle: the mark and the write have to be one
            # piece of work).
            with lock:
                done[key] = {"ok": False, "step": step, "day": k, "cycle": cyc,
                             "missing": str(e)}
                with open(STATE + ".tmp", "w") as f:
                    json.dump(st, f, indent=1)
                os.replace(STATE + ".tmp", STATE)
            return key
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
        # THE MARK AND THE WRITE ARE UNDER THE LOCK TOGETHER: the dump
        # walks the steps dict, and a mark put in by another thread while
        # this one was dumping killed it with "dictionary changed size
        # during iteration" (28 November 2026, the 12Z cycle).
        with lock:
            done[key] = {"ok": True, "step": step, "day": k, "cycle": cyc,
                         "members": members,
                         "cap": {str(lev): cap[lev] for lev in LEVELS},
                         "sectors": {name: {str(lev): sec[lev][name]
                                            for lev in LEVELS}
                                     for name in SECTORS}}
            with open(STATE + ".tmp", "w") as f:
                json.dump(st, f, indent=1)
            os.replace(STATE + ".tmp", STATE)
        print("      done: %d members" % members, flush=True)
        return key

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for key in ex.map(work, tasks):
            results[key] = True

    # THE WAIT.  ECMWF publishes the open data a step at a time: measured
    # from the objects' own timestamps, a cycle's first step lands about
    # 7.7 hours after its init and its LAST step - the 360-hour one, the
    # end of the fifteen-day product - about 8.5 hours after it.  The
    # owner's windows open before that (the 12Z window at 19:00, the data
    # whole at about 20:30), so the pull waits for the steps that are not
    # there yet and fetches them when they arrive.  The series is written
    # only when the cycle is whole.
    if args.wait_minutes:
        left = [t for t in tasks
                if not (done.get(t[3]) or {}).get("ok")]
        waited = 0
        while left and waited < args.wait_minutes:
            nap = min(5, args.wait_minutes - waited)
            print("   %d steps are not there yet - waiting %d min for them"
                  % (len(left), nap), flush=True)
            time.sleep(nap * 60)
            waited += nap
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                list(ex.map(work, left))
            left = [t for t in left
                    if not (done.get(t[3]) or {}).get("ok")]

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

    # A DAY IS A DAY OF THE "BOTH CYCLES" SERIES ONLY WHEN BOTH CYCLES
    # ARE IN IT.  The chart says the two suites are pooled, and a day that
    # carries only one of them is not pooled - and the open data publishes
    # a run a file at a time, so the 12Z cycle of the newest run can be
    # half up for a while.  The days that are not whole are left out, and
    # the guard below keeps the last whole series until the new one is
    # whole.
    #
    # A SINGLE CYCLE IS PUBLISHED ON ITS OWN - the owner gave the 00Z and
    # the 12Z cycle a window each - so a cycle on its own carries its own
    # days, and the chart says which cycle it is showing.
    if len(cycles) > 1:
        days = {d: keys for d, keys in days.items()
                if len(keys) == len(cycles)}
        if not days:
            print("   no day has both cycles yet - the series stays as it "
                  "was")
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

    # THE MODEL'S OWN ANALYSIS, for the days the reanalysis does not
    # reach.  NOAA's CORe runs about two days behind the day it is fetched
    # for, so the reanalysis half of the section would stop short of the
    # forecast and the chart would carry a white band where the two meet.
    # The 0-hour step of the open data is ECMWF's own analysis of that
    # hour (it agrees with the CORe's polar-cap mean at 10 hPa to about
    # 23 m, the same order as the difference between the two centres), so
    # it closes the seam.
    ana_times, ana_values, ana_sectors = [], [], {n: [] for n in SECTORS}
    ana_by_day = {}
    # THE SHARED CACHE OF THE ECMWF'S OWN ANALYSIS.  Every model's chart
    # closes its seam with it, so the EPS's own pull - which runs every
    # day - is what keeps it fed.  (The import is here and not at the top
    # because that module borrows this one's http machinery.)
    import fetch_polar_analysis as FA
    shared = FA.load()
    core_last = core_last_day()
    fc_first = out_times[0][:10] if out_times else ""
    if fc_first:
        # the run's own analysis, and the day before's, in case the
        # reanalysis is further behind than it usually is
        wanted = []
        for cyc in cycles:
            hour = int(cyc[:2])
            for back in (0, 1):
                d = (init - timedelta(days=back)).strftime("%Y%m%d")
                key = "%s/%s/analysis" % (d, cyc)
                if (done.get(key) or {}).get("ok"):
                    wanted.append((key, (init - timedelta(days=back)),
                                   "%02d" % hour, cyc))
                    continue
                try:
                    vals = fetch_analysis(d, cyc)
                except MissingStep:
                    continue
                except Exception as e:                # noqa: BLE001
                    print("      the %s %s analysis FAILED: %r"
                          % (d, cyc, e), flush=True)
                    continue
                with lock:
                    done[key] = {"ok": True, "cycle": cyc, "analysis": True,
                                 "cap": {str(lev): vals[lev][0]
                                         for lev in LEVELS},
                                 "sectors": {name: {str(lev): vals[lev][1][name]
                                                    for lev in LEVELS}
                                             for name in SECTORS}}
                    with open(STATE + ".tmp", "w") as f:
                        json.dump(st, f, indent=1)
                    os.replace(STATE + ".tmp", STATE)
                wanted.append((key, (init - timedelta(days=back)),
                               "%02d" % hour, cyc))
        for key, when, hour, cyc in sorted(wanted, key=lambda w: w[1]):
            rec_a = done.get(key) or {}
            if not rec_a.get("cap"):
                continue
            t = when.strftime("%Y-%m-%d")
            # THE SHARED CACHE OF THE ECMWF'S OWN ANALYSIS.  The open data
            # keeps about four days of it, so the analysis of a day has to
            # be captured the day it is there - and the EPS runs every day,
            # so the EPS's own pull is what keeps the cache fed.  The
            # seasonal's analysis day is the first of its month, and that
            # is twenty-five days before the seasonal is published, so the
            # cache has to have kept it.
            try:
                FA.put_values(shared, t.replace("-", ""), cyc, LEVELS,
                              rec_a["cap"], rec_a["sectors"])
            except Exception as e:                        # noqa: BLE001
                print("      the shared analysis cache FAILED: %r" % (e,),
                      flush=True)
            # only the days that are between the reanalysis and the
            # forecast: the rest the reanalysis already covers
            if core_last and t <= core_last:
                continue
            if t >= fc_first:
                continue
            # ONE ANALYSIS A DAY: when both cycles are in the series their
            # analyses fall on the same calendar day - the 00Z cycle's at
            # 00Z and the 12Z cycle's at 12Z - and the 12Z one is kept,
            # because the reanalysis is measured at 12Z.
            if t in ana_by_day and ana_by_day[t][1] >= hour:
                continue
            ana_by_day[t] = (rec_a, hour)
        for t in sorted(ana_by_day):
            rec_a, hour = ana_by_day[t]
            ana_times.append("%s-01 %s" % (t, hour))
            ana_values.append([rec_a["cap"][str(lev)] for lev in LEVELS])
            for name in SECTORS:
                ana_sectors[name].append([rec_a["sectors"][name][str(lev)]
                                          for lev in LEVELS])
        if ana_times:
            print("   the model's own analysis fills %s to %s"
                  % (ana_times[0][:10], ana_times[-1][:10]), flush=True)
        FA.save(shared)

    run_txt = " ".join("%s %sZ" % (day, c[:2].upper()) for c in cycles)
    rec = {"times": out_times, "values": out_values,
           "sectors": out_sectors, "levels": list(LEVELS),
           "run": run_txt,
           "cycles": ["%sZ" % c[:2].upper() for c in cycles],
           "product": "medium-range",
           "frequency": "daily", "members": min(members) if members else 0,
           "source": "ECMWF open data: the control forecast and the fifty "
                     "perturbed members of the %s run" % run_txt}
    if ana_times:
        rec["analysis_times"] = ana_times
        rec["analysis_values"] = ana_values
        rec["analysis_sectors"] = ana_sectors
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
                  "cycles": rec.get("cycles"),
                  "product": rec.get("product")}
    if rec.get("sectors"):
        cache[TAG]["sectors"] = rec["sectors"]
    if rec.get("analysis_times"):
        cache[TAG]["analysis_times"] = rec["analysis_times"]
        cache[TAG]["analysis_values"] = rec["analysis_values"]
        cache[TAG]["analysis_sectors"] = rec["analysis_sectors"]
    with open(CACHE + ".tmp", "w") as f:
        json.dump(cache, f)
    os.replace(CACHE + ".tmp", CACHE)

    print("   the EPS series: %s" % OUT, flush=True)
    print("   the run %s, %d days, %s members, the %s cycles"
          % (rec["run"], len(rec["times"]), rec["members"],
             " and ".join(rec["cycles"])), flush=True)


if __name__ == "__main__":
    main()
