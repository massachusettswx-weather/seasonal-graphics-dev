#!/usr/bin/env bash
# The SEASONAL's own DISSEMINATION - the C3S release calendar.
#
# THE OWNER'S WORD (27 November 2026): "we really need to start working on
# getting ready to receive the December seasonals whenever the first
# seasonal comes in to December 10th... we can enact schedules for
# whenever is the nominal dissemination time of seasonal guidance".
#
# THE NOMINAL DISSEMINATION TIMES ARE THE RELEASE CALENDAR.  The C3S
# seasonal archive publishes a new init every month: the ECMWF on the 6th
# and every other centre on the 10th.  A centre is therefore on this
# month's init from its release day and on last month's before it, and
# init_info holds that rule - so this script has no month in it and the
# December rollover is a one-step move.
#
#     ./tools/seasonal_disseminate.sh
#
# ONE job, ONE window.  It:
#
#   1. puts the tree back (a sandbox rebuild takes the working tree with
#      it; the credentials come back from the environment);
#   2. points the daily pulls at the init the calendar says they are on;
#   3. if any centre has actually moved, fetches what the new init
#      carries - the monthly fields, then the daily series, then the
#      polar-cap series for the seasonal systems;
#   4. rebuilds the panels, the registry and the site, puts the init
#      audit in front of the publish as a gate, and publishes; and
#   5. STOPS.
#
# IF NOTHING HAS MOVED IT DOES NOTHING, and says so.  That is what makes
# it safe to run it every day of the month: the release day is when the
# data arrives, and the job runs then.
#
# THE QUEUE IS SHARED.  The archive gives the account only a couple of
# slots and two submitters simply fight over them, so this script runs
# the fetchers one after the other and never in parallel.
set -u

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

export HOME="${HOME:-/workspace/.home}"
export PYTHONPATH="${PYTHONPATH:-/workspace/.home/.local/lib/python3.11/site-packages}"

LOG="logs_seasonal_disseminate.log"
say() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

DEV=/workspace/devrepo
DEV_REPO="https://github.com/massachusettswx-weather/seasonal-graphics-dev.git"

# ------------------------------------------------------------------
# 0. the tree
if [ ! -d "$DEV/.git" ]; then
    say "the tree $DEV is not there - cloning it"
    rm -rf "$DEV"
    git clone --depth 50 "$DEV_REPO" "$DEV" >>"$LOG" 2>&1 || {
        say "   the clone FAILED"
        exit 2
    }
    git -C "$DEV" remote set-url origin "$DEV_REPO"
fi

# ------------------------------------------------------------------
# 1. the plan: which init is each centre on, and has it moved?
say "the release calendar"
python3 -u tools/seasonal_init_plan.py --apply 2>&1 | tee -a "$LOG"
MOVED=$(python3 - <<'PY' >>"$LOG" 2>&1
import sys
sys.path.insert(0, ".")
import init_info
moved = []
for tag in init_info.CENTRES:
    if init_info.recorded_init(tag) != init_info.newest_init(tag):
        moved.append(tag)
print(" ".join(moved))
PY
)
say "   the centres that have moved: ${MOVED:-none}"

if [ -z "${MOVED// /}" ]; then
    say "nothing has moved - the site is already on the newest init."
    say "Nothing is fetched and nothing is published."
    exit 0
fi

# ------------------------------------------------------------------
# 2. the fetch.  ONE SUBMITTER AT A TIME: the archive's queue is shared
# with every other user and the account holds only a couple of slots.
say "the monthly fields"
python3 -u wipe_changed_inits.py snapshot >>"$LOG" 2>&1
# THE MONTHLY FETCH IS TRIED AGAIN.  The release day is the day the
# archive serves the new init, but the hour it appears in is not written
# down anywhere, so the fetch is tried a few times over the day.  It is
# safe to repeat: a centre already at the freshest init is skipped.
FETCH_RC=1
for attempt in 1 2 3 4 5 6; do
    python3 -u fetch_models.py >>"logs_fetch_models.log" 2>&1
    FETCH_RC=$?
    LEFT=$(python3 - <<'PY'
import sys
sys.path.insert(0, ".")
import init_info
left = [t for t in init_info.CENTRES
        if init_info.recorded_init(t) != init_info.newest_init(t)]
print(len(left))
PY
)
    say "   attempt $attempt: the fetch rc=$FETCH_RC, $LEFT centre(s) still on the old init"
    if [ "${LEFT:-1}" = "0" ]; then
        break
    fi
    [ "$attempt" = "6" ] || sleep 600
done
python3 -u wipe_changed_inits.py wipe >>"$LOG" 2>&1

say "the daily snowfall series"
python3 -u fetch_snow_daily.py --auto >>"logs_fetch_snow_daily.log" 2>&1
SNOW_RC=$?

say "the daily 10 hPa wind series"
python3 -u fetch_models_daily.py --auto >>"logs_fetch_models_daily.log" 2>&1
WIND_RC=$?

say "the polar-cap series of the seasonal systems"
python3 -u fetch_polar_models.py >>"data/polar_models.log" 2>&1 || true

# ------------------------------------------------------------------
# 3. the rebuild and the publish, with the init audit as the gate
say "the rebuild and the publish"
./refresh_site.sh "" "the seasonal: the $(date -u +%B) init" >>"$LOG" 2>&1
PUB_RC=$?

# ------------------------------------------------------------------
# 4. one line
say "done: the monthly fetch rc=$FETCH_RC, the daily snowfall rc=$SNOW_RC,"
say "the daily wind rc=$WIND_RC, the publish rc=$PUB_RC (0 = published,"
say "2 = the init audit said no)"
