#!/usr/bin/env bash
# The daily GEFSv12 sub-seasonal DISSEMINATION.
#
# ONE job, ONE product:
#
#   1. put the pipeline back (a sandbox rebuild takes the packages, the
#      credentials and the workers with it);
#   2. pull the day's other data;
#   3. fetch the NEWEST COMPLETE 00Z GEFS cycle - the one that carries the
#      full 35-day range - and WAIT for it to finish;
#   4. publish it: the two charts and the one registry entry, on the
#      development copy and on the operational site.
#
# THE TRIGGER IS THE RUN, NOT A CLOCK.  The panel goes out when the newest
# 00Z cycle has finished downloading, so the site carries the latest model
# run the moment that run exists - once a day, because that is how often
# NCEP publishes one.
#
# THE PUBLISHING IS NARROW.  It is tools/publish_polar_subseasonal.py:
# one product, two pictures, one registry entry, seven files.  The
# general publisher stays off, so nothing else about the site moves.
#
#     ./tools/gefs_subs_disseminate.sh
#
# It is safe to run at any time: the narrow path is idempotent (it says
# "the target already carries this cycle" and does nothing), and the fetch
# resumes from data/polar_gefs_jobs.json, which is in git.
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

# ------------------------------------------------------------------
# 0. the trees
# A sandbox rebuild can take the working tree with it.  Both clones are
# PUBLIC, so they can be fetched without a credential; the token is only
# needed for the push, and the push script puts it in the URL for the
# length of the push and takes it out again.
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
# tools/auto_run.sh does all of it.  SKIP_GEFS=1 keeps the GEFS fetch out
# of the daily pull: this script owns it, because the trigger is the run
# finishing and not the pull's start.
export SKIP_GEFS=1
say "the pipeline"
bash tools/auto_run.sh >>"$LOG" 2>&1

# ------------------------------------------------------------------
# 1b. the C3S centres
# If a centre is not on disk, its results are fetched again - DOWNLOAD
# ONLY.  The recovery never re-submits a request, because two submitters
# at once is the one thing this pipeline must never do: the seasonal fetch
# needs those queue slots for the December rollover.
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
# 2. the GEFS cycle
# The fetcher finds the newest cycle that carries the whole 35-day range
# and downloads it; when there is nothing new it puts the series back
# together from the state file in a few seconds.  It runs in the
# FOREGROUND here, so "the run has finished" is a real answer and not a
# hope: the cache only holds a complete series once the fetch is done.
say "the GEFSv12 00Z cycle"
python3 -u fetch_polar_gefs.py >>logs_fetch_polar_gefs.py.log 2>&1
FETCH_RC=$?
if [ "$FETCH_RC" != "0" ]; then
    say "   the fetch FAILED (rc=$FETCH_RC) - nothing is published"
fi

# The state file is what a rebuild would throw away, and it holds an hour
# of downloading.  It is committed so the next run resumes instead of
# starting again, and the commit is pushed - git is the only thing that
# survives a sandbox rebuild.
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

if [ -f data/polar_gefs_jobs.json ]; then
    git add -- data/polar_gefs_jobs.json 2>/dev/null
    if ! git diff --cached --quiet -- data/polar_gefs_jobs.json 2>/dev/null; then
        git -c user.name="MCode" -c user.email="mcode@local" commit -q \
            -m "The GEFSv12 fetch state, so a rebuild does not download it again" \
            >>"$LOG" 2>&1 && say "   the fetch state is committed"
    fi
fi
push_dev && say "   the development copy is up to date on the server"

# ------------------------------------------------------------------
# 3. the dissemination
# The narrow path.  It draws the two charts from the series that is on
# disk, patches the ONE registry entry that names them, and pushes those
# seven files - to the development copy, and to the operational site.
# The operational push is the owner's approval, given for this product on
# 20 Nov 2026 ("we need to extend the daily GEFSv12 SUBS update to the
# live site as well") and confirmed on 22 Nov ("fix the dissemination of
# 00z GEFSv12 SUBS to update daily").
say "the development copy"
python3 -u tools/publish_polar_subseasonal.py --repo "$DEV" --apply --push \
    >>"$LOG" 2>&1
DEV_RC=$?
say "the operational site"
python3 -u tools/publish_polar_subseasonal.py --repo "$LIVE" --apply --push \
    --prod --approved >>"$LOG" 2>&1
LIVE_RC=$?

# ------------------------------------------------------------------
# 4. one line
CYCLE=$(python3 - <<'PY' 2>/dev/null
import json
try:
    d = json.load(open("data/polar_model_z.json"))
    g = d.get("gefsv12") or {}
    print("%s (%d days)" % (g.get("run", "?"), len(g.get("times") or [])))
except Exception:
    print("?")
PY
)
say "done: the cycle $CYCLE; the development copy rc=$DEV_RC, the operational site rc=$LIVE_RC (0 = published or already current, 2 = nothing to publish, 3 = the push failed)"
