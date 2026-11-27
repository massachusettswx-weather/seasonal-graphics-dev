"""EC46 (the ECMWF sub-seasonal ensemble) polar-cap geopotential height.

The seasonal route in `fetch_polar_models.py` uses the C3S sub-daily archive,
which has no sub-seasonal system in it.  For the sub-seasonal guidance the
same quantity - the area weighted (cos(lat)) mean geopotential height over
60-90N - has to come out of ECMWF's own store: the ECDS service, dataset
`s2s-forecasts`, system 46 (the 46-day ensemble).

    POST https://ecds.ecmwf.int/api/retrieve/v1/processes/s2s-forecasts/execute
    headers: PRIVATE-TOKEN: <the CDS key in .cdsapirc>
    {
      "inputs": {
        "origin": "ecmwf", "system": 46,
        "year": "2026", "month": "11", "day": "13", "time": "00:00",
        "level_type": "pressure", "variable": ["geopotential_height"],
        "level_value": ["10_hpa", ...],
        "forecast_type": ["control_forecast", "perturbed_forecast"],
        "leadtime_hour": ["24_48", "72_96", ..., "456_480"],
        "area": [90, -180, 60, 180], "data_format": "grib"
      },
      "outputs": {"asset": {"value": {"type": "file"}}}
    }

Two things about the catalogue, both measured from the live form schema
(GET /retrieve/v1/processes/s2s-forecasts):

  * `level_value` holds TEN pressure levels - 10, 50, 100, 200, 300, 500,
    700, 850, 925, 1000 hPa.  There is no 30 hPa and no 400 hPa, so an EC46
    section carries ten levels rather than the reference's twelve.
  * `leadtime_hour` takes 359 values, 98 of them ranges; the weekly ranges
    24_48 ... 456_480 are the ones the sub-seasonal windows are built from.

**The licence.**  The account has not accepted the S2S licence, so every
request is refused with

    HTTP 403 {"title": "required licences not accepted",
              "detail": "Not all the required licences have been accepted;
                         please visit https://ecds.ecmwf.int/datasets/
                         s2s-forecasts?tab=download#manage-licences ..."}

The check runs before the request is validated, so a 403 always means the
licence, never a malformed request.

**The licence CAN be accepted by the API** (found in the R package
CopernicusClimate, R/licenses.R):

    GET  {store}/api/profiles/v1/account/licences          what is accepted
    GET  {store}/api/catalogue/v1/vocabularies/licences    the catalogue
    PUT  {store}/api/profiles/v1/account/licences/<id>      accept one
         body: {"revision": N}                              (answers 201)

The S2S licence is `s2s-licence`, revision 5.  The same key works on the CDS
and on the ECDS; only the store's base URL differs.

Until the licence is accepted this script reports the refusal and writes
NOTHING: a chart must never be published without real data behind it.
"""
import datetime
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import G0, SECTORS, sector_mean, zonal_mean  # noqa: E402

ECDS = "https://ecds.ecmwf.int/api"
EXEC = "%s/retrieve/v1/processes/s2s-forecasts/execute" % ECDS
OUT = os.path.join(DATA, "polar_ec46_z.json")
STATE = os.path.join(DATA, "polar_ec46_jobs.json")
# the shared cache the plotter reads; the series is merged into it under its
# own key, and every other model's record is left exactly as it was found
CACHE = os.path.join(DATA, "polar_model_z.json")
TAG = "ec46"

# the levels the S2S catalogue serves (ten of the reference's twelve: the
# catalogue has no 30 hPa and no 400 hPa)
LEVELS = [10, 50, 100, 200, 300, 500, 700, 850, 925, 1000]
AREA = [90.0, -180.0, 60.0, 180.0]

# The catalogue has no `system` parameter: the product is picked by the RUN
# DATE, so the 46-day extended range is what the archive serves on the days
# it runs (Mondays and Thursdays, 00Z) and the 15-day ensemble on the others.
# The lead times are 24-hour blocks, so the series that comes back is a daily
# one.
SYSTEM = 46

