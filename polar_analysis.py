"""THE MODEL'S OWN ANALYSIS - the days between the reanalysis and the forecast.

WHY THIS EXISTS (27 November 2026).  Every polar section is drawn in three
parts:

    the reanalysis | the model's OWN analysis | the model's forecast

The reanalysis is NOAA's CORe, and it runs about two days behind the day it
is fetched for.  The forecast is the model's own run, and it starts the day
after the run was initialised.  So the reanalysis stops short of the
forecast: without the model's own analysis the section carries a band of
nothing where the two halves meet, and - worse - the reader cannot tell
where the observation ends and the model's own idea of the atmosphere
begins.

THE MODEL'S OWN ANALYSIS IS THE STATE THE RUN STARTED FROM.

  * for the ECMWF's products it is the 0-hour step of the open data, and it
    is cached day by day in data/polar_model_analysis.json
    (fetch_polar_analysis.py keeps it; the open data only holds about four
    days, so the cache has to be fed every day);
  * for the GEFS it is the f000 step of its own run - the GFS analysis the
    run started from - and it is carried in the record itself.

THE ZONE IS THE DAYS BETWEEN THE REANALYSIS AND THE FORECAST.  The
reanalysis keeps precedence - it is the observation - EXCEPT on the days
the model's own analysis covers: there the model's own analysis is drawn,
so that the label is always on the chart and the reader can see exactly
where the observation ends.

    from polar_analysis import analysis_for, fit_bridge
"""
import json
import os
import re
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
# the day-by-day cache of the ECMWF's own analysis
CACHE = os.path.join(DATA, "polar_model_analysis.json")
# the reanalysis the section is measured with, and the last day it holds
CORE = os.path.join(DATA, "polar_core_recent.npz")

# The name each system's own analysis carries on the chart.  The GEFS's own
# analysis is the GFS analysis its run started from, and the owner asked
# for it to be named as the GEFS's (27 November 2026), because it is the
# GEFS's and not the ECMWF's.
LABELS = {"gefsv12": "GEFS analysis"}
DEFAULT_LABEL = "ECMWF analysis"

# How far back the model's own analysis is looked for.  The run's own
# analysis day is the one that matters; the days before it are wanted
# because the reanalysis is sometimes further behind than it usually is.
LOOKBACK_DAYS = 10


def load_cache():
    """The shared day-by-day cache of the ECMWF's own analysis."""
    if not os.path.exists(CACHE):
        return {}
    try:
        with open(CACHE) as fh:
            d = json.load(fh)
    except Exception:                                    # noqa: BLE001
        return {}
    return d if isinstance(d, dict) else {}


def core_last_day():
    """The last day NOAA's CORe reanalysis holds, or "" when it has none."""
    if not os.path.exists(CORE):
        return ""
    try:
        import numpy as np
        d = np.load(CORE, allow_pickle=True)
        times = [str(t) for t in d["times"]]
    except Exception:                                    # noqa: BLE001
        return ""
    return times[-1][:10] if times else ""


def init_day(rec):
    """The day the run was initialised - the model's own analysis day.

    The run's own name gives it (the EPS's "20261127 12Z", the EC46's
    "2026-11-25 00Z").  The seasonal carries no run name: its init is the
    day before its first value, because the archive's first daily field of
    a run is the day after the run was initialised.
    """
    run = str(rec.get("run") or "")
    m = re.search(r"(\d{4})-?(\d{2})-?(\d{2})", run)
    if m:
        return "%s-%s-%s" % m.groups()
    times = rec.get("times") or []
    if not times:
        return ""
    try:
        d = date.fromisoformat(str(times[0])[:10]) - timedelta(days=1)
    except Exception:                                    # noqa: BLE001
        return ""
    return d.isoformat()


def run_hour(rec):
    """The hour the run was initialised, "" when it is not known."""
    run = str(rec.get("run") or "")
    m = re.search(r"(\d{2})\s*Z", run)
    return m.group(1) if m else ""


