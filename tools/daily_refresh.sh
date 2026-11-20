#!/usr/bin/env bash
# The daily pull: the products that move every day.
#
#     ./tools/daily_refresh.sh
#
# Everything here is read from a PUBLIC source and needs no key and no
# queue, so it can be run by anything, at any time:
#
#   fetch_oisst.py       the observed SST the ENSO plumes are drawn against
#   fetch_enso_noaa.py   the NOAA ENSO index
#   fetch_cfsv2.py       the NOAA CFSv2
#   fetch_sfs.py         the NOAA SFSv1, the seasonal model of our own
#   fetch_polar_core.py  NOAA's CORe reanalysis - the polar cap page's
#                        reanalysis half
#   fetch_polar_gefs.py  the GEFSv12's 35-day extended range - the polar
#                        cap page's forecast half
#
# THE LAST TWO ARE NEW HERE, and they are the reason the polar cap page
# went stale: the GEFSv12 panel was drawn from a run that was a week old
# because NOTHING called the GEFS fetcher.  The fetcher existed and worked;
# it was simply never wired into anything, so the panel could only be
# refreshed by hand.
#
# THE SLOW ONES RUN IN THE BACKGROUND.  The GEFS fetcher downloads 35
# daily leads for 31 members - an hour when the run is new - and the SFS
# takes a few minutes, so this script must not hold a caller up for an
# hour.  They are started detached and their own logs carry the result.
#
# ONCE A DAY, not once a run: the mark file is dated, so a keepalive that
# fires every twenty minutes does the work once and then stops.  The mark
# lives in data/, which a sandbox rebuild takes away - and that is right:
# after a rebuild the data is gone too, so a refresh is what is wanted.
# The mark is REMOVED again if a step failed, so the next run finishes
# the job instead of skipping it.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

export HOME="${HOME:-/workspace/.home}"
export PYTHONPATH="${PYTHONPATH:-/workspace/.home/.local/lib/python3.11/site-packages}"

LOG="${DAILY_LOG:-logs_daily_refresh.log}"
mkdir -p data
MARK="data/.daily_fetch_$(date -u +%Y-%m-%d)"
if [ -f "$MARK" ]; then
    echo "the daily refresh for $(date -u +%Y-%m-%d) has already run"
    exit 0
fi
touch "$MARK"

say() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

# in the foreground: quick, and the site wants them today
say "the daily refresh"
FAILED=0
for f in fetch_oisst.py fetch_enso_noaa.py fetch_cfsv2.py; do
    if [ ! -f "$f" ]; then
        say "  $f is not here - skipped"
        continue
    fi
    say "  $f"
    if ! python3 -u "$f" >> "$LOG" 2>&1; then
        say "  $f FAILED"
        FAILED=1
    fi
done

# in the background: slow, and nothing waits on them
#
# THE GEFS FETCH CAN BE HANDED TO SOMEONE ELSE.  Set SKIP_GEFS=1 and the
# GEFSv12 is not started here: tools/gefs_subs_disseminate.sh owns it,
# because the trigger for publishing is the RUN FINISHING and not the
# pull's start - so the fetch must be in the foreground of the job that
# waits for it.
SLOW="fetch_sfs.py fetch_polar_core.py"
if [ "${SKIP_GEFS:-}" != "1" ]; then
    SLOW="$SLOW fetch_polar_gefs.py"
fi
for f in $SLOW; do
    if [ ! -f "$f" ]; then
        say "  $f is not here - skipped"
        continue
    fi
    say "  $f (in the background)"
    setsid nohup python3 -u "$f" >> "logs_$f.log" 2>&1 < /dev/null &
    sleep 1
done

if [ "$FAILED" != "0" ]; then
    rm -f "$MARK"
    say "a step failed - the mark is cleared so the next run finishes the job"
else
    say "the daily refresh is done (the slow fetches are still running)"
fi