# The lead time ranges, 24_48 up to 1080_1104: FORTY-SIX days, which is the
# whole of the extended range - the chart runs to the end of the run, not to
# some shorter window of it.  (The window 1080_1104 is the LAST one: the
# window 1104_1128 would be day 47, which the run does not have.)
WEEKLY = ["%d_%d" % (h, h + 24) for h in range(24, 1081, 24)]

# The extended range runs on MONDAYS and THURSDAYS at 00Z, and only those runs
# carry the 46 days: on the other days the archive serves the 15-day
# ensemble, which stops at lead 360 h.  The catalogue has no `system`
# parameter - the product is picked by the RUN DATE - so the run is found by
# asking for a lead window that only an extended-range run has.
EXTENDED_ONLY = ["1080_1104"]

# WHERE THE SEARCH FOR THE NEWEST RUN STARTS.  The archive holds the run
# about two days late, so the search used to start at today-48h and walk
# back from there.  That was too late: measured 27 Nov 2026, the
# 2026-11-26 run was in the store at 03:15 UTC on the 27th - about 27
# hours after its date - and the search never looked at it, so the EC46
# on the site stayed a run behind (the owner's word, 26 Nov 2026: "why
# don't I see the newly updated EC46 from today").
#
# The search now starts at TODAY and walks back until the store answers.
# The request it makes carries BOTH the first week and the far end of the
# 46-day window, so a run that is only half in the archive is refused and
# the search moves on to the day before it - a run that is served whole is
# a run that is there.
DELAY_HOURS = 0

LICENCE_URL = ("https://ecds.ecmwf.int/datasets/s2s-forecasts"
               "?tab=download#manage-licences")

# the S2S dataset's licence, and the revision of it that is current
S2S_LICENCE = "s2s-licence"
S2S_REVISION = 5


# ------------------------------------------------------------------ licences
def accepted_licences(s):
    """-> the licences the account has accepted."""
    r = s.get("%s/profiles/v1/account/licences" % ECDS, timeout=60)
    if r.status_code != 200:
        return []
    try:
        d = r.json()
    except Exception:
        return []
    if isinstance(d, dict):
        d = d.get("results") or d.get("licences") or []
    return d or []


def accept_licence(s, licence_id, revision):
    """Accept one licence.  -> True when the store took it."""
    r = s.put("%s/profiles/v1/account/licences/%s" % (ECDS, licence_id),
              json={"revision": revision}, timeout=60)
    # the Data Store answers 201 Created for a new acceptance
    return r.status_code in (200, 201, 204)


def ensure_licence(s):
    """Accept the S2S licence if the account has not taken it yet.

    The tick in the web UI is a PUT against the account's licence list, and
    the same key works here, so the EC46 does not have to wait for a manual
    click.
    """
    have = accepted_licences(s)
    ids = []
    for x in have:
        if isinstance(x, dict):
            ids.append(str(x.get("id") or x.get("licence") or ""))
        else:
            ids.append(str(x))
    if S2S_LICENCE in ids:
        print("   the licence %s is already accepted" % S2S_LICENCE,
              flush=True)
        return True
    print("   the licence %s is not accepted - accepting it now" % S2S_LICENCE,
          flush=True)
    ok = accept_licence(s, S2S_LICENCE, S2S_REVISION)
    print("   the licence %s: %s" % (S2S_LICENCE,
                                      "accepted" if ok else "REFUSED"),
          flush=True)
    return ok


def key():
    """-> the CDS/ECDS key, from .cdsapirc (mode 600, never in the repo)."""
    p = os.path.join(HERE, ".cdsapirc")
    if not os.path.exists(p):
        raise SystemExit(
            "   there is no .cdsapirc here, so there is no key to ask the\n"
            "   store with.  Put it in place with:\n"
            "       ./set_cds_key.sh <your CDS API key>\n"
            "   (the same key works on the CDS and on the ECDS, where the\n"
            "    EC46 comes from.)")
    with open(p) as f:
        for l in f:
            if l.strip().startswith("key:"):
                return l.split(":", 1)[1].strip()
    raise SystemExit("   the .cdsapirc here has no key: line")


