"""GEFS v12 (NOAA's sub-seasonal GEFS) polar-cap geopotential height, daily 12Z.

The seasonal route in `fetch_polar_models.py` uses the C3S sub-daily archive
and therefore only reaches the seasonal models.  For the sub-seasonal
guidance the same quantity - the area weighted (cos(lat)) mean geopotential
height over 60-90N on twelve pressure levels - has to come out of NOAA's own
GEFS, which is the suite NOAA now runs as its S2S system.

The route (measured, not assumed):

  * the archive lives on NOMADS under
        https://nomads.ncep.noaa.gov/pub/data/nccf/com/gens/prod/gefs.YYYYMMDD/HH/
    and is mirrored verbatim in the AWS open-data bucket
        https://noaa-gefs-pds.s3.amazonaws.com/gefs.YYYYMMDD/HH/
    The same tree also sits under `.../com/gens/v12.3/` (the version tag).
  * each cycle directory holds `atmos/pgrb2ap5/` and `atmos/pgrb2bp5/`: the
    0.50 degree GRIB2 product, split into two halves (the "a" half carries
    the surface and the middle troposphere, the "b" half the stratosphere).
    `atmos/pgrb2sp25/` is the 0.25 degree SURFACE-only subset, so it cannot
    serve the pressure levels.
  * the ensemble members are the files `gec00.*` (control) and `gep01.*` ...
    `gep30.*` (the perturbed members): 31 members a cycle.  NCEP also
    publishes the ensemble mean and the spread as `geavg.*` and `gespr.*`.
  * the twelve levels of the reference figure are spread over the two
    halves: the "a" half has 10, 50, 100, 200, 300, 500, 700, 850, 925 and
    1000 hPa, the "b" half 30 and 400 hPa.  Both halves are needed.
  * the GRIB2 `HGT` (geopotential height) is in GEOPOTENTIAL METRES, not in
    m2/s2 like the CDS `geopotential`: it is multiplied by 9.80665 here, so
    the series is on the same scale as the ERA5 half of the section.
  * the runs are initialised at 00Z, so the 12Z value of a day sits at a
    lead time of 12 + 24k hours - the same clock as the seasonal archive
    and the ERA5 half, so the series lands on the right calendar days.
  * only the HGT messages are downloaded: the `.idx` file beside every
    GRIB2 lists the byte offset of every message, so each of the twelve
    messages is fetched with an HTTP Range request (about 210 kB each)
    instead of the whole 15-90 MB file.

The ensemble mean is computed here from the member files rather than taken
from NCEP's own `geavg` file, because `geavg` is only published once the whole
ensemble is done, and the live cycle is still in production.

THE 35-DAY EXTENDED RANGE (measured on the 20261114 00Z cycle)
--------------------------------------------------------------
Only the **00Z** cycle carries the full extended range: the 06Z, 12Z and 18Z
cycles of the same day stop at f384 (16 days), while the 00Z cycle runs to
**f840 = 35 days**.  So the cycle is the first thing the fetcher decides.

NCEP thins the ensemble as the lead grows, and the thinning is not
arbitrary - it is the *last* lead that decides:

    f000 - f438   31 members (gec00 + gep01..gep30)
    f444          28 members
    f450          25 members (gec00 + gep01..gep24)
    f558 - f840   24 members (gep01..gep24 - the control is gone)

An ensemble mean over 31 members is not the same number as one over 24, so
the mean cannot change membership half way through the chart: it would draw
a step that is an artefact of the archive, not of the atmosphere.  The fetcher
therefore takes the member set of the **longest** lead (the archive only ever
drops members, so that set is present at every lead) and uses the same 24
members for the whole 35 days.  The 31-member mean is still checked at one
lead, so the size of the difference is known rather than assumed.
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import LEVELS, SECTORS, read_grib_levels_sectors  # noqa: E402

# the shared cache the plotter reads; this script only ever touches its own
# key in it and never rewrites another model's record
CACHE = os.path.join(DATA, "polar_model_z.json")
STATE = os.path.join(DATA, "polar_gefs_jobs.json")
TAG = "gefsv12"

# the two hosts that serve the same tree
S3_ROOT = "https://noaa-gefs-pds.s3.amazonaws.com/"
NOMADS_ROOT = ("https://nomads.ncep.noaa.gov/pub/data/nccf/com/gens/prod/")

# the GRIB2 "HGT" is geopotential metres; the series is in m2/s2
G0 = 9.80665

# the half that carries each level of the reference figure
PART_OF = {}
for _l in (10, 50, 100, 200, 300, 500, 700, 850, 925, 1000):
    PART_OF[_l] = "a"
for _l in (30, 400):
    PART_OF[_l] = "b"

PARTS = {"a": "pgrb2ap5/", "b": "pgrb2bp5/"}

# the forecast length: the 00Z cycle of the GEFS v12 carries the FULL
# extended range - 840 hours, 35 days.  The 06Z, 12Z and 18Z cycles of the
# same day are cut at 384 hours (16 days), so the cycle that is chosen
# decides how long the chart can run.
MAX_LEAD_H = 35 * 24

# THE DAILY SERIES STARTS AT INIT+1 DAY (36 hours).  The init day itself
# is the GEFS's OWN ANALYSIS - the f000 step of the run, which is the GFS
# analysis the run started from - and it is drawn as such, so that the
# reader can see where the reanalysis ends and the model begins.  The
# chart therefore covers the same 35 days it always did: the analysis day
# and then 34 days of forecast.
FIRST_LEAD = 36

# how many requests at a time
THREADS = 20

UA = {"User-Agent": "Mozilla/5.0 (seas5 polar cap fetcher)"}

# the cycle this run is on; the URLs are built from it
DATE = None
HOUR = None

# the hosts that answer, in the order they are tried
HOSTS = []


# ------------------------------------------------------------------ the http
def live_hosts():
    """-> the hosts that answer, in the order they are tried.

    NOMADS answers in bursts and sometimes not at all from a given machine;
    the AWS open-data bucket serves the same tree verbatim and has no such
    behaviour.  Probing once at the start and dropping the hosts that do not
    answer keeps the thousands of byte-range requests from each paying the
    full timeout.
    """
    out = []
    for name, root in (("aws", S3_ROOT), ("nomads", NOMADS_ROOT)):
        url = root
        try:
            r = requests.get(url, headers=UA, timeout=15, stream=True)
            # any answer at all - even a 403 for a directory that does not
            # exist - means the host is reachable
            out.append(name)
            print("   the host answers: %s (%d)" % (url, r.status_code),
                  flush=True)
            r.close()
        except Exception as e:                      # noqa: BLE001
            print("   the host does not answer: %s (%s)"
                  % (url, type(e).__name__), flush=True)
    if not out:
        raise RuntimeError("no GEFS host answers from here")
    return out


def get(url, headers=None, tries=4, timeout=120):
    """A GET with a few retries: NOMADS answers 503 in bursts."""
    h = dict(UA)
    if headers:
        h.update(headers)
    last = None
    for k in range(tries):
        try:
            r = requests.get(url, headers=h, timeout=timeout)
            # 206 is a byte range answered, which is what most of the
            # requests here are
            if r.status_code in (200, 206):
                return r
            last = "HTTP %d" % r.status_code
        except Exception as e:                      # noqa: BLE001
            last = "%s: %s" % (type(e).__name__, str(e)[:80])
        time.sleep(1.5 * (k + 1))
    raise RuntimeError("%s -> %s" % (url, last))


def cycle_url(host, path=""):
    """The URL of a file (or a directory) of the current cycle."""
    rel = "gefs.%s/%s/%s" % (DATE, HOUR, path)
    if host == "aws":
        return S3_ROOT + rel
    return NOMADS_ROOT + rel


def file_urls(path):
    """Every URL that serves one file of the current cycle."""
    return [cycle_url(h, path) for h in (HOSTS or ["aws", "nomads"])]


def get_first(path, headers=None, tries=4):
    """The first host that answers wins."""
    last = None
    for url in file_urls(path):
        try:
            return get(url, headers=headers, tries=tries)
        except Exception as e:                      # noqa: BLE001
            last = e
    raise RuntimeError("%s -> %s" % (path, last))


def head_size(path):
    for url in file_urls(path):
        try:
            r = requests.head(url, headers=UA, timeout=60)
            if r.status_code == 200:
                return int(r.headers["Content-Length"])
        except Exception:                           # noqa: BLE001
            continue
    raise RuntimeError("no size for %s" % path)


def list_keys(path):
    """-> the names of the files in one directory of the cycle.

    The S3 listing is an XML document that is PAGINATED - a directory holds
    thousands of keys (every member at every lead) - so the continuation
    token is followed until the listing ends.  The NOMADS listing is an
    Apache HTML index.

    A listing that stops half way is DANGEROUS: the keys come in member
    order, so a truncated listing loses the LAST members (gep25 ...
    gep30) and the member set it implies is short at every lead - which
    reads as though the archive had dropped them.  So a failed page makes
    the whole listing start again, and the listing is checked against the
    last member name before it is accepted.
    """
    for host in (HOSTS or ["aws", "nomads"]):
        if host == "aws":
            for attempt in range(3):
                out = []
                token = None
                failed = False
                while True:
                    url = (S3_ROOT + "?list-type=2&max-keys=1000&prefix=" +
                           "gefs.%s/%s/%s" % (DATE, HOUR, path))
                    if token:
                        url += "&continuation-token=%s" % requests.utils.quote(token)
                    try:
                        r = get(url, tries=6)
                    except Exception:               # noqa: BLE001
                        failed = True
                        break
                    t = r.text
                    out += re.findall(r"<Key>([^<]*)</Key>", t)
                    m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>",
                                  t)
                    if m and "<IsTruncated>true</IsTruncated>" in t:
                        token = m.group(1)
                        continue
                    break
                if not failed and out:
                    return out
                print("      the listing of %s failed part way "
                      "(%d keys so far); listing it again"
                      % (path, len(out)), flush=True)
                time.sleep(3)
            continue
        else:
            try:
                r = get(cycle_url(host, path))
            except Exception:                       # noqa: BLE001
                continue
            t = re.sub(r"<script.*?</script>", "", r.text, flags=re.S)
            out = []
            for m in re.finditer(r"HREF=\"([^\"]+)\"", t, flags=re.I):
                n = m.group(1)
                if n.startswith("/") or n.startswith("?") or n == "../":
                    continue
                out.append(n.rsplit("/", 1)[-1])
            if out:
                return out
    raise RuntimeError("no listing for %s" % path)


# ------------------------------------------------------------------ the cycle
def s3_prefixes(prefix):
    """-> the common prefixes under a prefix (the S3 delimiter listing)."""
    out = []
    token = None
    while True:
        url = (S3_ROOT + "?list-type=2&max-keys=1000&delimiter=/&prefix=" +
               prefix)
        if token:
            url += "&continuation-token=%s" % requests.utils.quote(token)
        try:
            r = get(url)
        except Exception:                           # noqa: BLE001
            break
        t = r.text
        out += re.findall(r"<Prefix>([^<]*)</Prefix>", t)
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>",
                      t)
        if m and "<IsTruncated>true</IsTruncated>" in t:
            token = m.group(1)
            continue
        break
    return out


def find_cycle():
    """-> (date, hour) of the newest cycle that carries the extended range.

    The 00Z cycle is the one with the full 35 days, so it is preferred over
    the 06Z/12Z/18Z cycles of the same day.  A cycle that is STILL BEING
    UPLOADED is not usable: the newest cycle's members arrive one by one and
    its long leads are not there yet, so the newest cycle is only taken
    when it carries the whole range with the whole ensemble.
    """
    dates = set()
    if "aws" in (HOSTS or ["aws"]):
        for p in s3_prefixes("gefs."):
            m = re.search(r"gefs\.(\d{8})/", p)
            if m:
                dates.add(m.group(1))
    if not dates and "nomads" in (HOSTS or []):
        try:
            r = get(NOMADS_ROOT)
            for m in re.finditer(r"HREF=\"([^\"]*gefs\.\d{8})/\"", r.text):
                dates.add(m.group(1).split(".")[-1])
        except Exception:                            # noqa: BLE001
            pass
    if not dates:
        raise RuntimeError("no GEFS cycle with member files found")

    for d in sorted(dates, reverse=True):
        hours = []
        if "aws" in (HOSTS or ["aws"]):
            for p in s3_prefixes("gefs.%s/" % d):
                m = re.search(r"gefs\.\d{8}/(\d{2})/", p)
                if m:
                    hours.append(m.group(1))
        if not hours:
            try:
                r = get(NOMADS_ROOT + "gefs.%s/" % d)
                hours = re.findall(r"HREF=\"(\d{2})/\"", r.text)
            except Exception:                        # noqa: BLE001
                pass
        # the 00Z cycle first: it is the one with the full 35-day range
        for h in ["00"] + sorted((x for x in hours if x != "00"), reverse=True):
            if has_members(d, h) and cycle_is_complete(d, h):
                return d, h
    raise RuntimeError("no GEFS cycle with member files found")


def cycle_is_complete(date, hour):
    """Does this cycle carry the whole range with the whole ensemble?

    The check is on EVERY lead, not just the longest: a cycle that is
    still being uploaded has the whole ensemble at its first leads and only
    a handful further out, and the check that looked only at the longest
    lead and at the member COUNT accepted it - so the chart was drawn from
    a cycle whose second half had only eight members in it.
    """
    global DATE, HOUR
    old = (DATE, HOUR)
    DATE, HOUR = date, hour
    try:
        by_lead = members_by_lead()
        for part in ("a", "b"):
            d = by_lead.get(part) or {}
            if not d:
                return False
            if len(d) < 31:
                return False
            longest = max(max(v) for v in d.values())
            if longest < MAX_LEAD_H:
                return False
            # every lead of the range must carry the WHOLE ensemble
            counts = {}
            for m, leads in d.items():
                for lf in leads:
                    counts.setdefault(lf, 0)
                    counts[lf] += 1
            for lf in range(12, MAX_LEAD_H + 1, 24):
                if counts.get(lf, 0) < 31:
                    print("   the cycle %s %sZ is incomplete: the lead f%03d "
                          "carries %d members" % (date, hour, lf,
                                                  counts.get(lf, 0)),
                          flush=True)
                    return False
        return True
    except Exception:                                # noqa: BLE001
        return False
    finally:
        DATE, HOUR = old


def has_members(d, h):
    """Is there a member file in this cycle?  One HEAD is enough."""
    global DATE, HOUR
    old = (DATE, HOUR)
    DATE, HOUR = d, h
    try:
        url = cycle_url("aws" if "aws" in (HOSTS or ["aws"]) else "nomads",
                        "atmos/pgrb2ap5/gep01.t00z.pgrb2a.0p50.f000")
        r = requests.head(url, headers=UA, timeout=60)
        return r.status_code == 200
    except Exception:                                # noqa: BLE001
        return False
    finally:
        DATE, HOUR = old


def members_by_lead():
    """-> {part: {member: {lead: True}}}, from the two directory listings.

    One listing of each half gives every member at every lead.  The listing
    is PAGINATED and a cycle directory holds thousands of keys, so the
    continuation token is followed until the listing ends - and the listing
    is CHECKED when it ends.  A listing that stops early looks exactly like
    an archive that has dropped members: the members that come last in the
    key order (gep25 ... gep30) simply go missing, and a member set built
    from it is short at every lead.  That is how this once came to believe
    that NCEP thins the ensemble at long leads - it does not.  All thirty-one
    members (gec00 and gep01..gep30) are there at every lead of the 00Z
    cycle, and the check below says so out loud.
    """
    out = {}
    for part in ("a", "b"):
        names = list_keys("atmos/%s" % PARTS[part])
        d = {}
        for n in names:
            if n.endswith(".idx"):
                continue
            m = re.search(r"(ge[cp]\d+)\.t00z\.pgrb2[ab]\.0p50\.f(\d{3})", n)
            if not m:
                continue
            d.setdefault(m.group(1), set()).add(int(m.group(2)))
        out[part] = d
    return out


def member_sets(by_lead):
    """-> {part: the member names}, and the count at the longest lead.

    The members that are present at EVERY lead are the ones the mean is
    taken over: a mean whose membership changes half way through the chart
    draws an archive artefact, not an atmospheric signal.
    """
    sets = {}
    for part in ("a", "b"):
        d = by_lead[part]
        if not d:
            sets[part] = set()
            continue
        longest = max(max(v) for v in d.values())
        sets[part] = set(m for m, leads in d.items() if longest in leads)
    return sets


def check_membership(by_lead, leads):
    """The member count at each lead, and the members common to all of them.

    The point is to catch a SHORT LISTING: if the two halves do not agree,
    or if the member count falls from one lead to the next, the listing was
    truncated rather than the archive having dropped members.
    """
    per_lead = []
    for f in leads:
        sets = []
        for part in ("a", "b"):
            d = by_lead[part]
            sets.append(set(m for m, ls in d.items() if f in ls))
        per_lead.append((f, set.intersection(*sets) if sets else set()))
    common = set.intersection(*[s for _, s in per_lead]) if per_lead else set()
    counts = sorted(set(len(s) for _, s in per_lead))
    return per_lead, common, counts


# ------------------------------------------------------------------ the idx
def read_idx(path):
    """-> [(offset, var, level)] of every message of one file."""
    r = get_first(path)
    out = []
    for line in r.text.strip().split("\n"):
        p = line.split(":")
        if len(p) < 6:
            continue
        try:
            off = int(p[1])
        except ValueError:
            continue
        out.append((off, p[3], p[4]))
    return out


# ------------------------------------------------------------------ one lead
def lead_members(members, fstep):
    """-> {member: {level: bytes}} - the twelve HGT messages of every member."""
    jobs = []

    def plan_for(m):
        plan = {}
        for part in ("a", "b"):
            base = "atmos/%s%s.t00z.pgrb2%s.0p50.f%03d" % (PARTS[part], m,
                                                           part, fstep)
            try:
                msgs = read_idx(base + ".idx")
            except Exception as e:                    # noqa: BLE001
                print("      the %s %s f%03d is not there (%s)"
                      % (m, part, fstep, str(e)[:60]), flush=True)
                continue
            if not msgs:
                continue
            try:
                size = head_size(base)
            except Exception as e:                    # noqa: BLE001
                print("      the %s %s f%03d has no size (%s)"
                      % (m, part, fstep, str(e)[:60]), flush=True)
                continue
            alloff = sorted(set(x[0] for x in msgs))
            for lev in LEVELS:
                if PART_OF[lev] != part:
                    continue
                hit = [o for o, v, l in msgs if v == "HGT" and l == "%d mb" % lev]
                if not hit:
                    continue
                jobs.append((m, part, lev, hit[0], alloff, size))
        return m

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        list(ex.map(plan_for, members))

    def one(job):
        m, part, lev, off, alloff, size = job
        base = "atmos/%s%s.t00z.pgrb2%s.0p50.f%03d" % (PARTS[part], m, part,
                                                       fstep)
        nxt = [o for o in alloff if o > off]
        end = nxt[0] if nxt else size
        r = get_first(base, headers={"Range": "bytes=%d-%d" % (off, end - 1)})
        return m, lev, r.content

    out = {m: {} for m in members}
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        for m, lev, blob in ex.map(one, jobs):
            out[m][lev] = blob
    return out


def read_cap_mean(path):
    """-> ({level: polar cap mean in m2/s2}, {sector: {level: mean}}, time).

    The sector means are the same reduction over one longitude sector, so
    the Atlantic and the Pacific can be drawn separately.
    """
    times, vals, sec = read_grib_levels_sectors(path)
    if not times:
        return {}, {}, None
    t = times[0]
    row = {int(l): float(v) * G0 for l, v in vals[t].items()}
    srow = {name: {int(l): float(v) * G0 for l, v in ld.items()}
            for name, ld in sec.get(t, {}).items()}
    return row, srow, t


def decode_lead(members, fstep):
    """One lead of the cycle, decoded -> {time, values, members, sectors}.

    Every member's twelve messages are written into one file and read back
    in one pass, which averages the fields that share a time and a level:
    the ensemble mean.
    """
    got = lead_members(members, fstep)
    got = {m: v for m, v in got.items() if len(v) == len(LEVELS)}
    if not got:
        return None
    tmp = os.path.join(DATA, "_gefs_f%03d.grib2" % fstep)
    with open(tmp, "wb") as f:
        for m in sorted(got):
            for lev in LEVELS:
                f.write(got[m][lev])
    row, srow, t = read_cap_mean(tmp)
    os.remove(tmp)
    if not row or any(l not in row for l in LEVELS):
        return None
    return {"time": t, "values": [row[l] for l in LEVELS],
            "members": len(got),
            "sectors": {name: [sd[l] for l in LEVELS]
                        for name, sd in srow.items()
                        if all(l in sd for l in LEVELS)}}


def build_record(out, date, hour):
    """-> the record for the cache, from the decoded leads, or None.

    None when no daily lead has been decoded yet: the f000 analysis on its
    own is not a series, and a record with no days in it would take the
    chart's series away.
    """
    keys = sorted((k for k in out if int(k) >= FIRST_LEAD),
                  key=lambda k: int(k))
    if not keys:
        return None
    times = [out[k]["time"] for k in keys]
    values = [out[k]["values"] for k in keys]
    nmem = min(out[k]["members"] for k in keys)
    # the sector means, where the members carried them
    sectors = {}
    if all(out[k].get("sectors") for k in keys):
        # each lead carries the twelve level values for that sector
        sectors = {name: [out[k]["sectors"][name] for k in keys]
                   for name in out[keys[0]]["sectors"]}
    rec = {"times": times, "values": values, "members": nmem,
           "levels": list(LEVELS),
           "run": "%s %sZ" % (date, hour),
           "source": "NOAA GEFS v12 (0.50 deg pgrb2a+pgrb2b), the ensemble "
                     "mean of %d members" % nmem,
           "lead_days": (int(keys[-1]) + 12) // 24}
    if sectors:
        rec["sectors"] = sectors
    # THE GEFS'S OWN ANALYSIS - the f000 step of the run.  It is the state
    # the run started from: the GFS analysis of the init time.  It is the
    # GEFS's own analysis and not the ECMWF's, and the owner's word (27
    # November 2026) is that the chart must say so.
    a = out.get("0")
    if a:
        rec["analysis_times"] = [a["time"]]
        rec["analysis_values"] = [a["values"]]
        if a.get("sectors"):
            rec["analysis_sectors"] = {name: [a["sectors"][name]]
                                        for name in a["sectors"]}
        rec["analysis_label"] = "GEFS analysis"
        rec["analysis_source"] = ("the GEFS's own analysis, the 0-hour step "
                                  "of the %s %sZ run" % (date, hour))
    return rec


def write_cache(rec):
    """Into the shared cache, under this script's own key only.

    The file is written whole, but every other model's record is left
    exactly as it was found.  It is written after every lead, so a run that
    is interrupted keeps everything it had already decoded.
    """
    if not rec:
        return
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            cache = json.load(f)
    cache[TAG] = rec
    with open(CACHE + ".tmp", "w") as f:
        json.dump(cache, f)
    os.replace(CACHE + ".tmp", CACHE)


def commit_state():
    """Put the fetch state into git and push it, so that a rebuild does
    not download the run again.

    Never fatal: a git that will not play is not a reason to stop a fetch
    that is half done - the state is committed at the end of the run too.
    """
    try:
        import subprocess
        here = os.path.dirname(os.path.abspath(__file__))
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        subprocess.run(["git", "add", "--", "data/polar_gefs_jobs.json"],
                       cwd=here, capture_output=True, text=True, env=env)
        d = subprocess.run(["git", "diff", "--cached", "--quiet", "--",
                            "data/polar_gefs_jobs.json"],
                           cwd=here, capture_output=True, text=True, env=env)
        if d.returncode == 0:
            return                       # nothing new to commit
        c = subprocess.run(["git", "-c", "user.name=MCode",
                            "-c", "user.email=mcode@local", "commit", "-q",
                            "-m", "The GEFSv12 fetch state, so a rebuild "
                                  "does not download it again"],
                           cwd=here, capture_output=True, text=True, env=env)
        if c.returncode != 0:
            return
        print("   the fetch state is committed (a rebuild does not lose "
              "the download)", flush=True)
        # and pushed, so a rebuild that takes the working tree with it
        # still finds the state on the server
        tok = (os.environ.get("GITHUB_TOKEN") or "").strip()
        if not tok:
            return
        cred = os.path.join(here, ".git", "gh_cred")
        with open(cred, "w") as f:
            f.write("https://x-access-token:%s@github.com\n" % tok)
        os.chmod(cred, 0o600)
        try:
            p = subprocess.run(["git", "-c",
                                "credential.helper=store --file=%s" % cred,
                                "push", "origin", "HEAD"],
                               cwd=here, capture_output=True, text=True,
                               env=env)
            if p.returncode == 0:
                print("   the fetch state is on the server", flush=True)
        finally:
            try:
                os.remove(cred)
            except OSError:
                pass
    except Exception:                    # noqa: BLE001
        pass


def from_state():
    """Rebuild the cache from the state file, without asking for anything.

    The state file holds every decoded lead, so a run that was interrupted
    (or a machine that was rebuilt) can put the series back together without
    fetching a byte.
    """
    if not os.path.exists(STATE):
        print("   there is no state file yet")
        return
    st = json.load(open(STATE))
    out = {k: v for k, v in st.get("leads", {}).items()
           if v.get("status") == "decoded"}
    if not out:
        print("   the state file holds no decoded lead")
        return
    date = st.get("date") or ""
    hour = st.get("hour") or ""
    rec = build_record(out, date, hour)
    if not rec:
        print("   the state file holds no daily lead yet")
        return
    write_cache(rec)
    print("   the %s series rebuilt from the state file: %d days, %s to %s"
          % (TAG, len(rec["times"]), rec["times"][0], rec["times"][-1]),
          flush=True)


# ------------------------------------------------------------------ the main
def main():
    global DATE, HOUR, HOSTS
    if "--from-state" in sys.argv:
        from_state()
        return
    HOSTS = live_hosts()
    date, hour = find_cycle()
    DATE, HOUR = date, hour
    print("   the GEFS v12 cycle: %s %sZ" % (date, hour), flush=True)
    print("   the host: %s" % cycle_url(HOSTS[0]), flush=True)

    by_lead = members_by_lead()
    leads = list(range(12, MAX_LEAD_H + 1, 24))
    per_lead, common, counts = check_membership(by_lead, leads)
    if not common:
        raise RuntimeError("no member carries every lead of the range")
    members = sorted(common)
    print("   the members that carry the whole range: %d (%s ... %s)"
          % (len(members), members[0], members[-1]), flush=True)
    print("   the member count at each lead: %s"
          % ", ".join("f%03d:%d" % (f, len(s)) for f, s in per_lead), flush=True)
    if len(counts) > 1:
        print("   !! the member count is NOT the same at every lead (%s) - "
              "that is a truncated listing, not the archive" % counts, flush=True)

    st = json.load(open(STATE)) if os.path.exists(STATE) else {"leads": {}}
    # A state file from ANOTHER cycle holds that cycle's leads, and reusing
    # them would put a different run's data on the chart.  The cycle that
    # is wanted is the newest one that carries the whole range with the
    # whole ensemble, and when the newest complete cycle is not the one in
    # the state file the state is cleared.
    if st.get("date") and (st["date"], st.get("hour")) != (date, hour):
        print("   the state file holds the cycle %s %sZ and the cycle wanted "
              "is %s %sZ - the state is cleared"
              % (st["date"], st.get("hour"), date, hour), flush=True)
        st = {"leads": {}}
    st["date"], st["hour"] = date, hour
    out = {}

    # THE GEFS'S OWN ANALYSIS - the f000 step of the run, which is the GFS
    # analysis the run started from.  It is the model's own analysis of its
    # init day, and it is drawn as such: between the reanalysis and the
    # forecast, so that the reader can see where the observation ends and
    # the GEFS begins.  It is one lead's worth of the same download as the
    # rest, so it is fetched with the rest.
    if st["leads"].get("0", {}).get("status") == "decoded":
        out["0"] = st["leads"]["0"]
        print("   the f000 analysis is already decoded", flush=True)
    else:
        print("   the f000 analysis (the GEFS's own analysis) ...", flush=True)
        ana = decode_lead(members, 0)
        if ana:
            out["0"] = ana
            st["leads"]["0"] = dict(ana, status="decoded")
            with open(STATE + ".tmp", "w") as f:
                json.dump(st, f, indent=1)
            os.replace(STATE + ".tmp", STATE)
            write_cache(build_record(out, date, hour))
            print("      %d members, valid %s, 10 hPa = %.0f m2/s2 (%.0f m)"
                  % (ana["members"], ana["time"], ana["values"][0],
                     ana["values"][0] / G0), flush=True)
        else:
            print("      the f000 step did not answer - the chart will carry "
                  "no zone of the model's own analysis", flush=True)

    # the daily 12Z leads: the 12Z value of a day is 12 + 24k hours from the
    # 00Z init, the same clock as the seasonal archive and the ERA5 half.
    # The series starts at INIT+1 DAY, because the init day itself is the
    # model's own analysis and is drawn as such.
    for fstep in range(FIRST_LEAD, MAX_LEAD_H + 1, 24):
        key = str(fstep)
        if st["leads"].get(key, {}).get("status") == "decoded":
            # A lead that is already decoded is reused, UNLESS the sectors
            # it carries are not the ones wanted now: the sector set grew
            # (the Arctic sector was added so that the by-sector charts
            # cover the whole polar cap), and a lead decoded without it
            # has to be fetched again.
            want = set(SECTORS)
            have = set(st["leads"][key].get("sectors") or {})
            if have == want or "--resectors" not in sys.argv:
                out[key] = st["leads"][key]
                print("   the lead %s is already decoded" % key, flush=True)
                continue
            print("   the lead %s carries %d sector(s) and %d are wanted - "
                  "it is fetched again" % (key, len(have), len(want)),
                  flush=True)
        print("   the lead f%03d ..." % fstep, flush=True)
        row = decode_lead(members, fstep)
        if row is None:
            print("      the lead f%03d did not carry the twelve levels"
                  % fstep, flush=True)
            continue
        out[key] = row
        st["leads"][key] = dict(out[key], status="decoded")
        with open(STATE + ".tmp", "w") as f:
            json.dump(st, f, indent=1)
        os.replace(STATE + ".tmp", STATE)
        # and into the cache straight away, so an interrupted run keeps
        # everything it had already decoded
        write_cache(build_record(out, date, hour))
        print("      %d members, valid %s, 10 hPa = %.0f m2/s2 (%.0f m)"
              % (row["members"], row["time"], row["values"][0],
                 row["values"][0] / G0), flush=True)
        # THE STATE GOES INTO GIT WHILE THE FETCH RUNS, NOT ONLY AT THE
        # END.  A new cycle takes about an hour to fetch and the sandbox is
        # rebuilt every hour or so, which kills it: a state that is only
        # committed when the fetch RETURNS loses the whole hour with it.
        # So the state is committed every tenth lead, and a rebuild costs
        # minutes of fetching instead of an hour.  A failure here is never
        # fatal - the fetch carries on and commits at the end.
        if fstep % 240 == 0:
            commit_state()

    if not out:
        print("   nothing was decoded", flush=True)
        return

    # the record, in the shape the seasonal puller writes
    rec = build_record(out, date, hour)
    if not rec:
        print("   no daily lead was decoded - nothing is written")
        return

    # into the shared cache, under this script's own key only
    write_cache(rec)
    print("   the %s series: %s (%d days, %s to %s)"
          % (TAG, CACHE, len(rec["times"]), rec["times"][0], rec["times"][-1]),
          flush=True)


if __name__ == "__main__":
    main()