def _record_analysis(rec):
    """The analysis the record carries itself -> a dict, or None.

    This is the GEFS's own f000 step, and (for the EPS) the analysis of the
    open data that the EPS's own fetcher put in the record.
    """
    at = [str(x) for x in (rec.get("analysis_times") or [])]
    av = rec.get("analysis_values") or []
    if not at or not av:
        return None
    return {
        "days": [t[:10] for t in at],
        "values": av,
        "sectors": rec.get("analysis_sectors") or {},
        "levels": [int(x) for x in (rec.get("analysis_levels")
                                    or rec.get("levels") or [])],
        "label": str(rec.get("analysis_label") or ""),
        "source": str(rec.get("analysis_source") or ""),
    }


# ------------------------------------------------------------------
# THE DAY BEFORE: THE MODEL'S OWN ANALYSIS OF THE PREVIOUS CYCLE
# ------------------------------------------------------------------
# WHY THIS EXISTS.  The GEFS's own analysis is ONE instant: the state at
# the init, the f000 step.  NOAA's CORe reanalysis runs about three days
# behind, so the day between the reanalysis and the init would be a HOLE in
# the section - and a hole in a section is worse than no analysis at all.
#
# The previous cycle's f000 is the GFS analysis of that day: the same model,
# its own analysis, one day earlier.  So the zone can be two days - the
# previous cycle's analysis and this cycle's - and the section has no hole
# in it, and the label still says "GEFS analysis", which is what it is.
#
# It is read out of the GIT HISTORY, because the record itself only ever
# holds the cycle that is current: the record of the previous cycle is in
# the history of the files that carry it - the fetch state file of the
# GEFS's own fetcher (which is in git, so that a rebuild does not download
# it again) and the record file itself.  Anything that goes wrong here ->
# None -> the section is drawn exactly as it was before.
GIT_RECORD = "data/polar_model_z.json"
GIT_STATE = "data/polar_gefs_jobs.json"
# how many commits of each file are looked at
GIT_LOOKBACK = 8


