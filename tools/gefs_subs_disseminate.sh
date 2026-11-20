#!/usr/bin/env bash
# The NIGHTLY GEFSv12 sub-seasonal DISSEMINATION.
#
# ONE job, ONE product, ONE night:
#
#   1. put the pipeline back (a sandbox rebuild takes the packages, the
#      credentials and the workers with it);
#   2. pull the day's other data;
#   3. WATCH for the newest COMPLETE 00Z GEFS cycle - the one that
#      carries the full 35-day range - and fetch it;
#   4. publish it: the two charts and the one registry entry, on the
#      development copy and on the operational site;
#   5. and then STOP.  The watcher runs until the data has come in, and
#      not a minute longer; the next night is the next run.
#
# WHY A WATCHER AND NOT A SINGLE TRY.  NCEP publishes the members of the
# 00Z cycle in FOUR BATCHES, and the last one lands at about 00:40 UTC
# the NEXT day - so the cycle for a given day appears at an uncertain
# hour, and the fetch itself takes about an hour.  The job starts at
# 03:00 UTC and keeps checking until the cycle for yesterday is on the
# site.  The cycle's own date is the test, not the clock: a cycle that
# is still uploading is never published.
#
# THE PUBLISHING IS NARROW.  It is tools/publish_polar_subseasonal.py:
# one product, two pictures, one registry entry, seven files.  The
# general publisher stays off, so nothing else about the site moves.
#
#     ./tools/gefs_subs_disseminate.sh
#
# It is safe to run at any time: the narrow path is idempotent (it says
# "the target already carries this cycle" and does nothing), and the
# fetch resumes from data/polar_gefs_jobs.json, which is in git.
set -u

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

export HOME="${HOME:-/workspace/.home}"
export PYTHONPATH="${PYTHONPATH:-/workspace/.home/.local/lib/python3.11/site-packages}"

LOG="logs_gefs_subs.log"
say() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

DEV=/workspace/devrepo
LIVE=/workspace/repo
DEV_REPO="https://github.com/massachusettswx-weather/seasonal-graphics-dev.git"
LIVE_REPO="https://github.com/massachusettswx-weather/seasonal-graphics.git"

# how long the watcher keeps looking.  The typical night is over in an
# hour and a half; this is the backstop for a night when NCEP is late.
WATCH_HOURS="${WATCH_HOURS:-12}"
CHECK_EVERY="${CHECK_EVERY:-1200}"      # seconds between checks

# ------------------------------------------------------------------
# 0. the trees
# A sandbox rebuild can take the working tree with it.  Both clones are
# PUBLIC, so they can be fetched without a credential; the token is only
# needed for the push, and the push script puts it in a credential file
# for the length of the push and takes it out again.
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
# 1. the toolchain, the credentials and the other workers
# tools/auto_run.sh does all of it.  SKIP_GEFS=1 keeps the GEFS fetch
# out of the daily pull: this script owns it, because the trigger is
# the run finishing and not the pull's start.
export SKIP_GEFS=1
say "the pipeline"
bash tools/auto_run.sh >>"$LOG" 2>&1

# ------------------------------------------------------------------
# 1b. the C3S centres
# If a centre is not on disk, its results are fetched again - DOWNLOAD
# ONLY.  The recovery never re-submits a request, because two submitters
# at once is the one thing this pipeline must never do: the seasonal
# fetch needs those queue slots for the December rollover.
MISSING=""
for tag in ecmwf-seas5 ukmo-gloseas6 meteo-france-s9 cmcc-sps4 dwd-gcfs2 \
           eccc-gem5 eccc-canesm5 eccc-cansips; do
    if [ ! -d "data/models/$tag" ] || [ -z "$(ls -A "data/models/$tag" 2>/dev/null)" ]; then
        MISSING="$MISSING $tag"
    fi
done
if [ -n "$MISSING" ]; then
    say "   the C3S centres that are not on disk:$MISSING"
    python3 -u tools/recover_jobs.py --no-request $MISSING >>"$LOG" 2>&1
    say "   the recovery finished (download only - nothing was re-submitted)"
fi

