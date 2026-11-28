#!/usr/bin/env bash
# Publish the site.
#
#   ./push_to_github.sh              -> the DEVELOPMENT site (the default)
#   ./push_to_github.sh --dev        -> the DEVELOPMENT site
#   ./push_to_github.sh --prod --approved
#                                   -> the OPERATIONAL site, and ONLY with the
#                                      explicit approval flag
#   ./push_to_github.sh --dev <token>
#
# NOTHING reaches the operational site without --approved.  The development
# site is where work happens; the operational site is a publication step
# that has to be asked for.
#
# There are TWO sites, and they are two repositories:
#
#   dev   the working copy - everything goes here, always
#         https://matthew22-cmd.github.io/seasonal-graphics-dev/
#   prod  the operational site - only a deliberate --prod publish reaches it
#         https://massachusettswx-weather.github.io/seasonal-graphics/
#
# The site is REBUILT for the target before the commit, so the absolute
# links (the nav tabs, the crumbs, the canonical tag, the title link), the
# "GitHub" link and the README's link all point at the right place in each
# copy.  A change is therefore never automatically put on the operational
# site: it goes to the development copy, and it reaches the operational
# site only when --prod is asked for.
#
# The token needs the "repo" scope (classic) or Contents:Read+write
# (fine-grained).  It is used once and then scrubbed from the git remote.
#
# How to get a token:
#   1. https://github.com/settings/tokens  ->  "Generate new token (classic)"
#   2. Tick the "repo" scope (and "workflow" if you want Actions).
#   3. Copy it once - GitHub only shows it at creation time.
set -euo pipefail

# ----------------------------------------------------------------------
# the target
# ----------------------------------------------------------------------
TARGET="dev"
APPROVED=0
ARGS=()
for a in "$@"; do
  case "$a" in
    --dev)        TARGET="dev" ;;
    --prod|--operational|--live) TARGET="prod" ;;
    --approved)   APPROVED=1 ;;
    *)            ARGS+=("$a") ;;
  esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
export HOME="${HOME:-/workspace/.home}"
export PYTHONPATH="${PYTHONPATH:-/workspace/.home/.local/lib/python3.11/site-packages}"

if [ "$TARGET" = "prod" ] && [ "$APPROVED" != "1" ]; then
  echo "REFUSING to publish to the operational site without approval." >&2
  echo "  The operational site is a publication step that has to be asked" >&2
  echo "  for: ./push_to_github.sh --prod --approved" >&2
  echo "  (everything else goes to the development site.)" >&2
  exit 2
fi

# ----------------------------------------------------------------------
# ONE PUBLISHER AT A TIME ON THIS TREE
#
# The narrow publishers take an exclusive lock - a file BESIDE the tree,
# /workspace/.publish-lock-<tree> - for the whole publish: read, write,
# commit, push.  The general publisher has to take it as well, or it can
# land in the middle of a narrow publish and the two can commit over each
# other.
#
# flock(1) is used here because the lock has to be held across a whole
# shell script.  It is the SAME advisory lock the Python publishers take
# with fcntl.flock, on the same file, so the two agree.
LOCKFILE="$(dirname "$HERE")/.publish-lock-$(basename "$HERE")"
if [ "${PUBLISH_LOCK_HELD:-}" != "1" ]; then
    export PUBLISH_LOCK_HELD=1
    echo ">> waiting for the publish lock: $LOCKFILE"
    exec flock -w 1800 "$LOCKFILE" "$HERE/$(basename "$0")" "$@"
fi

DEV_REPO_NAME="seasonal-graphics-dev"
if [ "$TARGET" = "prod" ]; then
  REPO="seasonal-graphics"
  OWNER="${GITHUB_OWNER:-massachusettswx-weather}"
  SITE_URL="https://massachusettswx-weather.github.io/seasonal-graphics/"
  SITE_REPO_URL="https://github.com/massachusettswx-weather/seasonal-graphics"
  SITE_DEV=0
  echo ">> target: the OPERATIONAL site (${SITE_URL})"
else
  REPO="$DEV_REPO_NAME"
  # The account that OWNS the development copy.  It is the account whose
  # token can push it, so the pipeline can publish with nobody awake.  The
  # development copy is a separate repository from the operational site
  # and is never published to it.
  OWNER="${GITHUB_DEV_OWNER:-massachusettswx-weather}"
  SITE_URL="https://${OWNER}.github.io/${DEV_REPO_NAME}/"
  SITE_REPO_URL="https://github.com/${OWNER}/${DEV_REPO_NAME}"
  SITE_DEV=1
  echo ">> target: the DEVELOPMENT site (${SITE_URL})"
