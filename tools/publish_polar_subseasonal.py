#!/usr/bin/env python3
"""Put ONLY the daily GEFSv12 sub-seasonal update on the operational site.

The general publisher is stopped (the owner's instruction, 20 Nov 2026) and
it must stay stopped: it would carry the whole development site - the new
map page, the three-month product, the new stylesheet - to the live site.
The one product on the live site that changes every day is the daily
GEFSv12 sub-seasonal panel, and that is what this script carries.

So this is the NARROW path: one product, two pictures, one registry entry.
It never rebuilds the site.  It copies the two GEFSv12 charts and patches
the one registry entry that names them, so the live site's pages, CSS and
everything else stay exactly as they are.

What it touches in the target tree, and nothing else:

    docs/assets/polar/polar_cap_gefsv12.png
    docs/assets/polar/polar_sectors_gefsv12.png
    docs/data/models.json          the one registry entry
    docs/data/models_public.json   the same entry
    docs/model.html                the registry, inlined
    docs/snow.html                 the registry, inlined
    docs/spv.html                  the registry, inlined

HOW IT SELECTS THEM.  The model id is a CONSTANT in this file (MODEL_ID);
it is never read out of a file that an earlier run wrote.  Only the two
charts whose names carry that id are copied, and only the one registry
entry with that id is patched.  Every other model, chart and page is left
byte for byte as it was.

WHEN THE UPDATE IS MISSING.  Nothing is changed and the exit code is 2: a
chart is never published without a series behind it, and a missing update
never becomes an empty one.

WHEN THE OPERATIONAL REPOSITORY CANNOT BE REACHED.  The push fails loudly
(exit code 3), the commit stays local, and the live site keeps serving the
previous cycle.  Nothing is half published.

    python3 tools/publish_polar_subseasonal.py --repo /workspace/repo
        plan only: what would change, nothing is written

    python3 tools/publish_polar_subseasonal.py --repo /workspace/repo --apply
        the seven files above are written into the target's working tree

    python3 tools/publish_polar_subseasonal.py --repo /workspace/repo \\
        --apply --push --prod --approved
        ... and it is committed and pushed to the operational repository
        (the destination gate: without --prod --approved the script refuses
        to push to the live site, whatever the remote says)
"""
import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DEFAULT = os.path.dirname(HERE)
TARGET_DEFAULT = "/workspace/repo"

# the one product.  A constant, not a record of the last run.
MODEL_ID = "gefsv12"
LABEL = "NOAA GEFSv12 (35-day extended)"
# the two pictures that make up the product
CHARTS = ("polar_cap_gefsv12.png", "polar_sectors_gefsv12.png")
# the seven files the product is carried in
FILES = ("docs/assets/polar/polar_cap_gefsv12.png",
         "docs/assets/polar/polar_sectors_gefsv12.png",
         "docs/data/models.json",
         "docs/data/models_public.json",
         "docs/model.html", "docs/snow.html", "docs/spv.html")
# the live site: a push to it needs the approval flags
OPERATIONAL_MARK = "github.com/massachusettswx-weather/seasonal-graphics"
# the GEFSv12's 00Z cycle carries 35 days (f012 to f840).  The fetcher writes
# the series into the cache after EVERY lead, so a series that is still being
# downloaded is on disk and is SHORTER than this.  A partial series is never
# published: the panel would show half a season.
EXPECTED_DAYS = 35


def say(msg):
    print(msg)


def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


# --------------------------------------------------------------------------
# the update itself
# --------------------------------------------------------------------------
def load_series(src):
    """The GEFSv12 series in the source tree, or None if there is none."""
    p = os.path.join(src, "data", "polar_model_z.json")
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p))
    except Exception:
        return None
    g = d.get(MODEL_ID)
    if not isinstance(g, dict):
        return None
    times = g.get("times") or []
    if not times:
        return None
    run = str(g.get("run") or "")
    init = "%s-%s-%s" % (run[0:4], run[4:6], run[6:8]) if len(run) >= 8 else ""
    if len(init) != 10:
        init = str(times[0])[:10]
    if len(times) < EXPECTED_DAYS:
        # the series is still being downloaded - the fetcher writes it after
        # every lead, so a short one is a half-downloaded run
        return {"run": run, "init": init, "days": len(times),
                "members": g.get("members"), "complete": False}
    return {"run": run, "init": init, "days": len(times),
            "members": g.get("members"), "complete": True}