def session():
    import requests
    s = requests.Session()
    s.headers.update({"PRIVATE-TOKEN": key(), "Content-Type": "application/json"})
    return s


def save_state(st):
    """Write the job state, so a restart can ADOPT what is in the store."""
    with open(STATE + ".tmp", "w") as f:
        json.dump(st, f, indent=1)
    os.replace(STATE + ".tmp", STATE)


def live_jobs(s):
    """-> the jobs the account has in the store, the live ones first."""
    try:
        r = s.get("%s/retrieve/v1/jobs?limit=20" % ECDS, timeout=60)
        if r.status_code != 200:
            return []
        jobs = r.json().get("jobs") or []
    except Exception:                                # noqa: BLE001
        return []
    live = [j for j in jobs if j.get("status") in
            ("accepted", "queued", "running", "executing")]
    return live


# The account may hold this many jobs in the store at once.
MAX_LIVE_JOBS = 2

# How many times one chunk is asked for again when the store fails the
# job.  On 15 Nov 2026 the store failed a job that had been queued for
# more than nine hours, and the chunk was lost with it.
# The store REJECTS a job now and then (measured 22 Nov 2026: six in a row
# for the same request, and the very same request successful minutes
# later), so the chunk is asked for again - with a pause, because the
# store's patience is not the fetcher's to spend.
RETRIES = 8
RETRY_PAUSE = 30


def wait_for_queue(s, room, tries=180):
    """Wait until the account's queue has room for `room` MORE jobs.

    The store refuses a request when the account already has too many jobs
    waiting, and the refusal comes back as a job that is REJECTED.  A
    dismissal does not free the slot at once, so the queue is watched rather
    than assumed.

    The jobs the account already holds INCLUDE the ones this run has
    submitted and is waiting for, so the room that is wanted is the number
    of jobs to ADD: the account's limit is a total, and a job of ours that
    is already queued counts towards it exactly like any other.
    """
    for _ in range(tries):
        live = live_jobs(s)
        if len(live) + room <= MAX_LIVE_JOBS:
            return True
        print("   the queue holds %d job(s); waiting for room for %d more"
              % (len(live), room), flush=True)
        time.sleep(20)
    return False


def latest_run(s, tries=8):
    """The most recent ECMWF sub-seasonal run the archive holds.

    The S2S archive holds the run with about a TWO-DAY delay - but not
    always: the 2026-11-26 run was already there on the 27th (measured
    27 Nov 2026, 03:15 UTC).  So the search starts at TODAY and walks
    back until the store answers, and the run it finds is the newest one
    the archive has - not the newest one the delay allows.

    The catalogue has no `system` parameter: the product is picked by the
    RUN DATE.  The probe asks for a lead window at the far end of the
    extended range (1080_1104 = day 46) together with the first one, so a
    run that carries the whole 46 days is recognised as such; a run that
    refuses it is still used, with a word about it, because the run itself
    is the one that is there.

    The probe is a job of its own, and it is dismissed at once so it does
    not sit in the queue.
    """
    today = date.today() - timedelta(hours=DELAY_HOURS)
    for back in range(0, tries + 1):
        d = today - timedelta(days=back)
        for t in ("00:00", "12:00"):
            for windows, extended in ((list(EXTENDED_ONLY) + ["24_48"], True),
                                      (["24_48"], False)):
                req = {"origin": "ecmwf",
                       "year": "%04d" % d.year, "month": "%02d" % d.month,
                       "day": "%02d" % d.day, "time": t,
                       "level_type": "pressure",
                       "variable": ["geopotential_height"],
                       "level_value": ["%d_hpa" % l for l in LEVELS],
                       "forecast_type": ["control_forecast"],
                       "leadtime_hour": list(windows), "area": AREA,
                       "data_format": "grib"}
                r = s.post(EXEC, json={"inputs": req}, timeout=180)
                # the Data Store answers 201 Created for a new job, not 200
                if r.status_code in (200, 201):
                    try:
                        j = r.json()
                        jid = j.get("jobID") or j.get("processID")
                        if jid:
                            s.delete("%s/retrieve/v1/jobs/%s" % (ECDS, jid),
                                     timeout=30)
                            # the dismissal is NOT immediate: until the store
                            # has actually released the job, the probe is still
                            # holding one of the account's two queue slots and
                            # every real request is turned away with
                            # "rejected".  So the queue is watched until the
                            # probe is out of it.
                            wait_for_queue(s, 1)
                    except Exception:                # noqa: BLE001
                        pass
                    if not extended:
                        print("   the run %s %s does not serve the far end of "
                              "the extended range" % (d, t), flush=True)
                    print("   the EC46 run: %s %s" % (d, t), flush=True)
                    return d, t, None
                if r.status_code == 403:
                    raise SystemExit(licence_refusal(r))
                if r.status_code == 400:
                    break            # this run cannot serve those windows
    return None, None, None