fi
export SITE_URL SITE_REPO_URL SITE_DEV

# The development copy is private: it is built with a password gate in
# front of it.  The password is read from the gitignored file (or from the
# environment) and only its SHA-256 hash reaches the published pages.
if [ "$SITE_DEV" = "1" ]; then
  if [ -z "${DEV_GATE_PASSWORD:-}" ] && [ -f data/.dev_gate_password ]; then
    DEV_GATE_PASSWORD="$(tr -d '\n' < data/.dev_gate_password)"
  fi
  if [ -n "${DEV_GATE_PASSWORD:-}" ]; then
    export DEV_GATE_PASSWORD
  else
    # No plaintext password - a wiped tree loses data/.dev_gate_password.
    # The builder then falls back to the PUBLISHED gate hash, so the
    # development copy keeps exactly the password the owner already has and
    # stays private.  The gate is VERIFIED in the built pages below: a build
    # without a gate is never published.
    echo "   no gate password file - keeping the published gate hash"
  fi
fi

# The token comes from the first argument, or from data/.github_token (mode
# 600, gitignored) so it never appears in the process list.
TOKFILE="data/.github_token"
if [ ${#ARGS[@]} -gt 0 ] && [ -n "${ARGS[0]}" ]; then
  TOKEN="${ARGS[0]}"
elif [ -f "$TOKFILE" ]; then
  TOKEN="$(cat "$TOKFILE")"
else
  echo "usage: ./push_to_github.sh [--dev|--prod] [<github_token>]" >&2
  echo "   (or put the token in $TOKFILE)" >&2
  exit 1
fi
[ -n "$TOKEN" ] || { echo "no token" >&2; exit 1; }

# ----------------------------------------------------------------------
# the build, for THIS target
# ----------------------------------------------------------------------
echo ">> building the site for this target"
# The registry carries the version string that busts the browser's cache on
# every asset URL, so it is rebuilt first: a re-rendered figure then gets a
# new URL instead of being served from the cache.
python3 -u build_registry.py | sed 's/^/   /'
python3 -u build_site.py | sed 's/^/   /'

# The gate can be switched off deliberately (DEV_NO_GATE=1, or a file called
# data/.no_gate).  The build then carries no gate at all and the copy is
# readable by anyone with the link.  Say so out loud, because it is a
# deliberate act and not a broken build.
GATE_OFF=0
if [ "$SITE_DEV" = "1" ]; then
  case "$(printf '%s' "${DEV_NO_GATE:-}" | tr 'A-Z' 'a-z')" in
    1|true|yes|on) GATE_OFF=1 ;;
  esac
  [ -f data/.no_gate ] && GATE_OFF=1
fi

if [ "$SITE_DEV" = "1" ] && [ "$GATE_OFF" = "0" ]; then
  # The development copy must be private.  The gate is the block of script in
  # the head of every page that carries the password hash; if the build
  # produced a page without it, nothing is published - an open development
  # copy is worse than no development copy.
  gated=0
  for pg in docs/index.html docs/model.html docs/snow.html docs/spv.html \
            docs/maps.html; do
    [ -f "$pg" ] || continue
    if grep -qE 'var H="[a-f0-9]{64}"' "$pg"; then
      gated=$((gated+1))
    else
      echo "ERROR: $pg has no password gate - the development copy would be" >&2
      echo "       public.  Nothing is published.  Check the build." >&2
      exit 2
    fi
  done
  # The login page IS the gate: it must carry the hash to compare the typed
  # password against (it must NOT carry the redirect script - that would
  # bounce the visitor straight back out of the login page).
  if ! grep -qE '[a-f0-9]{64}' docs/login.html; then
    echo "ERROR: docs/login.html carries no password hash - the development" >&2
    echo "       copy would be public.  Nothing is published." >&2
    exit 2
  fi
  echo "   password gate present in $gated page(s) + the login page"
elif [ "$SITE_DEV" = "1" ]; then
  echo "   NOTE: the password gate is OFF - the development copy is readable"
  echo "         by anyone with the link.  (Set DEV_NO_GATE=0 and remove"
  echo "         data/.no_gate to put the gate back.)"
fi

if [ -z "$(git status --porcelain)" ]; then
  echo ">> working tree clean"
else
  git add -A
  if [ "$TARGET" = "prod" ]; then
    git -c user.name="MCode" -c user.email="mcode@local" commit -q \
      -m "Publish the operational site"
  else
    git -c user.name="MCode" -c user.email="mcode@local" commit -q \
      -m "Update the development site"
  fi
  echo ">> committed outstanding changes"
fi

echo ">> ensuring repo ${OWNER}/${REPO} exists"
# If the repo is already there, do NOT try to create it.  The create call is
# made under the TOKEN's own account, so running it against a repo the token
# cannot write to does not fail - it quietly makes a stray repository under
# that account instead, and the push then fails on the real repo.
exists=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${OWNER}/${REPO}")
if [ "$exists" = "200" ]; then
  echo "   it is already there"
else
  LOGIN=$(curl -s -H "Authorization: Bearer ${TOKEN}" \
      "https://api.github.com/user" | \
      python3 -c "import json,sys;print(json.load(sys.stdin).get('login',''))" \
      2>/dev/null || echo "")
  if [ "$LOGIN" != "$OWNER" ]; then
    echo "   the repo ${OWNER}/${REPO} is not there, and this token belongs"
    echo "   to ${LOGIN:-another account}, so it cannot create it."
    echo "   Create it by hand, or give that account write access to it"
    echo "   (Settings -> Collaborators)."
    exit 1
  fi
  code=$(curl -s -o /tmp/repo.json -w '%{http_code}' -X POST \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/user/repos" \
    -d "{\"name\":\"${REPO}\",\"private\":false,\"has_pages\":true,\"description\":\"DEVELOPMENT COPY of the seasonal forecast graphics - the operational site is massachusettswx-weather/seasonal-graphics\"}")
  if [ "$code" = "201" ]; then
    echo "   created"
  elif [ "$code" = "422" ]; then
    echo "   already exists"
  else
    echo "   WARNING: could not confirm repo creation (HTTP $code):"
    head -c 400 /tmp/repo.json; echo
  fi
fi

echo ">> pushing"
# The token is only ever in the remote URL while the push is running.  If the
# push fails - a revoked token, for instance - the remote must not be left
# holding a dead credential, so the clean URL is restored on the way out.
# The remote is ALWAYS left pointing at the DEVELOPMENT repository, even
# after an --prod publish: a bare `git push` must never be able to reach the
# operational site.
DEV_REMOTE="https://github.com/${GITHUB_DEV_OWNER:-massachusettswx-weather}/${DEV_REPO_NAME}.git"
cleanup_remote () {
    git remote set-url origin "$DEV_REMOTE" 2>/dev/null || true
}
trap cleanup_remote EXIT
git remote remove origin 2>/dev/null || true
git remote add origin "https://${TOKEN}@github.com/${OWNER}/${REPO}.git"
git push -u origin main
git remote set-url origin "$DEV_REMOTE"

echo
echo "Pushed to https://github.com/${OWNER}/${REPO}"

# GitHub Pages: the static site lives in docs/ -> publish from branch main, path /docs
# (the repo root holds the pipeline code and must NOT be the published root).
pages_set () {
  curl -s -o /tmp/pages.json -w '%{http_code}' -X "$1" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${OWNER}/${REPO}/pages" \
    -d '{"source":{"branch":"main","path":"/docs"},"build_type":"legacy"}'
}
code=$(pages_set POST)
if [ "$code" = "409" ]; then
  code=$(pages_set PUT)          # already enabled -> update the source path
fi
case "$code" in
  200|201|204) echo "Pages configured (source: main /docs)" ;;
  *) echo "NOTE: could not set Pages automatically (HTTP $code) - set it in"
     echo "      Settings -> Pages -> Source: Deploy from a branch -> main /docs."
     head -c 300 /tmp/pages.json; echo ;;
esac

echo ">> waiting for the build to finish"
url=""
for i in $(seq 1 40); do
  sleep 15
  read -r st url < <(curl -s -H "Authorization: Bearer ${TOKEN}" \
    "https://api.github.com/repos/${OWNER}/${REPO}/pages" | \
    python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('status',''),d.get('html_url',''))" 2>/dev/null || echo " ")
  if [ "$st" = "built" ] && [ -n "$url" ]; then break; fi
  printf "."
done
echo
echo "Pages status: ${st:-unknown}"

# html_url exists even when the build failed, so check the content actually serves.
echo ">> verifying the published pages"
for p in "" "model.html" "snow.html" "spv.html" "assets/css/style.css"; do
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 30 "${url}${p}")
  printf "  %-28s %s\n" "/${p}" "$c"
  [ "$c" = "200" ] || echo "  WARNING: ${p} did not serve (HTTP ${c})"
done

echo
echo "Site live at: ${url}"
