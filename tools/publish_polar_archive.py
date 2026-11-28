#!/usr/bin/env python3
"""The narrow path: the polar cap's archive of earlier runs.

THE OWNER'S WORD (25 November 2026): only the polar cap carries archived
runs.  The seasonal snowfall maps do not - the earlier run and the current
one differ by a few tenths of an inch and the comparison drew that as a
whole map of colour, which reads as "these runs are nothing alike".

WHAT THIS CARRIES:
    docs/assets/polar/archive/index.json      the list of earlier runs
    docs/assets/polar/archive/<model>/<init>/*.png    the charts themselves
    docs/assets/js/polar_archive.js           the control that reads them
    docs/spv.html                              the page, with the control on it

The charts are not redrawn: they are the drawings that were published at
the time, read back out of the git history by tools/build_polar_archive.py.

    python3 tools/publish_polar_archive.py --repo <tree> --apply --push
"""

import argparse
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import publish_polar_subseasonal as P          # noqa: E402

SRC_DEFAULT = os.path.join(ROOT, "docs")
TARGET_DEFAULT = "/workspace/repo"
OPERATIONAL_REPO = ("massachusettswx-weather", "seasonal-graphics")


def say(msg):
    print(msg, flush=True)


def add_archive_control(text):
    """The picker's control: the archived runs of the chosen model."""
    if 'id="polarArchive"' in text:
        return text
    m = re.search(r'(<select[^>]*id="polarView".*?</select>)', text, re.S)
    if not m:
        return None
    ctrl = ('\n    <label for="polarArchive">Archived run</label>\n'
            '    <select id="polarArchive" class="ctrl" disabled></select>')
    # the whole select is group 1 and is kept: dropping it would take the
    # rest of the picker with it
    return text[:m.end(1)] + ctrl + text[m.end(1):]


def add_archive_script(text, stamp):
    """The script that drives the control, after the page's own."""
    tag = '<script src="assets/js/polar_archive.js?v=%s"></script>' % stamp
    m = re.search(r'<script src="assets/js/polar_archive\.js\?v=[0-9]*"></script>',
                  text)
    if m:
        return text[:m.start()] + tag + text[m.end():]
    i = text.rfind("</body>")
    if i < 0:
        return None
    return text[:i] + tag + "\n" + text[i:]


def the_files(src):
    """The archive's own files, with the paths the TARGET uses."""
    out = []
    root = os.path.join(src, "assets", "polar", "archive")
    if os.path.isdir(root):
        for dirpath, _dirs, files in os.walk(root):
            for fn in sorted(files):
                full = os.path.join(dirpath, fn)
                out.append(os.path.relpath(full, src))
    js = os.path.join(src, "assets", "js", "polar_archive.js")
    if os.path.exists(js):
        out.append(os.path.join("assets", "js", "polar_archive.js"))
    return sorted(out)


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
    is_operational = P.remote_repo(P.remote_url(target)) == OPERATIONAL_REPO

    # ONE PUBLISH AT A TIME ON THIS TREE - the archive commits into the
    # same tree as the charts, and a commit beside another commit is a
    # collision.
    try:
        with P.publish_lock(target):
            return publish_body(src, target, args, is_operational)
    except P.LockTimeout:
        return 2


def publish_body(src, target, args, is_operational):
    if is_operational and not (args.prod and args.approved):
        say("   the operational site needs --prod --approved.  NOTHING IS CHANGED.")
        return 2

    say("== the narrow path: the polar cap's archive ==")
    index_path = os.path.join(src, "assets", "polar", "archive", "index.json")
    if not os.path.exists(index_path):
        say("   there is no archive index in %s" % src)
        say("   NOTHING IS CHANGED.  Run tools/build_polar_archive.py first.")
        return 2
    index = json.load(open(index_path))
    n = sum(len(v) for v in index.values())
    for model, runs in index.items():
        say("   %-14s %d earlier run(s): %s"
            % (model, len(runs), ", ".join(r["init"] for r in runs)))
    if not n:
        say("   the archive is empty.  NOTHING IS CHANGED.")
        return 2

    stamp = time.strftime("%Y%m%d%H%M%S")
    written = []

    # the page
    page = os.path.join(target, "docs", "spv.html")
    if not os.path.exists(page):
        say("   %s has no spv.html.  NOTHING IS CHANGED." % target)
        return 2
    text = open(page).read()
    patched = add_archive_control(text)
    if patched is None:
        say("   the page's polar picker was not found.  NOTHING IS CHANGED.")
        return 2
    patched = add_archive_script(patched, stamp)
    if patched is None:
        say("   the page has no </body>.  NOTHING IS CHANGED.")
        return 2
    if patched != text:
        if args.apply:
            open(page, "w").write(patched)
        written.append("docs/spv.html")
        say("   docs/spv.html                    the archive control")

    # the archive's files
    for rel in the_files(src):
        s = os.path.join(src, rel)
        d = os.path.join(target, "docs", rel)
        if os.path.realpath(s) == os.path.realpath(d):
            written.append("docs/%s" % rel)
            continue
        if args.apply:
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copyfile(s, d)
        written.append("docs/%s" % rel)
    say("   the archive: %d file(s) and the index" % (len(written) - 2))

    if not args.apply:
        say("   nothing was written (no --apply)")
        return 0

    msg = args.message or "the polar cap: the archive of earlier runs"
    P.commit_files(target, sorted(set(written)), msg)
    if args.push:
        url = P.remote_url(target)
        token = P.token_for(target)
        r = P.push(target, url, token)
        say("   pushed to %s (%s)" % (url, "ok" if r.returncode == 0 else
                                     "FAILED"))
        if r.returncode != 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
