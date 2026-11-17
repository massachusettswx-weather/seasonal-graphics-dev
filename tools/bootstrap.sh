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
#             (both GitHub repositories, and the agent's memory)
#   does NOT  data/models/** (the model GRIBs - bulky, gitignored),
#             .cdsapirc and data/.github_token (the credentials), and the
#             python packages
#
# So this script:
#   1. clones the development repository (or pulls, if it is already here)
#   2. writes the credentials back out of the environment
#   3. puts the python packages back
#   4. recovers the model data: the job ids are tracked, so the results can
#      often be downloaded again WITHOUT queueing for them
#   5. prints what is still missing
#
# USAGE
#   export CDS_API_KEY=<the cds key>        # from the encrypted secret store
#   export GITHUB_TOKEN=<the github pat>    # from the encrypted secret store
#   ./tools/bootstrap.sh                    # in the repo
#   ./tools/bootstrap.sh --pull             # only update an existing checkout
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO_URL="https://github.com/Matthew22-cmd/seasonal-graphics-dev.git"

if [ "${1:-}" != "--pull" ]; then
    if [ ! -f "$HERE/README.md" ]; then
        echo "== cloning the development repository"
        git clone --depth 50 "$REPO_URL" "$HERE" || exit 1
    else
        echo "== the checkout is already here - pulling"
        git -C "$HERE" pull --ff-only || echo "   (the pull did not apply - carry on with what is here)"
    fi
fi

echo "== credentials"
./tools/restore_secrets.sh || echo "   (no credentials yet - the fetches will not work)"

echo "== python packages"
./tools/restore_env.sh || echo "   (the packages did not install - the GRIB readers will fail)"

echo "== the model data"
if [ -f .cdsapirc ]; then
    python3 tools/recover_jobs.py || true
else
    echo "   skipped: no .cdsapirc"
fi

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
        ok = os.path.exists(os.path.join(d, "snowfall_monthly.grib"))
        (have if ok else miss).append(tag)
    print("   model data present :", ", ".join(have) or "-")
    print("   model data missing :", ", ".join(miss) or "-")
else:
    print("   no registry yet")
print("   site               :", "docs/index.html" if os.path.exists("docs/index.html") else "MISSING")
PY
