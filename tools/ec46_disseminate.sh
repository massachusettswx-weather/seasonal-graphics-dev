#!/usr/bin/env bash
# The EC46's own DISSEMINATION - the owner's 20:00-22:00 UTC window.
#
# ONE job, ONE window, TWO products:
#
#   1. put the trees back (a sandbox rebuild takes the working tree with
#      it; the credentials come back from the environment);
#   2. pull the EPS - ECMWF's medium-range ensemble, both cycles of the
#      run, from ECMWF's open data - and draw and publish it, on the
#      DEVELOPMENT copy only;
#   3. pull the newest EC46 run the store has - Monday, Thursday and
#      Saturday, the owner's days - in the FOREGROUND, so that "the run
#      has arrived" is an answer and not a hope;
#   4. draw the EC46's polar-cap charts from it;
#   5. publish them: the development copy and the operational site;
#   6. and then STOP.
#
# WHY IT IS ITS OWN JOB AND NOT PART OF THE NIGHTLY GEFVSv12 ONE.  The
# owner asked for it on 27 November 2026: the EC46's run is wanted
# between 20:00 and 22:00 UTC, and the GEFSv12's cycle between 03:00
# and 04:00 UTC.  Two windows, two jobs, and nothing runs outside them.
# They never overlap, so there is never a second submitter.
#
#     ./tools/ec46_disseminate.sh
#
# The EC46's fetch resumes from data/polar_ec46_jobs.json and the series
# itself lives in data/polar_ec46_z.json - both are in git, so a rebuild
# does not pull the run again.  The EPS's two files are tracked for the
# same reason.
set -u

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

export HOME="${HOME:-/workspace/.home}"
export PYTHONPATH="${PYTHONPATH:-/workspace/.home/.local/lib/python3.11/site-packages}"

LOG="logs_ec46_disseminate.log"
say() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

DEV=/workspace/devrepo
LIVE=/workspace/repo
DEV_REPO="https://github.com/massachusettswx-weather/seasonal-graphics-dev.git"
LIVE_REPO="https://github.com/massachusettswx-weather/seasonal-graphics.git"

# the owner's days: Monday, Thursday and Saturday.  The test is the
# OWNER'S OWN weekday, because the window is in the afternoon where the
# owner is (20:00 UTC is 16:00 in New York).
EC46_DAYS="${EC46_DAYS:-1 4 6}"
EC46_TZ="${EC46_TZ:-America/New_York}"

# ------------------------------------------------------------------
# 0. the trees
for pair in "$DEV:$DEV_REPO" "$LIVE:$LIVE_REPO"; do
    dir="${pair%%:*}"; url="${pair#*:}"
    if [ ! -d "$dir/.git" ]; then
        say "the tree $dir is not there - cloning it"
        rm -rf "$dir"
        git clone --depth 50 "$url" "$dir" >>"$LOG" 2>&1 || {
            say "   the clone of $dir FAILED"
            exit 2
        }
        git -C "$dir" remote set-url origin "$url"
    fi
done

# ------------------------------------------------------------------
# 1. is today one of the owner's days?
today_u=$(TZ=$EC46_TZ date +%u)
case " $EC46_DAYS " in
    *" $today_u "*)
        say "today is the owner's day $today_u ($EC46_TZ) - the pull runs"
        ;;
    *)
        say "today is day $today_u - not one of the EC46 days ($EC46_DAYS)."
        say "Nothing is fetched and nothing is published."
        exit 0
        ;;
esac