def render(src, stage):
    """Draw the two charts from the source tree's own data."""
    if src not in sys.path:
        sys.path.insert(0, src)
    import plot_polar_cap          # noqa: E402
    import plot_polar_sectors      # noqa: E402
    plot_polar_cap.OUT = stage
    plot_polar_sectors.OUT = stage
    plot_polar_cap.main(MODEL_ID, LABEL)
    plot_polar_sectors.main(MODEL_ID, LABEL)
    out = []
    for fn in CHARTS:
        p = os.path.join(stage, fn)
        if not os.path.exists(p):
            return None
        out.append(p)
    return out


# --------------------------------------------------------------------------
# the target's registry
# --------------------------------------------------------------------------
def public_map(reg):
    """The browser's map of the registry (build_site.py's own rule)."""
    out = {}
    for m in reg.get("models", []):
        p = dict(m)
        p["snow_ok"] = m.get("snow_ok", False)
        p["spv_ok"] = m.get("spv_ok", False)
        p["polar_ok"] = m.get("polar_ok", False)
        out[m["id"]] = p
    return out


def target_build_site(target):
    """The TARGET's own build_site.py, loaded from its own path.

    The pages were written by that file, and its `load_registry()` adds the
    "ok" flags by looking at the files that are actually there.  The blob
    that is inlined in the pages is therefore that file's output, and only
    that file can reproduce it.  A copy of the rule in this script would
    drift from the pages the moment the rule changed.
    """
    import importlib.util
    p = os.path.join(target, "build_site.py")
    if not os.path.exists(p):
        return None
    spec = importlib.util.spec_from_file_location("target_build_site", p)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, target)
    try:
        spec.loader.exec_module(mod)
    finally:
        if sys.path and sys.path[0] == target:
            sys.path.pop(0)
    return mod


def entry_of(reg):
    for m in reg.get("models", []):
        if m.get("id") == MODEL_ID:
            return m
    return None


def patched_registry(reg, init, version):
    """The registry with the ONE GEFSv12 entry brought forward."""
    new = copy.deepcopy(reg)
    entry = entry_of(new)
    if entry is None:
        return None
    entry["init"] = init
    for key, fn in (("polar", "polar_cap_gefsv12.png"),
                    ("polar_sectors", "polar_sectors_gefsv12.png")):
        if key in entry and isinstance(entry[key], dict):
            entry[key]["file"] = "assets/polar/%s?v=%s" % (fn, version)
    return new


def new_version(old):
    v = time.strftime("%Y%m%d%H%M%S")
    if v == old:
        v = str(int(old) + 1)
    return v


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------
def git(repo, *args, **kw):
    return subprocess.run(["git"] + list(args), cwd=repo,
                          capture_output=True, text=True, **kw)


def remote_url(repo):
    r = git(repo, "remote", "get-url", "origin")
    return r.stdout.strip() if r.returncode == 0 else ""


def token_for(repo):
    """The GitHub token: the file first, then the environment."""
    for p in (os.path.join(repo, "data", ".github_token"),
              os.path.join(SRC_DEFAULT, "data", ".github_token")):
        if os.path.exists(p):
            t = open(p).read().strip()
            if t:
                return t
    return (os.environ.get("GITHUB_TOKEN") or "").strip()


