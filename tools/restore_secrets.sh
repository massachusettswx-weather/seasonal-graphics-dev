#!/usr/bin/env bash
# Write the credentials the pipeline needs back onto disk.
#
# WHY THIS EXISTS
# ---------------
# The sandbox is reset from time to time and the working tree comes back
# empty.  The credentials are deliberately kept OUT of git (.cdsapirc and
# data/.github_token are gitignored), so a wipe takes them with it, and
# every fetcher and every push then fails with a confusing error instead of
# saying "no key".
#
# The credentials themselves are kept in the ENCRYPTED SECRET STORE, which
# survives the reset.  This script writes them back out from the
# environment, so a fresh session only has to export them:
#
#   export CDS_API_KEY=<the cds key>
#   export GITHUB_TOKEN=<the github pat>
#   ./tools/restore_secrets.sh
#
# The key file is written with mode 600 and is never committed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

rc=0

if [ -n "${CDS_API_KEY:-}" ]; then
    cat > .cdsapirc <<EOF
url: https://cds.climate.copernicus.eu/api
key: $CDS_API_KEY
EOF
    chmod 600 .cdsapirc
    echo "wrote .cdsapirc (mode 600)"
else
    echo "CDS_API_KEY is not set - .cdsapirc left as it was" >&2
    rc=1
fi

if [ -n "${GITHUB_TOKEN:-}" ]; then
    mkdir -p data
    printf '%s' "$GITHUB_TOKEN" > data/.github_token
    chmod 600 data/.github_token
    echo "wrote data/.github_token (mode 600)"
else
    echo "GITHUB_TOKEN is not set - data/.github_token left as it was" >&2
    rc=1
fi

# The development copy's gate password lives here too.  The password file is
# gitignored, so a wipe takes it with the tree, and without it the builder
# falls back to the PUBLISHED hash - which must be the hash of the password
# the owner actually has.  Keeping the password in the secret store means
# the gate never drifts away from the password that is written down.
if [ -n "${SITE_PASSWORD:-}" ]; then
    mkdir -p data
    printf '%s' "$SITE_PASSWORD" > data/.dev_gate_password
    chmod 600 data/.dev_gate_password
    echo "wrote data/.dev_gate_password (mode 600)"
fi

# The development copy's password gate can be switched off deliberately.  The
# switch lives in the secret store too, so it survives the wipe: without it
# the next rebuild would put the gate back and lock the owner out again.
if [ "${SITE_NO_GATE:-}" = "1" ] || [ "${SITE_NO_GATE:-}" = "true" ]; then
    mkdir -p data
    : > data/.no_gate
    echo "wrote data/.no_gate - the development copy will be published open"
fi

# The owner asked for the SCHEDULED POSTS to be off (17 Nov 2026): the
# data is still pulled and the site is still built locally, but nothing
# goes out on its own.  That switch has to survive a wipe too, so it is
# a file rather than an environment variable - otherwise the next rebuild
# would start publishing again.
if [ "${SITE_NO_PUBLISH:-}" = "1" ] || [ "${SITE_NO_PUBLISH:-}" = "true" ]; then
    mkdir -p data
    : > data/.no_publish
    echo "wrote data/.no_publish - the publisher will stay stopped"
fi

# a quick check that the key is actually accepted, so a stale key is caught
# here and not three hours into a queue
if [ -f .cdsapirc ] && command -v curl >/dev/null 2>&1; then
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 30 \
        -H "PRIVATE-TOKEN: $CDS_API_KEY" \
        "https://ecds.ecmwf.int/api/catalogue/v1/vocabularies/licences" || true)
    if [ "$code" = "200" ]; then
        echo "the CDS/ECDS key is accepted by the store."
    else
        echo "the store answered HTTP $code for the key - it may be stale" >&2
        rc=1
    fi
fi

exit $rc