# ------------------------------------------------------------------
# 2. THE EPS - THE SAME WINDOW, AND FIRST.
#
# The EPS is ECMWF's medium-range ensemble: the first fifteen days of the
# run, at BOTH cycles of it, read from ECMWF's OPEN data.  It is first
# because it is the bounded pull - about half an hour, no queue, nothing
# to wait for - while the EC46's pull asks the climate store, whose queue
# is shared with every other user and can hold a job for hours.  So the
# EPS is published in the window whatever the store is doing, and the
# EC46 follows.
#
# The two never overlap: the pulls run one after the other, in the
# foreground, and each product is drawn and published right after its own
# pull - so a pull that hangs cannot hold the other product's publication.
say "the EPS's run"
python3 -u fetch_polar_eps.py >>"logs_fetch_polar_eps.py.log" 2>&1
EPS_FETCH_RC=$?

python3 - <<'PY' >>"$LOG" 2>&1
import json
try:
    d = json.load(open("data/polar_eps_z.json")).get("eps") or {}
    print("   the EPS series: the run %s, %d days, %s members, the %s cycles"
          % (d.get("run"), len(d.get("times") or []), d.get("members"),
             " and ".join(d.get("cycles") or []) or "one"))
except Exception as e:
    print("   the EPS series could not be read: %s" % e)
PY

say "the EPS's charts"
python3 -u plot_polar_cap.py eps "ECMWF EPS" >>"$LOG" 2>&1 || true
python3 -u plot_polar_sectors.py eps "ECMWF EPS" >>"$LOG" 2>&1 || true
mkdir -p docs/assets/polar
for f in polar_cap_eps.png polar_sectors_eps.png; do
    if [ -f "output/polar_cap/$f" ]; then
        cp -f "output/polar_cap/$f" "docs/assets/polar/$f"
    fi
done

# THE EPS GOES TO THE DEVELOPMENT COPY ONLY.  It is a new product and it
# has not been approved for the operational site; its publisher refuses the
# operational clone outright, so there is nothing to guard here.
say "the EPS's publication (the development copy only)"
python3 -u tools/publish_polar_eps.py --repo "$DEV" --apply --push >>"$LOG" 2>&1
EPS_DEV_RC=$?

# ------------------------------------------------------------------
# 3. the EC46's pull, in the foreground
say "the EC46's run"
python3 -u fetch_polar_ec46.py >>"logs_fetch_polar_ec46.py.log" 2>&1
FETCH_RC=$?

# ------------------------------------------------------------------
# 3b. the series: is the run complete?  The narrow path refuses a series
# that is short of its 45 days, so an unfinished pull publishes nothing.
python3 - <<'PY' >>"$LOG" 2>&1
import json
try:
    d = json.load(open("data/polar_ec46_z.json")).get("ec46") or {}
    print("   the series: the run %s, %d days, %s members"
          % (d.get("run"), len(d.get("times") or []), d.get("members")))
except Exception as e:
    print("   the series could not be read: %s" % e)
PY

# ------------------------------------------------------------------
# 4. the charts and the publication - the narrow path, to both copies
say "the charts"
python3 -u plot_polar_cap.py ec46 "ECMWF EC46" >>"$LOG" 2>&1 || true
python3 -u plot_polar_sectors.py ec46 "ECMWF EC46" >>"$LOG" 2>&1 || true
for f in polar_cap_ec46.png polar_sectors_ec46.png; do
    if [ -f "output/polar_cap/$f" ]; then
        cp -f "output/polar_cap/$f" "docs/assets/polar/$f"
    fi
done

say "the publication"
python3 -u tools/publish_polar_ec46.py --repo "$DEV" --apply --push >>"$LOG" 2>&1
DEV_RC=$?
python3 -u tools/publish_polar_ec46.py --repo "$LIVE" --apply --push --prod --approved >>"$LOG" 2>&1
LIVE_RC=$?

# ------------------------------------------------------------------
# 5. one line
say "done: the fetch rc=$FETCH_RC; the development copy rc=$DEV_RC, the"
say "operational site rc=$LIVE_RC (0 = published, 2 = nothing to publish,"
say "3 = the push failed, 4 = the target already carries it)"
say "the EPS: the fetch rc=$EPS_FETCH_RC, the development copy rc=$EPS_DEV_RC"