def _git(*args):
    """git in this tree -> the text, or "" when it does not answer."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", HERE] + list(args),
                           capture_output=True, timeout=60)
    except Exception:                                    # noqa: BLE001
        return ""
    if r.returncode != 0:
        return ""
    return r.stdout.decode("utf-8", "ignore")


def _own_from_state(text, want):
    """The f000 of a cycle, out of a fetch state file -> a dict, or None.

    The state file holds the cycle's date and hour and its decoded leads,
    and the f000 lead is the cycle's own analysis.
    """
    try:
        d = json.loads(text)
    except Exception:                                    # noqa: BLE001
        return None
    if not isinstance(d, dict):
        return None
    f0 = (d.get("leads") or {}).get("0") or {}
    if not f0.get("values") or not f0.get("time"):
        return None
    if str(f0["time"])[:10] != want:
        return None
    run = "%s %sZ" % (d.get("date") or "", d.get("hour") or "")
    return {
        "day": want,
        "values": list(f0["values"]),
        "sectors": {n: list(row) for n, row in (f0.get("sectors") or {}).items()},
        "run": run,
    }


def _own_from_record(text, tag, want):
    """The own analysis of a cycle, out of a record file -> a dict, or None."""
    try:
        d = json.loads(text)
    except Exception:                                    # noqa: BLE001
        return None
    old = (d or {}).get(tag)
    if not isinstance(old, dict):
        return None
    at = [str(x)[:10] for x in (old.get("analysis_times") or [])]
    av = old.get("analysis_values") or []
    if not at or not av or at[0] != want:
        return None
    secs = old.get("analysis_sectors") or {}
    return {
        "day": at[0],
        "values": list(av[0]),
        "sectors": {n: list(row[0]) for n, row in secs.items()},
        "run": str(old.get("run") or ""),
    }


def _previous_own_analysis(rec, tag):
    """The model's own analysis of the day BEFORE the init -> a dict, or None.

    The dict holds one day: the day before the run's own analysis day.
    """
    got = _record_analysis(rec)
    if not got or not got["days"]:
        return None
    try:
        want = (date.fromisoformat(got["days"][0]) - timedelta(days=1)).isoformat()
    except Exception:                                    # noqa: BLE001
        return None
    run = str(rec.get("run") or "")
    for path, reader in ((GIT_RECORD, lambda t: _own_from_record(t, tag, want)),
                          (GIT_STATE, lambda t: _own_from_state(t, want))):
        shas = _git("log", "--format=%H", "--", path).split()
        for sha in shas[:GIT_LOOKBACK]:
            text = _git("show", "%s:%s" % (sha, path))
            if not text:
                continue
            try:
                old = reader(text)
            except Exception:                            # noqa: BLE001
                continue
            if not old:
                continue
            # the same cycle, committed again - it says nothing new
            if old.get("run") and run and old["run"] == run:
                continue
            return old
    return None


def _cached_analysis(rec, init, hour):
    """The ECMWF's own analysis, out of the shared cache -> a dict, or None.

    The cache holds the analysis of a day for the 12Z and the 00Z cycle
    separately.  The cycle the run itself was initialised from is preferred
    - the 00Z run started from the 00Z analysis - and the other one stands
    in when that cycle is not in the cache.
    """
    cache = load_cache()
    if not cache:
        return None
    first = date.fromisoformat(init) - timedelta(days=LOOKBACK_DAYS)
    days, values, sectors = [], [], {}
    levels = []
    for key in sorted(cache):
        try:
            d = date.fromisoformat("%s-%s-%s" % (key[0:4], key[4:6], key[6:8]))
        except Exception:                                # noqa: BLE001
            continue
        if d < first or d > date.fromisoformat(init):
            continue
        entry = cache[key] or {}
        cycles = entry.get("cycles") or {}
        pick = None
        if hour and ("%sz" % hour) in cycles:
            pick = cycles["%sz" % hour]
        elif entry.get("values"):
            pick = entry
        if not pick or not pick.get("values"):
            continue
        lv = [int(x) for x in (pick.get("levels") or [])]
        if not levels:
            levels = lv
        elif lv != levels:
            # a day on another set of levels cannot be put beside these
            # ones: the rows would be read against the wrong levels
            continue
        days.append(d.isoformat())
        values.append(pick["values"])
        for name, row in (pick.get("sectors") or {}).items():
            sectors.setdefault(name, []).append(row)
    if not days:
        return None
    # a sector row that is short would put the sector out of step with the
    # days, so the sectors are only kept when every day carries them
    for name, rows in list(sectors.items()):
        if len(rows) != len(days):
            sectors.pop(name)
    return {"days": days, "values": values, "sectors": sectors,
            "levels": levels, "label": "", "source": ""}


# THE MODELS WHOSE OWN ANALYSIS IS ONE INSTANT.  The GEFS's own analysis
# is the f000 step - a single state - so the day before it has to come
# from the previous cycle's own f000.  The ECMWF's products carry the
# analysis of every day they cover, so they never need it, and they must
# never be given one: their zone is the ECMWF's analysis from end to end.
ONE_INSTANT = ("gefsv12",)


def _merge_own(got, prev):
    """The model's own analysis of the day before, in front of this one.

    The two are put together only when they are CONTIGUOUS days and they
    carry the same values; otherwise the section is drawn with this one
    alone, exactly as it was before.
    """
    if not prev or not prev.get("day") or not got.get("days"):
        return got
    # the two must be CONTIGUOUS: the day before, and this one
    try:
        if (date.fromisoformat(got["days"][0])
                - date.fromisoformat(prev["day"])).days != 1:
            return got
    except Exception:                                    # noqa: BLE001
        return got
    out = {
        "days": [prev["day"]] + list(got["days"]),
        "values": [list(prev["values"])] + list(got["values"]),
        "sectors": {},
        "levels": list(got.get("levels") or []),
        "label": got.get("label") or "",
        "source": got.get("source") or "",
    }
    for name, rows in (got.get("sectors") or {}).items():
        prow = (prev.get("sectors") or {}).get(name)
        if prow is not None and len(rows) == len(got["days"]):
            out["sectors"][name] = [list(prow)] + list(rows)
    if prev.get("run") and got.get("run"):
        out["source"] = ("the model's own analysis, the 0-hour steps of the "
                         "%s and %s runs" % (prev["run"], got["run"]))
    return out


def analysis_for(tag, rec):
    """The model's own analysis -> a dict, or None when there is none.

    The dict holds the days, the polar-cap values, the sector values, the
    levels and the name the analysis carries on the chart.
    """
    got = _record_analysis(rec)
    if got:
        got["label"] = got["label"] or LABELS.get(tag, DEFAULT_LABEL)
        # THE DAY BEFORE, WHEN THE REANALYSIS IS FURTHER BACK THAN THE
        # RUN'S OWN ANALYSIS: the previous cycle's own analysis closes the
        # gap, and it is the same model's own analysis.
        prev = None
        if tag in ONE_INSTANT:
            prev = _previous_own_analysis(rec, tag)
        if prev:
            got = _merge_own(got, prev)
        return got
    init = init_day(rec)
    if not init:
        return None
    got = _cached_analysis(rec, init, run_hour(rec))
    if not got:
        return None
    got["label"] = LABELS.get(tag, DEFAULT_LABEL)
    got["source"] = "the ECMWF's own analysis, the 0-hour step of the open data"
    return got


def fit_bridge(ana, first, ana_days):
    """The model's own analysis that fits between the two halves.

    -> (days, values, sectors, levels, label); empty when there is none.

    Two rules, and both of them are about not leaving a hole:

      * the zone must REACH the forecast - a run of analysis days that
        stops short of it would leave a day with nothing in it, and a hole
        in a section is worse than no analysis at all;
      * the zone must TOUCH the reanalysis - the model's own analysis
        takes the reanalysis's own day over, so the observation ends
        exactly where the model's analysis begins.
    """
    if not ana or not first:
        return [], [], {}, [], ""
    days = ana.get("days") or []
    values = ana.get("values") or []
    if not days or not values:
        return [], [], {}, [], ""
    # the run of the model's analysis days that ends on the day before the
    # forecast begins
    end = date.fromisoformat(first) - timedelta(days=1)
    idx = []
    i = len(days) - 1
    while i >= 0 and days[i] == end.isoformat():
        idx.insert(0, i)
        end -= timedelta(days=1)
        i -= 1
    if not idx:
        return [], [], {}, [], ""
    zone = [days[i] for i in idx]
    if ana_days:
        # THE MODEL'S OWN ANALYSIS TAKES THE REANALYSIS'S LAST DAY OVER,
        # and no day before it: the analysis is the run's own state, and
        # every earlier day is the observation.
        floor = ana_days[-1]
        while zone and zone[0] < floor:
            zone.pop(0)
            idx.pop(0)
        if not zone:
            return [], [], {}, [], ""
        # the zone must not start after the day after the reanalysis's last
        # day, or there would be a day with nothing in it between the two
        gap = (date.fromisoformat(zone[0])
               - date.fromisoformat(ana_days[-1])).days
        if gap > 1:
            return [], [], {}, [], ""
    secs = {}
    for name, rows in (ana.get("sectors") or {}).items():
        if len(rows) != len(days):
            continue
        secs[name] = [rows[i] for i in idx]
    return (zone, [values[i] for i in idx], secs,
            ana.get("levels") or [], ana.get("label") or "")
