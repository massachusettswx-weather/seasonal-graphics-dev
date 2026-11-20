#!/usr/bin/env bash
# The daily pull: the products that move every day.
#
#     ./tools/daily_refresh.sh
#
# Everything here is read from a PUBLIC source and needs no key and no
# queue, so it can be run by anything, at any time:
#
#   fetch_oisst.py       the observed SST the ENSO plumes are drawn against
#   fetch_sfs.py         the NOAA SFSv1, the seasonal model of our own
#   fetch_cfsv2.py       the NOAA CFSv2
#   fetch_enso_noaa.py   the NOAA ENSO index
#   fetch_polar_gefs.py  the GEFSv12's 35-day extended range - the polar
#                        cap page's forecast half
#   fetch_polar_core.py  NOAA's CORe reanalysis - the polar cap page's
#                        reanalysis half
#
# THE LAST TWO ARE NEW HERE, and they are the reason the polar cap page
# went stale: the GEFSv12 panel was drawn from a run that was a week old
# because NOTHING called the GEFS fetcher.  The fetcher existed and worked;
# it was simply never wired into anything, so the panel could only be
# refreshed by hand.
#
# ONCE A DAY, not once a run: the mark file is dated, so a keepalive that
# fires every twenty minutes does the work once and then stops.  The mark
# lives in data/, which a sandbox rebuild takes away - and that is right:
# after a rebuild the data is gone too, so a refresh is what is wanted.
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
# The mark is touched FIRST: a refresh that is interrupted half way
# should be finished by the next run, not skipped by it.
touch "$MARK"

say() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "the daily refresh"
for f in fetch_oisst.py fetch_sfs.py fetch_cfsv2.py fetch_enso_noaa.py \
         fetch_polar_core.py fetch_polar_gefs.py; do
    if [ ! -f "$f" ]; then
        say "  $f is not here - skipped"
        continue
    fi
    say "  $f"
    python3 -u "$f" >> "$LOG" 2>&1
done
say "the daily refresh is done"
