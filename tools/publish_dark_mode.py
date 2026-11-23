#!/usr/bin/env python3
"""Put ONLY the dark mode on the operational site.

The owner's instruction, 22 Nov 2026: "push this and dark mode to the ops
site".  This script carries the second half.

The dark mode is a theme on the html element: the button in the header sets
it, the browser remembers it, and the first thing the page does is read it
back, so there is no white flash on a dark screen.  It is three things per
page - the stylesheet's rules, the small script in the head that reads the
theme back, the button in the header, and the script that runs the button -
and this script carries all of them from the SOURCE tree's own build, so
the wording and the markup are the builder's, not something written by hand
here.

What it touches in the target tree, and nothing else:

    docs/assets/css/style.css   the dark theme's rules
    docs/index.html             the theme, on this page
    docs/model.html             the theme, on this page
    docs/snow.html              the theme, on this page
    docs/spv.html               the theme, on this page
    docs/enso.html              the theme, on this page

(The stylesheet's URL carries a version, so it is bumped on every page:
without that the browser would keep serving the old stylesheet and the
dark theme would never arrive.)

    python3 tools/publish_dark_mode.py --repo /workspace/repo
        plan only: what would change, nothing is written

    python3 tools/publish_dark_mode.py --repo /workspace/repo --apply
        the files above are written into the target's working tree

    python3 tools/publish_dark_mode.py --repo /workspace/repo \\
        --apply --push --prod --approved
        ... and it is committed and pushed to the operational repository
        (the destination gate: without --prod --approved the script refuses
        to push to the live site, whatever the remote says)
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from publish_polar_subseasonal import (            # noqa: E402
    git, remote_url, remote_repo, commit_files, push_to, new_version, md5,
    say,
)

SRC_DEFAULT = os.path.dirname(HERE)
TARGET_DEFAULT = "/workspace/repo"
OPERATIONAL_REPO = ("massachusettswx-weather", "seasonal-graphics")

# the pages that carry the header and the theme
PAGES = ("index.html", "model.html", "snow.html", "spv.html", "enso.html")
# the stylesheet
CSS = "assets/css/style.css"
# the stylesheet's rules are taken from the source tree's own build,
# between these two anchors
CSS_FROM = "/* DARK MODE"
CSS_TO = "*{box-sizing:border-box}"
# the header's spare space - the button goes in front of the GitHub link
SPACER = '<span class="spacer"></span>'


# --------------------------------------------------------------------------
def dark_css(src):
    """The dark theme's rules, taken from the source tree's own stylesheet."""
    p = os.path.join(src, "docs", CSS)
    if not os.path.exists(p):
        return None
    t = open(p, encoding="utf-8").read()
    i = t.find(CSS_FROM)
    j = t.find(CSS_TO)
    if i < 0 or j < 0 or j <= i:
        return None
    block = t[i:j].rstrip() + "\n"
    if ':root[data-theme="dark"]' not in block or ".themebtn" not in block:
        return None
    return block


def scripts_and_button(src):
    """The theme's three pieces, taken from the source tree's own home page.

    - the script in the head, which reads the theme back before anything
      is drawn, so a dark screen never flashes white;
    - the button in the header;
    - the script that runs the button.
    """
    p = os.path.join(src, "docs", "index.html")
    if not os.path.exists(p):
        return None
    t = open(p, encoding="utf-8").read()
    head = tail = None
    for m in re.finditer(r"<script>(.*?)</script>", t, re.S):
        body = m.group(1)
        if "localStorage.getItem('theme')" in body:
            head = m.group(0)
        elif "getElementById('themebtn')" in body:
            tail = m.group(0)
    b = re.search(r'<button class="themebtn"[^>]*>[^<]*</button>', t)
    button = b.group(0) if b else None
    if not (head and tail and button):
        return None
    return head, button, tail


def patch_page(text, head, button, tail, version):
    """The theme, on one page.  Returns the new text, or None if the page
    does not have the anchors the theme needs."""
    if 'id="themebtn"' in text:
        return text
    if "</head>" not in text or "</body>" not in text:
        return None
    if SPACER not in text:
        return None
    out = text.replace("</head>", head + "\n</head>", 1)
    out = out.replace(SPACER, SPACER + "\n  " + button, 1)
    out = out.replace("</body>", tail + "\n</body>", 1)
    # the stylesheet's version, so the browser fetches the new rules
    out = re.sub(r"(style\.css\?v=)[0-9]+", r"\g<1>%s" % version, out)
    return out


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=SRC_DEFAULT,
                    help="the tree that holds the theme (default: this repo)")
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
                    help="publish even if the target already has it")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    target = os.path.abspath(args.repo)
    is_operational = remote_repo(remote_url(target)) == OPERATIONAL_REPO

    say("== the narrow path: the dark mode ==")

    css = dark_css(src)
    if css is None:
        say("   %s has no dark theme to carry - NOTHING IS CHANGED." % src)
        return 2
    bits = scripts_and_button(src)
    if bits is None:
        say("   %s has no theme markup to carry - NOTHING IS CHANGED." % src)
        return 2
    head, button, tail = bits

    docs = os.path.join(target, "docs")
    cssp = os.path.join(docs, CSS)
    if not os.path.exists(cssp):
        say("   %s has no site to publish into" % target)
        return 2
    cur = open(cssp, encoding="utf-8").read()
    if ':root[data-theme="dark"]' in cur and not args.force:
        say("   the target already carries the dark mode - nothing to do")
        return 4

    # the stylesheet's version: the pages point at it
    oldver = ""
    m = re.search(r"style\.css\?v=([0-9]+)", cur)
    if m:
        oldver = m.group(1)
    version = new_version(oldver)

    say("   it would put on the target:")
    say("     docs/%-30s the dark theme's rules" % CSS)
    for f in PAGES:
        say("     docs/%-22s the theme: the head, the button, the script"
            % f)
    say("   nothing else on the target changes.")

    if not args.apply:
        say("   (plan only - add --apply to write it)")
        return 0

    st = git(target, "status", "--porcelain")
    dirty = [l for l in st.stdout.strip().split("\n") if l.strip()]
    ours = tuple([os.path.join("docs", CSS)] +
                 [os.path.join("docs", f) for f in PAGES])
    others = [l for l in dirty if l[3:].strip().strip('"') not in ours]
    if others and is_operational:
        say("   the target's working tree has changes that are not ours -")
        say("   refusing to mix them with this one:")
        for line in others[:10]:
            say("     %s" % line)
        return 2

    # ---- prepared in memory, checked, and only then written
    pages = {}
    for f in PAGES:
        p = os.path.join(docs, f)
        if not os.path.exists(p):
            continue
        t = open(p, encoding="utf-8").read()
        t2 = patch_page(t, head, button, tail, version)
        if t2 is None:
            say("   %s has no header anchor - NOTHING IS CHANGED." % f)
            return 2
        if 'id="themebtn"' not in t2:
            say("   the button did not land on %s - NOTHING IS CHANGED." % f)
            return 2
        if "data-theme" not in t2 or "themebtn" not in t2.split("</body>")[0]:
            say("   the theme did not land on %s - NOTHING IS CHANGED." % f)
            return 2
        pages[f] = t2
    if len(pages) != len(PAGES):
        say("   only %d of the %d pages are there - NOTHING IS CHANGED."
            % (len(pages), len(PAGES)))
        return 2

    newcss = cur.rstrip() + "\n\n" + css
    if ':root[data-theme="dark"]' not in newcss:
        say("   the rules did not land in the stylesheet - NOTHING IS CHANGED.")
        return 2

    written = []
    open(cssp, "w", encoding="utf-8").write(newcss)
    written.append(os.path.join("docs", CSS))
    for f, t2 in pages.items():
        open(os.path.join(docs, f), "w", encoding="utf-8").write(t2)
        written.append(os.path.join("docs", f))

    # ---- checked again, from the disk
    back = open(cssp, encoding="utf-8").read()
    assert ':root[data-theme="dark"]' in back, "the rules did not land"
    for f in pages:
        t2 = open(os.path.join(docs, f), encoding="utf-8").read()
        assert 'id="themebtn"' in t2, "the button did not land on %s" % f
        assert "style.css?v=%s" % version in t2, \
            "the stylesheet's version did not move on %s" % f
    say("   written and checked: the rules are in the stylesheet, every page")
    say("   carries the button and reads the theme back before it draws.")

    msg = args.message or "The dark mode: a theme that the browser remembers"
    rc = commit_files(target, written, msg)
    if rc:
        return rc

    if not args.push:
        say("   (not pushed - add --push, with the destination gate)")
        return 0
    return push_to(target, args)


if __name__ == "__main__":
    sys.exit(main())
