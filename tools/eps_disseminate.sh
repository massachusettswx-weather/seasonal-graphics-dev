#!/usr/bin/env bash
# The EPS's own DISSEMINATION - the owner's two windows.
#
# THE OWNER'S WORD (27 November 2026): the 00Z cycle of the ECMWF EPS is
# wanted between 07:00 and 08:30 UTC and the 12Z cycle between 19:00 and
# 20:30 UTC.  Each cycle has its own window and its own job, and neither
# of them is inside the EC46's window (20:00-22:00 UTC), so there is never
# a second submitter at the climate store.
#
#     ./tools/eps_disseminate.sh 00z
#     ./tools/eps_disseminate.sh 12z
#
# ONE job, ONE cycle, ONE window.  It:
#
#   1. puts the tree back (a sandbox rebuild takes the working tree with
#      it; the credentials come back from the environment);
#   2. refreshes NOAA's CORe reanalysis - the section is measured with it,
#      and it runs about two days behind the day it is fetched for;
#   3. pulls the cycle from ECMWF's OPEN data, waiting for the steps the
#      open data has not put up yet;
#   4. draws the two charts;
#   5. publishes them to the DEVELOPMENT copy only;
#   6. puts the run that was just replaced into the archive; and
#   7. STOPS.
#
# WHY THE JOB WAITS.  ECMWF publishes the open data a step at a time: the
# first step of a cycle lands about 7.7 hours after its init and the last
# one - the 360-hour step, the end of the fifteen-day product - about 8.5
# hours after it (measured from the objects' own timestamps, 25-27 November
# 2026).  So the 12Z cycle is whole at about 20:30 UTC and the 00Z cycle
# at about 08:30.  The windows open before that, so the pull waits for the
# steps and fetches them when they arrive; the series is written only when
# the cycle is whole.
#
# THE PUBLISHING IS NARROW AND DEV-ONLY: the EPS's two charts, its one
# registry entry and its page entries, through tools/publish_polar_eps.py.
# That publisher refuses the operational clone outright - the EPS is a new
# product and it has not been approved for the operational site.
set -u

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

export HOME="${HOME:-/workspace/.home}"
export PYTHONPATH="${PYTHONPATH:-/workspace/.home/.local/lib/python3.11/site-packages}"

CYCLE="${1:-12z}"
case "$CYCLE" in
    00z|12z) ;;
    *) echo "usage: $0 00z|12z" >&2; exit 2 ;;
esac

LOG="logs_eps_disseminate_${CYCLE}.log"
say() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

DEV=/workspace/devrepo
DEV_REPO="https://github.com/massachusettswx-weather/seasonal-graphics-dev.git"

# how long to wait for the open data to finish the cycle.  The cycle is
# whole at about +8.5 h, and the window opens about 7.5 h before that.
WAIT_MINUTES="${EPS_WAIT_MINUTES:-150}"

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
# 0b. THE TOOLCHAIN.  The sandbox resets its python packages every
# hour or so, and `requests` and `eccodes` go with them - which kills
# the fetch without saying why.  The user site survives the reset, so
# the packages are put back there.
#
# ONLY THE PACKAGES.  This job publishes ONE product and nothing else,
# so the general publisher and the other workers are NOT started from
# here - tools/auto_run.sh would start them, and the general publisher
# would carry the whole development site across.
if ! python3 -c "import requests, eccodes" >/dev/null 2>&1; then
    say "the python packages are gone - putting them back"
    bash tools/restore_env.sh >>"$LOG" 2>&1 || true
fi
if ! python3 -c "import requests, eccodes" >/dev/null 2>&1; then
    say "the toolchain did NOT come back - the pull will fail"
fi

# ------------------------------------------------------------------
# 1. the reanalysis half's source.  NOAA's CORe is a couple of days
# behind, and the section is measured with it: a stale file means the
# chart's reanalysis half stops short of the forecast.
say "the CORe reanalysis"
python3 -u fetch_polar_core.py recent >>"logs_fetch_polar_core_recent.log" 2>&1
CORE_RC=$?

# ------------------------------------------------------------------
# 2. the run itself
say "the $CYCLE cycle of the EPS"
python3 -u fetch_polar_eps.py --cycle "$CYCLE" --wait-minutes "$WAIT_MINUTES" \
    >>"logs_fetch_polar_eps.py.log" 2>&1
FETCH_RC=$?

python3 - <<'PY' >>"$LOG" 2>&1
import json
try:
    d = json.load(open("data/polar_eps_z.json")).get("eps") or {}
    print("   the EPS series: the run %s, %d days, %s members, %s"
          % (d.get("run"), len(d.get("times") or []), d.get("members"),
             " and ".join(d.get("cycles") or []) or "one cycle"))
except Exception as e:
    print("   the EPS series could not be read: %s" % e)
PY

# ------------------------------------------------------------------
# 3. the charts
say "the charts"
python3 -u plot_polar_cap.py eps "ECMWF EPS" >>"$LOG" 2>&1 || true
python3 -u plot_polar_sectors.py eps "ECMWF EPS" >>"$LOG" 2>&1 || true
mkdir -p docs/assets/polar
for f in polar_cap_eps.png polar_sectors_eps.png; do
    if [ -f "output/polar_cap/$f" ]; then
        cp -f "output/polar_cap/$f" "docs/assets/polar/$f"
    fi
done

# ------------------------------------------------------------------
# 4. the publication - the development copy only
say "the publication (the development copy only)"
python3 -u tools/publish_polar_eps.py --repo "$DEV" --apply --push >>"$LOG" 2>&1
DEV_RC=$?

# ------------------------------------------------------------------
# 5. the archive: the run that was just replaced goes in, and a week is
# kept.  It is built from the git history, so it runs AFTER the
# publication.
say "the archive"
python3 -u tools/build_polar_archive.py --repo "$DEV" >>"$LOG" 2>&1 || true
python3 -u tools/publish_polar_archive.py --repo "$DEV" --apply --push \
    >>"$LOG" 2>&1 || true

# ------------------------------------------------------------------
# 6. one line
say "done: the reanalysis rc=$CORE_RC, the fetch rc=$FETCH_RC, the"
say "development copy rc=$DEV_RC (0 = published, 2 = nothing to publish,"
say "3 = the push failed, 4 = the target already carries it)"
