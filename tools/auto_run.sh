#!/usr/bin/env bash
# Bring the pipeline back up, and keep it up.
#
#   ./tools/auto_run.sh
#
# THE SANDBOX REBUILDS every hour or two, and a rebuild takes away the
# python packages and every background process - the CDS request pool, the
# polar puller and the publisher all die with it.  Nothing on the site
# breaks, because the site lives on GitHub, but the pipeline stops until
# somebody notices.
#
# This is the one command that puts it all back:
#
#   1. the python packages (requests, eccodes, numcodecs, Pillow, and the
#      zarr stack the NOAA pullers need);
#   2. the credentials - the CDS key and the GitHub token, which live in
#      the ENCRYPTED SECRET STORE and arrive as environment variables, so
#      they survive every rebuild;
#   3. the workers: the CDS request pool (only with a key), the polar-cap
#      puller and the publisher, each started only if it is not already
#      running;
#   4. a status report, so a human (or a scheduled task) can see at a
#      glance what is alive and what is waiting.
#
# The publisher watches the model data and rebuilds and publishes the site
# by itself when anything changes - the map export is in that chain, so
# the world map follows the panels.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# ------------------------------------------------------------------
# 1. the toolchain
SITE="$HOME/.local/lib/python3.11/site-packages"
mkdir -p "$SITE"
if ! python3 -c "import requests, eccodes, PIL" >/dev/null 2>&1; then
    log "putting the python packages back"
    pip install --break-system-packages -q --index-url https://pypi.org/simple \
        --target "$SITE" requests eccodes numcodecs Pillow s3fs zarr \
        h5netcdf h5py >/dev/null 2>&1
fi
export PYTHONPATH="$SITE:${PYTHONPATH:-}"
if ! python3 -c "import requests, eccodes, PIL" >/dev/null 2>&1; then
    log "the toolchain did NOT come back - the fetchers will fail"
else
    log "the toolchain is in place"
fi

# ------------------------------------------------------------------
# 2. the credentials
# They come from the encrypted secret store as environment variables, so
# they are here after a rebuild even though the sandbox files are not.
if [ -n "${CDS_API_KEY:-}" ]; then
    if [ ! -f .cdsapirc ] || ! grep -q "$CDS_API_KEY" .cdsapirc 2>/dev/null; then
        cat > .cdsapirc <<EOF
url: https://cds.climate.copernicus.eu/api
key: $CDS_API_KEY
EOF
        chmod 600 .cdsapirc
        log "the CDS key is in place"
    fi
else
    log "no CDS key in the environment - the C3S fetchers stay idle"
fi

if [ -n "${GITHUB_TOKEN:-}" ]; then
    mkdir -p data
    if [ ! -f data/.github_token ] || \
       [ "$(cat data/.github_token 2>/dev/null)" != "$GITHUB_TOKEN" ]; then
        printf '%s' "$GITHUB_TOKEN" > data/.github_token
        chmod 600 data/.github_token
        log "the GitHub token is in place"
    fi
else
    log "no GitHub token in the environment - the site is built locally but NOT published"
fi

# The development copy's password gate.  The owner asked for it to be switched
# off (17 Nov 2026), so the switch has to come back with the credentials -
# otherwise the next rebuild would put the gate in front of the site again
# and lock them out.  The switch lives in the encrypted secret store, so it
# survives every rebuild.
if [ "${SITE_NO_GATE:-}" = "1" ] || [ "${SITE_NO_GATE:-}" = "true" ]; then
    mkdir -p data
    if [ ! -f data/.no_gate ]; then
        : > data/.no_gate
        log "the password gate is OFF (the development copy is published open)"
    fi
elif [ -n "${SITE_PASSWORD:-}" ]; then
    mkdir -p data
    if [ ! -f data/.dev_gate_password ] || \
       [ "$(cat data/.dev_gate_password 2>/dev/null)" != "$SITE_PASSWORD" ]; then
        printf '%s' "$SITE_PASSWORD" > data/.dev_gate_password
        chmod 600 data/.dev_gate_password
        log "the gate password is in place"
    fi
fi

# ------------------------------------------------------------------
# 3. the workers
# pgrep also matches the zombies of an earlier run, so the check looks at
# the process state and ignores the dead ones.
running() { ps -eo stat,cmd | grep -v "^Z" | grep -F "$1" | grep -v grep >/dev/null 2>&1; }

if [ -f .cdsapirc ]; then
    if ! running "run_nov_queue.py"; then
        log "starting the CDS request pool"
        setsid nohup bash run_nov_queue.sh >/dev/null 2>&1 </dev/null &
        sleep 3
    fi
    if ! running "fetch_polar_models.py"; then
        log "starting the polar-cap puller"
        setsid nohup python3 -u fetch_polar_models.py \
            >>data/polar_models.log 2>&1 </dev/null &
        sleep 3
    fi
else
    log "the CDS request pool stays idle (no key)"
fi

# The publisher watches the model data and publishes the site when it
# changes.  The owner asked for the scheduled posts to be turned off
# (17 Nov 2026), so it is NOT started unless a publish is wanted:
#   NO_PUBLISH=1  -> the publisher stays stopped (the default while the
#                    posts are off; the data is still pulled and the site
#                    is still built locally, nothing goes out on its own)
#   unset          -> the publisher runs as it always did
if [ -n "${NO_PUBLISH:-}" ]; then
    log "the publisher stays stopped (NO_PUBLISH is set) - nothing is published"
elif ! running "auto_publish.sh"; then
    log "starting the publisher"
    setsid nohup bash auto_publish.sh >logs_auto_publish_watch.log 2>&1 </dev/null &
    sleep 3
fi

# ------------------------------------------------------------------
# 4. the status
echo ""
echo "the workers:"
for w in run_nov_queue.py fetch_polar_models.py auto_publish.sh; do
    n=$(ps -eo stat,cmd | grep -v "^Z" | grep -F "$w" | grep -vc grep)
    if [ "$n" -gt 0 ]; then
        printf "  %-24s %d process(es)\n" "$w" "$n"
    else
        printf "  %-24s NOT RUNNING\n" "$w"
    fi
done
echo ""
echo "the credentials:"
[ -f .cdsapirc ] && echo "  the CDS key       in place" || \
    echo "  the CDS key       MISSING (the C3S models cannot be pulled)"
[ -f data/.github_token ] && echo "  the GitHub token  in place" || \
    echo "  the GitHub token  MISSING (the site is built locally, not published)"
echo ""
echo "the model data:"
if [ -d data/models ]; then
    for d in data/models/*/; do
        tag=$(basename "$d")
        n=$(ls "$d" 2>/dev/null | wc -l)
        [ "$n" -gt 0 ] && printf "  %-22s %s file(s)\n" "$tag" "$n"
    done
else
    echo "  none yet"
fi
echo ""
echo "the last publish:"
git log --oneline -3 2>/dev/null | sed 's/^/  /'
