#!/usr/bin/env bash
# The EC46's own DISSEMINATION - the owner's 20:00-22:00 UTC window.
#
# ONE job, ONE window, ONE product:
#
#   1. put the trees back (a sandbox rebuild takes the working tree with
#      it; the credentials come back from the environment);
#   2. pull the newest EC46 run the store has - every day, because the
#      archive holds one every day - in the FOREGROUND, so that "the run
#      has arrived" is an answer and not a hope;
#   3. draw the EC46's polar-cap charts from it;
#   4. publish them: the development copy and the operational site;
#   5. put the run that was just replaced into the archive; and
#   6. and then STOP.
#
# WHY IT IS ITS OWN JOB AND NOT PART OF THE NIGHTLY GEFVSv12 ONE.  The
# owner asked for it on 27 November 2026: the EC46's run is wanted
# between 20:00 and 22:00 UTC, and the GEFSv12's cycle between 03:00
# and 04:00 UTC.  Two windows, two jobs, and nothing runs outside them.
# They never overlap, so there is never a second submitter.
#
# THE EPS IS NOT HERE ANY MORE.  It was, until 27 November 2026, and the
# owner gave it windows of its own: the 00Z cycle between 07:00 and 08:30
# UTC and the 12Z cycle between 19:00 and 20:30 UTC.  It has its own
# script (tools/eps_disseminate.sh) and its own two jobs.
#
#     ./tools/ec46_disseminate.sh
#
# The EC46's fetch resumes from data/polar_ec46_jobs.json and the series
# itself lives in data/polar_ec46_z.json - both are in git, so a rebuild
# does not pull the run again.
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

# THE EC46's days: EVERY DAY.  The owner's own days were Monday, Thursday
# and Saturday (22 November 2026), chosen because the extended range was
# thought to run on Mondays and Thursdays.  It does not: measured 22 November
# 2026, every run from 10 to 21 November served the 46-day window, the
# Saturdays and the Sundays included - the archive holds a run every day.
#
# And the archive holds it LATE: about 27 hours after its date (the
# 2026-11-26 run was in the store at 03:15 UTC on the 27th).  So a pull on
# three days a week left the site two, three, sometimes four days behind -
# the owner's word on 26 November 2026: "why don't I see the newly updated
# EC46 from today".  A pull every night at 21:00 UTC takes the run the
# moment it lands.
#
# The pull is cheap when there is nothing new: the fetch does not ask the
# archive for a run that is already on disk, and the publisher refuses a
# target that already carries the section.
EC46_DAYS="${EC46_DAYS:-1 2 3 4 5 6 7}"
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
# 1. is today one of the EC46's days?  (all of them, unless the caller
#    says otherwise)
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
# 2. THE EC46's run, in the foreground
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
# 4b. THE ARCHIVE.  The owner's word (27 November 2026): when each run of
# our models is posted, the one before it goes into the archive, and a
# week is kept.  The archive is built from the git history, so it runs
# AFTER the publication - the run that was just replaced is in the history
# by then.
say "the archive"
python3 -u tools/build_polar_archive.py --repo "$DEV" >>"$LOG" 2>&1 || true
python3 -u tools/publish_polar_archive.py --repo "$DEV" --apply --push >>"$LOG" 2>&1 || true
python3 -u tools/publish_polar_archive.py --repo "$LIVE" --apply --push --prod --approved >>"$LOG" 2>&1 || true

# ------------------------------------------------------------------
# 5. one line
say "done: the fetch rc=$FETCH_RC; the development copy rc=$DEV_RC, the"
say "operational site rc=$LIVE_RC (0 = published, 2 = nothing to publish,"
say "3 = the push failed, 4 = the target already carries it)"
