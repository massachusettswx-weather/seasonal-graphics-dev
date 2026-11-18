#!/usr/bin/env bash
# Rebuild the working environment after the sandbox has been wiped.
#
# THE PROBLEM
# -----------
# The sandbox resets from time to time and the working tree comes back
# empty: no repo, no data, no docs, no credentials.  Rediscovering all of
# that by hand is what made the earlier sessions stall.  This script does it
# in one command.
#
# WHAT SURVIVES AND WHAT DOES NOT
# -------------------------------
#   survives  the code, the published site and the small derived data
#             (both GitHub repositories, the encrypted secret store and the
#             agent's memory)
#   does NOT  data/models/** (the model GRIBs - bulky, gitignored),
#             .cdsapirc and data/.github_token (the credentials), and the
#             python packages
#
# So this script:
#   1. clones the development repository (or pulls, if it is already here)
#   2. puts the python packages back
#   3. writes the credentials back out of the environment - they come from
#      the encrypted secret store, which survives the reset
#   4. recovers the model data: the job ids are tracked, so the results can
#      often be downloaded again WITHOUT queueing for them
#   5. starts the workers and prints what is alive and what is waiting
#
# USAGE
#   export CDS_API_KEY=<the cds key>        # from the encrypted secret store
#   export GITHUB_TOKEN=<the github pat>    # from the encrypted secret store
#   ./tools/bootstrap.sh                    # in the repo
#   ./tools/bootstrap.sh --pull             # only update an existing checkout
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO_URL="https://github.com/massachusettswx-weather/seasonal-graphics-dev.git"

if [ "${1:-}" != "--pull" ]; then
    if [ ! -f "$HERE/README.md" ]; then
        echo "== cloning the development repository"
        git clone --depth 50 "$REPO_URL" "$HERE" || exit 1
    else
        echo "== the checkout is already here - pulling"
        git -C "$HERE" pull --ff-only || \
            echo "   (the pull did not apply - carry on with what is here)"
    fi
fi
cd "$HERE"

echo "== the toolchain and the credentials"
./tools/auto_run.sh || echo "   (auto_run.sh did not finish cleanly)"

echo ""
echo "== the model data"
if [ -f .cdsapirc ]; then
    python3 tools/recover_jobs.py || true
else
    echo "   skipped: no .cdsapirc"
fi

# The ECMWF's field is carried over from the committed SEAS5 files, so
# the panels and the map can be built without waiting for the archive.
echo ""
echo "== the carried-over data"
python3 tools/carry_over_seas5.py || \
    echo "   (nothing to carry over)"

echo ""
echo "== what is here now"
python3 - <<'PY'
import json, os
root = os.getcwd()
reg = os.path.join(root, "data", "models_fetched.json")
if os.path.exists(reg):
    st = json.load(open(reg))
    have, miss = [], []
    for tag, rec in st.items():
        d = os.path.join(root, "data", "models", tag)
        ok = os.path.exists(os.path.join(d, "snowfall_monthly.grib")) or \
             os.path.exists(os.path.join(d, "snowfall_monthly.npz"))
        (have if ok else miss).append(tag)
    print("   model data present :", ", ".join(have) or "-")
    print("   model data missing :", ", ".join(miss) or "-")
else:
    print("   no registry yet")
print("   site               :", "docs/index.html" if os.path.exists("docs/index.html") else "MISSING")
PY