def licence_refusal(r):
    return ("the S2S licence has not been accepted yet.  The data is free "
            "(CC BY 4.0) - the account only has to accept the terms once:\n"
            "  %s\n"
            "  the answer was HTTP %d: %s\n"
            "  nothing was written; the series needs real data behind it."
            % (LICENCE_URL, r.status_code, r.text[:200]))


def read_grib(path):
    """-> ({valid_time: {level: polar cap mean}}, {valid_time: {sector: {...}}},
             {valid_time: the members behind it}).

    The sector means are the same reduction over one longitude sector, so
    the Atlantic and the Pacific can be drawn separately.

    The GRIB carries the geopotential HEIGHT in metres ("gh"), not the
    geopotential in m2/s2 ("z"), so every value is multiplied by 9.80665
    here - the same thing fetch_polar_gefs.py does with the GEFS's HGT.

    The file carries every member at the same valid time and level, so the
    member values are AVERAGED: the section shows the ensemble mean.  (A
    reader that kept the last message it saw would draw ONE member and call
    it the ensemble.)

    The member set is the one that is present at EVERY time of the run, not
    the one that happens to be in each chunk: the archive caps the RESPONSE
    SIZE, so a chunk can come back with fewer members than were asked for,
    and a mean whose membership changes half way through the chart would
    draw a step that is an artefact of the archive and not of the atmosphere.
    """
    import eccodes
    from collections import defaultdict
    # acc[time][level][member] = the polar cap mean
    acc = defaultdict(lambda: defaultdict(dict))
    sacc = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:                         # noqa: BLE001
                break
            if gid is None:
                break
            try:
                la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                ni = int(eccodes.codes_get(gid, "Ni", 0) or 0)
                nj = int(eccodes.codes_get(gid, "Nj", 0) or 0)
                if ni and nj and v.size == ni * nj:
                    lat2d = la.reshape(nj, ni)
                    v = v.reshape(nj, ni)
                else:
                    lats = np.unique(la)[::-1]
                    lons = np.unique(lo)
                    if v.size != lats.size * lons.size:
                        continue
                    v = v.reshape(len(lats), len(lons))
                    lat2d = np.repeat(lats[:, None], len(lons), axis=1)
                lats = lat2d[:, 0]
                lon2d = lo.reshape(nj, ni) if (ni and nj
                                               and v.size == ni * nj) else \
                    np.repeat(np.unique(lo)[None, :], len(lats), axis=0)
                # the VALIDITY time, not the data time: the S2S fields are
                # initialised at 00Z or 12Z and carry the lead time as the
                # step, so validityDate/validityTime is the only pair that
                # gives the right calendar day
                vd = int(eccodes.codes_get(gid, "validityDate"))
                vt = int(eccodes.codes_get(gid, "validityTime"))
                valid = date(vd // 10000, (vd // 100) % 100, vd % 100) \
                    + timedelta(hours=vt // 100, minutes=vt % 100)
                lev = int(eccodes.codes_get(gid, "level"))
                key = valid.strftime("%Y-%m-%d %H")
                # the member number: the control is 0 and the perturbations
                # are 1, 2, 3 ...
                try:
                    mem = int(eccodes.codes_get(gid, "number") or 0)
                except Exception:                     # noqa: BLE001
                    mem = 0
                cap = zonal_mean(v, lats) * G0
                acc[key][lev][mem] = cap
                for name, (a, b) in SECTORS.items():
                    sacc[key][name][lev][mem] = \
                        sector_mean(v, lats, lon2d[0, :], a, b) * G0
            except Exception:                         # noqa: BLE001
                pass
            finally:
                eccodes.codes_release(gid)

    # the members that are present at EVERY time of the file
    common = None
    for t, d in acc.items():
        for lev, mm in d.items():
            s = set(mm)
            common = s if common is None else (common & s)
    common = common or set()

    out = {}
    sout = {}
    for t, d in acc.items():
        row = {}
        for lev, mm in d.items():
            vals = [mm[m] for m in common if m in mm]
            if vals:
                row[lev] = float(np.mean(vals))
        out[t] = row
    for t, sd in sacc.items():
        row = {}
        for name, ld in sd.items():
            srow = {}
            for lev, mm in ld.items():
                vals = [mm[m] for m in common if m in mm]
                if vals:
                    srow[lev] = float(np.mean(vals))
            row[name] = srow
        sout[t] = row
    # the members behind each time
    nmem = {t: len(common) for t in acc}
    return out, sout, nmem


def submit(s, run_date, run_time, weeks):
    """-> the job id of the request for these weekly windows.

    The catalogue's form schema names the 46-day system explicitly, so the
    request carries `system: 46`; if this build of the schema does not know
    the field the same request goes out without it.
    """
    base = {"origin": "ecmwf",
            "year": "%04d" % run_date.year, "month": "%02d" % run_date.month,
            "day": "%02d" % run_date.day, "time": run_time,
            "level_type": "pressure",
            "variable": ["geopotential_height"],
            "level_value": ["%d_hpa" % l for l in LEVELS],
            "forecast_type": ["control_forecast", "perturbed_forecast"],
            "leadtime_hour": weeks,
            "area": AREA, "data_format": "grib"}

    def post(req):
        return s.post(EXEC, json={"inputs": req,
                                  "outputs": {"asset": {"value": {"type": "file"}}}},
                      timeout=300)

    # THE CATALOGUE HAS NO `system` FIELD (measured 22 Nov 2026).  A request
    # that carries one is ACCEPTED by the endpoint (HTTP 201) and then
    # FAILS in the job - the 46-day system is picked by the RUN DATE, and
    # the store will not serve the long leads of a run that does not have
    # them.  The same request without the field comes back "successful".
    r = post(base)
    if r.status_code == 403:
        raise SystemExit(licence_refusal(r))
    if r.status_code >= 400:
        raise RuntimeError("submit failed HTTP %d: %s"
                           % (r.status_code, r.text[:300]))
    j = r.json()
    return j.get("jobID") or j.get("processID")


def wait(s, jid, tries=14400, stall_limit=14400):
    """-> True when the job finishes.

    The queue is congested and a job can sit 'accepted' for a long time.
    A job that has not even STARTED after a while is not slow, it is
    stuck, so the caller is told and the chunk is asked for again at a
    size the archive has already answered at.

    The stall limit is generous on purpose: the store's queue can sit on a
    job for HOURS (one was still 'accepted' after two and a half hours, and
    two more were still untouched after thirty minutes while the store
    processed NOTHING for the account), and a limit of a couple of minutes
    threw that job away and asked for it again, which only made the queue
    longer - a dismissal puts the request at the BACK of the queue.

    So a job that has not started is waited out rather than dismissed: the
    store's congestion is not the job's fault, and the account's own limit
    is small enough that a job sitting there IS the account's slot.

    15 Nov 2026: the stall limit is 14400 checks (60 hours at 15 s).  The
    store processed NOTHING for this account for more than twelve hours -
    two jobs sat 'accepted' from 08:01Z and 09:34Z - and a six-hour limit
    would have dismissed a job that had already waited nearly eight hours
    and put the request at the BACK of the queue.
    """
    started = False
    slow = 0
    for _ in range(tries):
        time.sleep(15)
        r = s.get("%s/retrieve/v1/jobs/%s" % (ECDS, jid), timeout=60)
        if r.status_code != 200:
            continue
        st = r.json().get("status")
        if st in ("successful", "completed"):
            return "done"
        if st in ("failed", "error", "rejected", "dismissed"):
            # The STORE failed the job.  On 15 Nov 2026 it failed the
            # chunk-0 job that had been queued since 08:01Z, after more
            # than nine hours, and then deleted it.  That is the store's
            # answer to the request, not a reason to skip the chunk: the
            # chunk is asked for again.
            print("   the job is %s" % st, flush=True)
            return "failed"
        if st in ("running", "executing"):
            started = True
            slow = 0
            continue
        # still 'accepted' or 'queued': it has not started
        if started:
            continue
        slow += 1
        if slow >= stall_limit:
            print("   the job %s has not started after %d checks" %
                  (jid, slow), flush=True)
            return "timeout"
    return "timeout"


def download(s, jid, path):
    r = s.get("%s/retrieve/v1/jobs/%s/results" % (ECDS, jid), timeout=120)
    link = r.json()["asset"]["value"]["href"]
    with s.get(link, stream=True, timeout=600) as dr:
        with open(path + ".part", "wb") as f:
            for chunk in dr.iter_content(4 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    os.replace(path + ".part", path)


def newest_run(s):
    """-> the run the store has, as a date, or None.

    THE EXTENDED RANGE IS DAILY (measured 22 Nov 2026: every run from 10 to
    21 November served the 46-day window, the Saturdays and the Sundays
    included).  The run is therefore found by PROBING for the lead window at
    the far end of the extended range - one small job - and not from a
    calendar.
    """
    d, t = latest_run(s)
    if d is None:
        return None
    return d


def main():
    if "--run-for-today" in sys.argv:
        # the run the store has, found by probing for the 46-day window
        d, t = latest_run(session())
        print(d.isoformat() if d else "")
        return
    s = session()
    # the licence first: a request that is refused for want of it says
    # nothing about the data, and the acceptance is an API call
    if not ensure_licence(s):
        print("   the S2S licence has not been accepted, so nothing can be "
              "asked of the archive.")
        print("   it is one tick in the web UI: %s" % LICENCE_URL)
        return
    # The run probe is itself a job, and the account's queue is small: every
    # slot the probe takes is a slot the real chunks cannot use.  So the run
    # can be given on the command line when it is known, and the probe is
    # skipped.
    forced = None
    if "--run" in sys.argv:
        forced = sys.argv[sys.argv.index("--run") + 1]
    if forced:
        run_date = date(int(forced[0:4]), int(forced[5:7]), int(forced[8:10]))
        run_time = forced[11:16] + ":00"
        print("   the S4S run: %s %s (given)" % (run_date, run_time), flush=True)
    else:
        run_date, run_time, _ = latest_run(s)
        if run_date is None:
            print("   no ECMWF S4S run found in the last week")
            return
        print("   the S4S run: %s %s" % (run_date, run_time), flush=True)

    st = json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": []}
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}

    # A RUN WE ALREADY HAVE IS NOT FETCHED AGAIN.  The weekly schedule
    # asks on three days and the store answers with the same run on two of
    # them; a second request for it would take one of the account's two
    # queue slots away from the seasonal requests (the December rollover
    # wants them).  A field that is already on disk is not re-queued.
    have = (out.get(TAG) or {}).get("run")
    want = "%s %sZ" % (run_date, run_time[:2])
    if have == want and not forced:
        print("   the %s run is already on disk - nothing is asked of the "
              "archive" % want)
        return

    # The weekly windows in chunks: the archive caps the RESPONSE SIZE, and
    # a chunk that carries fewer members than the model has is a broken
    # answer.  The chunk size can be set on the command line: one big request
    # for the whole range costs ONE turn of the queue and gives every day the
    # SAME member set, which is what a section wants (a mean whose membership
    # changes half way through is an artefact of the archive, not of the
    # atmosphere).
    #
    # FIVE days is the size the archive has answered at (51.8 MB for 101
    # members): a ten-day request is twice that and the queue will not move
    # it.  The chunks are asked for PARALLEL, two at a time, because the
    # account may hold two queued jobs and one job on its own leaves the
    # other slot empty for the whole run.
    CHUNK = 5
    if "--chunk-size" in sys.argv:
        CHUNK = int(sys.argv[sys.argv.index("--chunk-size") + 1])
    # ONE CHUNK AT A TIME (22 Nov 2026).  The account may hold two jobs and
    # the store's admission is stricter than its own listing: a job that has
    # just been dismissed still counts for a while, so a second submission
    # is refused while the first is still counted.  Two at a time therefore
    # ends in a rejection - and a rejected chunk that is asked for again
    # takes more room than the one it was holding.
    PARALLEL = 1
    if "--parallel" in sys.argv:
        PARALLEL = int(sys.argv[sys.argv.index("--parallel") + 1])

    # A chunk that is already in the store is ADOPTED, not asked for again.
    # The store's queue can sit on a job for hours, and a second request
    # for the same chunk only makes the queue longer (and takes the account's
    # room away from the chunk that is already there).
    adopted = {}
    for j in live_jobs(s):
        jid = j.get("jobID")
        for rec in st["jobs"]:
            if rec.get("job") == jid:
                adopted[rec.get("chunk")] = jid
    if adopted:
        print("   adopting %d job(s) already in the store: %s"
              % (len(adopted), ", ".join("chunk %d (job %s)"
                                        % (c, adopted[c][:8])
                                        for c in sorted(adopted))), flush=True)

    want_run = "%s %sZ" % (run_date, run_time[:2])
    pending = []
    for i in range(0, len(WEEKLY), CHUNK):
        weeks = WEEKLY[i:i + CHUNK]
        # A CHUNK THAT IS DECODED IS ONLY DONE FOR THE RUN IT CAME FROM.
        # The state used to record the chunk and nothing else, so the run
        # after the run after this one found every chunk "already decoded"
        # and fetched nothing at all.
        done = [j for j in st["jobs"]
                if j.get("chunk") == i and j.get("status") == "decoded"
                and j.get("run") == want_run]
        if done:
            continue
        pending.append((i, weeks))
    print("   %d chunks of %d days, %d at a time"
          % (len(pending), CHUNK, PARALLEL), flush=True)

    def run_chunk(i, weeks):
        """One chunk, end to end.  -> (chunk, job, the decoded values)."""
        print("   the weeks %s ..." % (weeks[0] + " to " + weeks[-1]), flush=True)
        jid = adopted.get(i)
        last = jid
        for attempt in range(1, RETRIES + 1):
            if jid:
                print("   the job %s (adopted from the store)" % jid, flush=True)
            else:
                # the room is made first: the store refuses a request when
                # the account already holds too many jobs
                wait_for_queue(s, 1)
                jid = submit(s, run_date, run_time, weeks)
                print("   the job %s" % jid, flush=True)
                # The job is recorded AT ONCE, not when the chunk is
                # finished.  A job that is live in the store but not in the
                # state file cannot be adopted after a restart, and the
                # chunk would be asked for a second time.
                st["jobs"].append({"chunk": i, "job": jid, "run": want_run,
                                   "status": "submitted"})
                save_state(st)
            last = jid
            what = wait(s, jid)
            if what == "done":
                break
            # a job that will not start is dismissed, so it does not sit in
            # the queue holding a slot for the rest of the run
            try:
                s.delete("%s/retrieve/v1/jobs/%s" % (ECDS, jid), timeout=30)
                print("   the job %s dismissed" % jid, flush=True)
            except Exception:                        # noqa: BLE001
                pass
            jid = None
            if attempt < RETRIES:
                print("   the chunk is asked for again (attempt %d of %d)"
                      % (attempt + 1, RETRIES), flush=True)
                # a dismissal is not free at once: the store still counts
                # the job for a while, and the next attempt is refused
                # while it is counted
                wait_for_queue(s, 1)
                time.sleep(RETRY_PAUSE)
        else:
            return i, last, None
        path = os.path.join(DATA, "_ec46_%d.grib" % i)
        download(s, jid, path)
        vals, svals, nmem = read_grib(path)
        os.remove(path)
        return i, jid, (vals, svals, nmem)

    results = []
    for k in range(0, len(pending), PARALLEL):
        batch = pending[k:k + PARALLEL]
        # The store turns a request away when the account already has too
        # many jobs waiting, so the room is made first.  The jobs that were
        # ADOPTED are ours and are already counted by the store, so the
        # room wanted is only what is left over - otherwise the fetcher
        # waits for room to wait for the job it already has, and never
        # gets to it.
        nnew = sum(1 for i, _ in batch if i not in adopted)
        wait_for_queue(s, nnew)
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            for res in ex.map(lambda a: run_chunk(*a), batch):
                results.append(res)

    for i, jid, got in results:
        if got is None:
            st["jobs"].append({"chunk": i, "job": jid, "run": want_run,
                               "status": "failed"})
            save_state(st)
            continue
        vals, svals, nmem = got
        # A NEW RUN REPLACES THE SERIES; it does not join it.  The record
        # used to be appended to whatever was there, so the second run
        # after this one left 90 days in the file - the old run's days and
        # the new one's, indistinguishable.
        run_name = "%s %sZ" % (run_date, run_time[:2])
        rec = out.get(TAG)
        if not isinstance(rec, dict) or rec.get("run") != run_name:
            rec = {"times": [], "values": [], "sectors": {},
                   "levels": list(LEVELS)}
            out[TAG] = rec
        # only the times that carry every level of BOTH the cap and the two
        # sectors are kept, so the times and the sector rows stay in step
        # (a sector row that was short would put the two out of line and
        # the chart would draw the wrong sector against the wrong day)
        keep = []
        for t in sorted(vals):
            row = [vals[t].get(l) for l in LEVELS]
            if any(x is None for x in row):
                continue
            srows = {}
            bad = False
            for name in SECTORS:
                sd = svals.get(t, {}).get(name, {})
                srow = [sd.get(l) for l in LEVELS]
                if any(x is None for x in srow):
                    bad = True
                    break
                srows[name] = srow
            if bad:
                continue
            keep.append((t, row, srows, nmem.get(t, 0)))
        for t, row, srows, nm in keep:
            rec["times"].append(t)
            rec["values"].append(row)
            for name, srow in srows.items():
                rec.setdefault("sectors", {}).setdefault(name, []).append(srow)
        rec["run"] = run_name
        # the ECMWF's sub-seasonal set is a DAILY run with a 48-hour delay:
        # the chart says so, because a reader comparing it with a 35-day
        # GEFS needs to know it
        rec["frequency"] = "daily"
        # the members behind the series: the FEWEST that came back for any of
        # the days, so the number on the chart is the number behind every day
        if keep:
            nm_all = [nm for _t, _r, _s, nm in keep]
            rec["members"] = min(nm_all)
            print("   the chunk carries %d members over %d days"
                  % (rec["members"], len(keep)), flush=True)
        with open(OUT + ".tmp", "w") as f:
            json.dump(out, f, indent=1)
        os.replace(OUT + ".tmp", OUT)
        # and into the shared cache, under the same key the plotter reads
        cache = {}
        if os.path.exists(CACHE):
            with open(CACHE) as f:
                cache = json.load(f)
        cache[TAG] = {"times": rec["times"], "values": rec["values"],
                      "levels": list(LEVELS), "run": rec["run"],
                      "frequency": rec.get("frequency", "daily"),
                      "members": rec.get("members", 0)}
        if rec.get("sectors"):
            cache[TAG]["sectors"] = rec["sectors"]
        with open(CACHE + ".tmp", "w") as f:
            json.dump(cache, f)
        os.replace(CACHE + ".tmp", CACHE)
        st["jobs"].append({"chunk": i, "job": jid, "status": "decoded"})
        save_state(st)
        print("   the chunk decoded: %d times so far" % len(rec["times"]),
              flush=True)

    print("   the EC46 series: %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