def push(repo, url, token):
    """Push to the remote, with the token never on the command line.

    The token is written to a credential file that only exists while the
    push runs, and the file is removed afterwards - so a bare `git push`
    can never reach the live site with a credential in it, and the token
    is never visible in the process list.
    """
    if "github.com" not in url or not token:
        return git(repo, "push", "origin", "HEAD")
    cred = os.path.join(repo, ".git", "gh_cred")
    with open(cred, "w") as f:
        f.write("https://x-access-token:%s@github.com\n" % token)
    os.chmod(cred, 0o600)
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            ["git", "-c", "credential.helper=store --file=%s" % cred,
             "push", "origin", "HEAD"],
            cwd=repo, capture_output=True, text=True, env=env)
    finally:
        try:
            os.remove(cred)
        except OSError:
            pass


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=SRC_DEFAULT,
                    help="the tree that holds the update (default: this repo)")
    ap.add_argument("--repo", default=TARGET_DEFAULT,
                    help="the tree to publish into (default: %s)" % TARGET_DEFAULT)
    ap.add_argument("--apply", action="store_true",
                    help="write the change into the target's working tree")
    ap.add_argument("--push", action="store_true",
                    help="commit and push (needs the destination gate)")
    ap.add_argument("--prod", action="store_true",
                    help="the target is the operational site")
    ap.add_argument("--approved", action="store_true",
                    help="the owner's approval for the operational site")
    ap.add_argument("--message", default=None, help="the commit message")
    ap.add_argument("--force", action="store_true",
                    help="publish even if the target already has this cycle")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    target = os.path.abspath(args.repo)
    # the operational site is the one whose remote says so - the gate is on
    # the DESTINATION, not on a flag
    is_operational = OPERATIONAL_MARK in remote_url(target)

    say("== the narrow path: the daily %s update ==" % MODEL_ID)

    # 1. is there an update at all?
    series = load_series(src)
    if series is None:
        say("   there is no %s series in %s" % (MODEL_ID, src))
        say("   NOTHING IS CHANGED.  A chart is never published without a")
        say("   series behind it.")
        return 2
    say("   the update: the %s run, %d days, %s members"
        % (series["run"], series["days"], series["members"]))
    if not series["complete"]:
        say("   the series is only %d of %d days - the run is still being"
            % (series["days"], EXPECTED_DAYS))
        say("   downloaded.  NOTHING IS CHANGED: a half season is not a season.")
        return 2

    regp = os.path.join(target, "docs", "data", "models.json")
    if not os.path.exists(regp):
        say("   %s has no site to publish into" % target)
        return 2
    reg = json.load(open(regp))
    entry = entry_of(reg)
    if entry is None:
        say("   the target's registry has no %s entry" % MODEL_ID)
        say("   NOTHING IS CHANGED.")
        return 2
    old_init = entry.get("init")
    # A CHANGE THAT WAS WRITTEN BUT NEVER COMMITTED IS NOT "ALREADY
    # THERE".  The working tree can carry a cycle that never reached the
    # server - a run that was interrupted between the write and the commit
    # leaves exactly that - so the check has to look at the files, not
    # only at the registry.
    stranded = bool(git(target, "status", "--porcelain", "--", *FILES)
                    .stdout.strip())
    if old_init == series["init"] and not args.force and not stranded:
        say("   the target already carries the %s cycle - nothing to do"
            % old_init)
        return 0
    if stranded:
        say("   the target's working tree holds a change that was never"
            " committed - it is finished and pushed now")
    if old_init and old_init > series["init"] and not args.force:
        say("   the target carries %s, which is NEWER than the update (%s)."
            % (old_init, series["init"]))
        say("   NOTHING IS CHANGED - the live site is never put back.")
        return 2

    # 2. draw the two charts from the source tree's own data
    stage = tempfile.mkdtemp(prefix="gefs_publish_")
    try:
        drawn = render(src, stage)
        if drawn is None:
            say("   the charts could not be drawn - NOTHING IS CHANGED.")
            return 2

        # 3. the plan: the seven files, and nothing else
        oldver = ""
        for key in ("polar", "polar_sectors"):
            f = (entry.get(key) or {}).get("file") or ""
            if "?v=" in f:
                oldver = f.split("?v=")[-1]
                break
        version = new_version(oldver)
        new_reg = patched_registry(reg, series["init"], version)

        # the blob the pages carry is the TARGET's own builder's output: its
        # load_registry() adds the "ok" flags from the files that are really
        # there, so only the target's own code can reproduce it.
        bs = target_build_site(target)
        if bs is not None:
            old_blob = json.dumps(bs.public_map(bs.load_registry()))
        else:
            old_blob = json.dumps(public_map(reg))

        docs = os.path.join(target, "docs")
        html_files = sorted(f for f in os.listdir(docs) if f.endswith(".html"))
        hits = []
        for f in html_files:
            t = open(os.path.join(docs, f), encoding="utf-8").read()
            if old_blob in t:
                hits.append(f)
        if not hits:
            say("   the target's pages were not built from its own registry,")
            say("   so they cannot be patched safely - NOTHING IS CHANGED.")
            return 2

        say("   it would put on the target:")
        say("     docs/assets/polar/polar_cap_gefsv12.png      (%s)"
            % md5(drawn[0]))
        say("     docs/assets/polar/polar_sectors_gefsv12.png  (%s)"
            % md5(drawn[1]))
        say("     docs/data/models.json          the %s entry: init %s -> %s"
            % (MODEL_ID, old_init, series["init"]))
        say("     docs/data/models_public.json   the same entry")
        for f in hits:
            say("     docs/%-22s the registry, inlined" % f)
        say("   nothing else on the target changes.")

        if not args.apply:
            say("   (plan only - add --apply to write it)")
            return 0

        # 4. the files this run would write
        written = []
        for p in drawn:
            written.append(os.path.join("docs", "assets", "polar",
                                        os.path.basename(p)))
        written.append(os.path.join("docs", "data", "models.json"))
        written.append(os.path.join("docs", "data", "models_public.json"))
        written.extend(os.path.join("docs", f) for f in hits)

        # the target's working tree: somebody else's work in it means no.
        # The operational clone must be clean of anything else; the
        # development copy is busy all the time, so there only the files
        # that are NOT ours must be untouched.
        st = git(target, "status", "--porcelain")
        dirty = [l for l in st.stdout.strip().split("\n") if l.strip()]
        others = [l for l in dirty
                  if not any(l[3:].strip().strip('"') == w for w in FILES)]
        if others:
            say("   the target's working tree has changes that are not ours -")
            say("   refusing to mix them with this update:")
            for line in others[:10]:
                say("     %s" % line)
            return 2

        for p in drawn:
            shutil.copyfile(p, os.path.join(target, os.path.join(
                "docs", "assets", "polar", os.path.basename(p))))
        json.dump(new_reg, open(regp, "w"), indent=1)
        pub = {"models": []}
        for m in new_reg["models"]:
            pub["models"].append(dict(m))
        json.dump(pub, open(os.path.join(docs, "data", "models_public.json"),
                            "w"), indent=1)
        if bs is not None:
            new_blob = json.dumps(bs.public_map(bs.load_registry()))
        else:
            new_blob = json.dumps(public_map(new_reg))
        for f in hits:
            p = os.path.join(docs, f)
            t = open(p, encoding="utf-8").read()
            t = t.replace(old_blob, new_blob)
            open(p, "w", encoding="utf-8").write(t)

        # 5. check what was written
        back = json.load(open(regp))
        bentry = entry_of(back)
        assert bentry["init"] == series["init"], "the init did not land"
        for p in drawn:
            q = os.path.join(docs, "assets", "polar", os.path.basename(p))
            assert md5(q) == md5(p), "the chart did not land"
        say("   written and checked: init=%s, both charts byte for byte."
            % series["init"])

        # 6. commit - ONLY the files this script wrote.  The development
        # copy's tree is busy all the time, and a `git add -A` there would
        # carry whatever the workers happened to be writing.
        msg = args.message or ("The daily %s sub-seasonal update: the %s cycle"
                                % (MODEL_ID, series["init"]))
        git(target, "add", "--", *written)
        # the identity is given here, not taken from the machine: a clone
        # that has never committed anything has no user.name, and the
        # commit would fail with "Author identity unknown"
        c = git(target, "-c", "user.name=MCode", "-c", "user.email=mcode@local",
                "commit", "-m", msg)
        if c.returncode != 0:
            say("   the commit failed:")
            say("   %s" % (c.stderr or c.stdout).strip()[:400])
            return 2
        say("   committed: %s" % msg.split("\n")[0])

        if not args.push:
            say("   (not pushed - add --push, with the destination gate)")
            return 0

        # 7. the gate: the operational site needs the owner's approval
        url = remote_url(target)
        if OPERATIONAL_MARK in url and not (args.prod and args.approved):
            say("   %s IS THE OPERATIONAL SITE." % url)
            say("   It is not published: it needs --prod --approved.")
            return 2
        if args.prod and OPERATIONAL_MARK not in url:
            say("   the remote is %s, which is not the operational site." % url)
            return 2
        token = token_for(target)
        if "github.com" in url and not token:
            say("   there is no GitHub token - nothing is pushed.")
            say("   the commit stays local; the site keeps the old cycle.")
            return 3
        ls = git(target, "ls-remote", "origin")
        if ls.returncode != 0:
            say("   the repository cannot be reached:")
            say("   %s" % (ls.stderr or ls.stdout).strip()[:400])
            say("   the commit stays local; the site keeps the old cycle.")
            return 3
        p = push(target, url, token)
        if p.returncode != 0:
            say("   the PUSH FAILED:")
            say("   %s" % (p.stderr or p.stdout).strip()[:400])
            say("   the commit stays local; the site keeps the old cycle.")
            return 3
        say("   pushed to %s" % url)
        return 0
    finally:
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
