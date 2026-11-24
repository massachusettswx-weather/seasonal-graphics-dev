"""The narrow path for the INTERACTIVE MAPS PAGE.

The general publisher is off, and the maps page is part of the general
build - so without a path of its own the page could never be updated
again.  This copies the built page, its scripts and the map's data into
the target tree, commits them and pushes.

It is a NARROW path in the house's sense: it carries the maps page and
nothing else.  The files it writes are

    docs/maps.html                 the page
    docs/assets/js/maps.js         the page's script
    docs/assets/js/mapgl.js        the renderer
    docs/assets/js/d3.v7.min.js    the library
    docs/data/snowmap_tags.json    the model picker
    docs/data/maps_index.json      the list of runs (the archive picker)
    docs/data/maps/**              the archived runs' rasters and manifests
    docs/data/snowmap_*.json       the current runs' manifests
    docs/data/snowmap_*.png        the current runs' rasters

The page is built by build_site.py's own build_maps_page(), so the
published page is the same page the site builds - this only moves it.

usage:
    python3 tools/publish_maps_page.py --repo /workspace/devrepo --apply --push
"""
import os
import sys
import shutil
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import publish_polar_subseasonal as P   # noqa: E402  (the git machinery)

SRC_DEFAULT = os.path.join(ROOT, "docs")
TARGET_DEFAULT = "/workspace/repo"
OPERATIONAL_REPO = ("massachusettswx-weather", "seasonal-graphics")


def say(msg):
    print(msg, flush=True)


def the_files(src, prefix="docs"):
    """The files the maps page needs, and the archive with them.

    THE PATHS ARE THE TARGET'S, not the source's: the source is the
    site's own docs/ directory, and the target is the repository, so
    every path has to carry the docs/ prefix.  The first version of this
    script used the source's own paths and put a copy of the page at the
    top of the repository - where it is nothing but litter.
    """
    out = []
    for rel in ("maps.html", "assets/js/maps.js", "assets/js/mapgl.js",
                "assets/js/d3.v7.min.js", "data/snowmap_tags.json",
                "data/maps_index.json"):
        p = os.path.join(src, rel)
        if os.path.exists(p):
            out.append(rel)
    data = os.path.join(src, "data")
    if os.path.isdir(data):
        for fn in sorted(os.listdir(data)):
            if fn.startswith("snowmap_") and fn.endswith((".json", ".png")):
                out.append(os.path.join("data", fn))
        md = os.path.join(data, "maps")
        if os.path.isdir(md):
            for root, _dirs, files in os.walk(md):
                for fn in sorted(files):
                    full = os.path.join(root, fn)
                    out.append(os.path.relpath(full, src))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=SRC_DEFAULT)
    ap.add_argument("--repo", default=TARGET_DEFAULT)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--prod", action="store_true")
    ap.add_argument("--approved", action="store_true")
    ap.add_argument("--message", default=None)
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    target = os.path.abspath(args.repo)
    url = P.remote_url(target)
    repo = P.remote_repo(url)
    is_operational = repo == OPERATIONAL_REPO

    say("== the narrow path: the interactive maps page ==")
    if is_operational and not (args.prod and args.approved):
        say("   %s IS THE OPERATIONAL SITE." % url)
        say("   It is not published: it needs --prod --approved.")
        return 2
    if args.prod and not is_operational:
        say("   the remote is %s, which is not the operational site." % url)
        return 2

    files = the_files(src)
    if not files:
        say("   there is nothing to publish - the page has not been built.")
        return 2
    say("   it would put on the target:")
    for rel in files:
        say("     %s" % rel)

    if not args.apply:
        return 0

    for rel in files:
        s = os.path.join(src, rel)
        d = os.path.join(target, "docs", rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        # THE SOURCE AND THE TARGET CAN BE THE SAME TREE: the development
        # copy builds its own page and then publishes it, and the sandbox
        # mounts one tree under two paths - so the copy is skipped when
        # the two names are the same file.
        if os.path.realpath(s) == os.path.realpath(d):
            continue
        shutil.copyfile(s, d)

    # THE ARCHIVE IS A DIRECTORY: a stale run that is no longer in the
    # source must not stay on the site, or the picker would offer a run
    # whose files are gone.
    smd = os.path.join(src, "data", "maps")
    tmd = os.path.join(target, "docs", "data", "maps")
    if os.path.isdir(smd) and os.path.isdir(tmd):
        for tag in sorted(os.listdir(tmd)):
            sd = os.path.join(smd, tag)
            td = os.path.join(tmd, tag)
            if not os.path.isdir(sd):
                shutil.rmtree(td)
                continue
            for init in sorted(os.listdir(td)):
                if not os.path.isdir(os.path.join(sd, init)):
                    shutil.rmtree(os.path.join(td, init))

    say("   written: %d files" % len(files))

    if not args.push:
        return 0

    P.git(target, "add", "--", *["docs/" + f for f in files])
    msg = args.message or "the interactive maps page"
    c = P.git(target, "-c", "user.name=MCode", "-c", "user.email=mcode@local",
              "commit", "-m", msg)
    if c.returncode != 0:
        if "nothing to commit" in (c.stdout or "") + (c.stderr or ""):
            say("   the target already carries this page - nothing to do")
            return 4
        say("   the commit failed: %s" % (c.stderr or c.stdout).strip()[:300])
        return 3
    say("   committed: %s" % msg)
    token = P.token_for(target)
    p = P.push(target, url, token)
    if p.returncode != 0:
        say("   the PUSH FAILED: %s" % (p.stderr or p.stdout).strip()[:300])
        return 3
    say("   pushed to %s" % url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