# ------------------------------------------------------------------
# 2. the fetch state
# The state file is what a rebuild would throw away, and it holds an
# hour of downloading.  It is committed so the next run resumes instead
# of starting again, and the commit is pushed - git is the only thing
# that survives a sandbox rebuild.
push_dev() {
    python3 - "$DEV" <<'PY' >>"$LOG" 2>&1
import os, subprocess, sys
repo = sys.argv[1]
tok = (os.environ.get("GITHUB_TOKEN") or "").strip()
if not tok:
    print("   no GitHub token - the fetch state stays local")
    sys.exit(0)
cred = os.path.join(repo, ".git", "gh_cred")
with open(cred, "w") as f:
    f.write("https://x-access-token:%s@github.com\n" % tok)
os.chmod(cred, 0o600)
env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
try:
    r = subprocess.run(["git", "-c", "credential.helper=store --file=%s" % cred,
                        "push", "origin", "HEAD"],
                       cwd=repo, capture_output=True, text=True, env=env)
    sys.stdout.write(r.stderr or "")
    sys.exit(r.returncode)
finally:
    try:
        os.remove(cred)
    except OSError:
        pass
PY
}

commit_state() {
    [ -f data/polar_gefs_jobs.json ] || return 0
    git add -- data/polar_gefs_jobs.json 2>/dev/null
    if ! git diff --cached --quiet -- data/polar_gefs_jobs.json 2>/dev/null; then
        git -c user.name="MCode" -c user.email="mcode@local" commit -q \
            -m "The GEFSv12 fetch state, so a rebuild does not download it again" \
            >>"$LOG" 2>&1 && say "   the fetch state is committed"
    fi
    push_dev && say "   the development copy is up to date on the server"
}

# ------------------------------------------------------------------
# 3. the watcher
# THE CYCLE WE ARE WAITING FOR.  The 00Z cycle of yesterday is complete
# at about 00:40 UTC today, so a run that starts at 03:00 UTC wants
# yesterday's cycle - and if NCEP is late, the next one.
# EXPECTED_CYCLE can be set by hand - it is the hook the tests use.
EXPECTED=${EXPECTED_CYCLE:-$(date -u -d 'yesterday' +%Y%m%d)}
DEADLINE=$(( $(date -u +%s) + WATCH_HOURS * 3600 ))
say "watching for the $EXPECTED 00Z cycle (until $(date -u -d "@$DEADLINE" +%H:%M) UTC)"

LIVE_RC=2
DEV_RC=2
CYCLE="?"
while :; do
    # 3a. the fetch, in the foreground: "the run has finished" is then an
    # answer and not a hope.  It is quick when there is nothing new.
    python3 -u fetch_polar_gefs.py >>logs_fetch_polar_gefs.py.log 2>&1
    commit_state

    CYCLE=$(python3 - <<'PY' 2>/dev/null
import json
try:
    d = json.load(open("data/polar_model_z.json"))
    g = d.get("gefsv12") or {}
    run = str(g.get("run") or "?")
    print("%s (%d days)" % (run, len(g.get("times") or [])))
except Exception:
    print("?")
PY
)
    RUN=${CYCLE%% *}

    # 3b. the dissemination - the narrow path, to both copies.
    python3 -u tools/publish_polar_subseasonal.py --repo "$DEV" --apply --push \
        >>"$LOG" 2>&1
    DEV_RC=$?
    python3 -u tools/publish_polar_subseasonal.py --repo "$LIVE" --apply --push \
        --prod --approved >>"$LOG" 2>&1
    LIVE_RC=$?

    # 3c. is the cycle we were waiting for on the site?  The narrow path
    # says 0 when it published and 4 when the site already carries it.
    if [ "$RUN" = "$EXPECTED" ] && { [ "$LIVE_RC" = "0" ] || [ "$LIVE_RC" = "4" ]; }; then
        say "the $RUN cycle is on the site - the watcher stops here"
        break
    fi

    NOW=$(date -u +%s)
    if [ "$NOW" -ge "$DEADLINE" ]; then
        say "the watcher has run out of night ($WATCH_HOURS h) - the cycle"
        say "$EXPECTED has not arrived; the site still carries what it had"
        break
    fi
    if [ "$RUN" != "$EXPECTED" ]; then
        say "   the cycle on disk is $RUN; we are waiting for $EXPECTED"
    else
        say "   the cycle $RUN is here but the publication did not go"
        say "   through (rc=$LIVE_RC) - trying again"
    fi
    sleep "$CHECK_EVERY"
done

# ------------------------------------------------------------------
# 4. one line
say "done: the cycle $CYCLE; the development copy rc=$DEV_RC, the operational site rc=$LIVE_RC (0 = published, 2 = nothing to publish, 3 = the push failed, 4 = already current)"
