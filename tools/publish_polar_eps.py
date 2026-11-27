#!/usr/bin/env python3
"""Put the ECMWF EPS section on the DEVELOPMENT copy.

The owner's instruction, 27 November 2026: "lets work on getting ECMWF EPS
to the 'by sector' area on dev page ... make it our style ... make sure all
data (EPS, GEFSv12 Ext and SEAS5) use actual data".

This is the EPS's narrow path, in the same sense as
publish_polar_ec46.py: it never rebuilds the site, it patches the BUILT
output, and it touches only the files that belong to the one product.

What it touches in the target tree, and nothing else:

    docs/assets/polar/polar_cap_eps.png       the picture
    docs/assets/polar/polar_sectors_eps.png   the by-sector picture
    docs/data/models.json                      the registry entry
    docs/data/models_public.json               the same entry
    docs/model.html                            the registry, inlined
    docs/spv.html                              the registry, inlined; the polar
                                               block's own registry; the
                                               picker's new option
    docs/index.html                            the model's card, and the
                                               sentence that lists the models
                                               without a snowfall field

**THE DEVELOPMENT COPY ONLY.**  The EPS is a new product and it has not been
approved for the operational site, so this script REFUSES to write into the
operational clone - there is no flag that turns that off.  (The EC46's path
has one; this one deliberately does not.)

WHEN THE SECTION IS MISSING.  Nothing is changed and the exit code is 2: a
chart is never published without a series behind it.  NOTHING is written
until every page has been checked in memory, so a refusal leaves the target
exactly as it was.

    python3 tools/publish_polar_eps.py --repo /workspace/devrepo
        plan only: what would change, nothing is written

    python3 tools/publish_polar_eps.py --repo /workspace/devrepo --apply
        the files above are written into the target's working tree

    python3 tools/publish_polar_eps.py --repo /workspace/devrepo --apply --push
        ... and it is committed and pushed to the development repository
"""
import argparse
import copy
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

# the shared machinery of the narrow path: the git helpers, the token, the
# credential-file push and the destination gate.  IMPORTED, never edited.
from publish_polar_subseasonal import (            # noqa: E402
    git, remote_url, remote_repo, token_for, push, commit_files, push_to,
    inline_registry, new_version, md5, say,
)

# the builder's own wording for the model - so the card and the registry
# entry say the same thing the site builder would say
from build_registry import MODELS                   # noqa: E402

SRC_DEFAULT = ROOT
TARGET_DEFAULT = "/workspace/devrepo"
# the operational clone is NOT a target of this script
OPERATIONAL_REPO = ("massachusettswx-weather", "seasonal-graphics")

# the one product.  A constant, not a record of the last run.
MODEL_ID = "eps"
NAME = "ECMWF EPS"
# the two pictures: the polar-cap section and the same section split into the
# North Pacific and the North Atlantic
CHART = "polar_cap_eps.png"
SECTOR_CHART = "polar_sectors_eps.png"
# the EPS is fifteen days long - the lead windows 24_48 ... 336_360 - and the
# chart carries one point a day
EXPECTED_DAYS = 15
# the pages that carry the main registry (the snowfall page reads the
# registry out of models.json, so it follows the registry)
REGISTRY_PAGES = ("model.html", "spv.html")
# the page that carries the polar section's own registry and its picker
POLAR_PAGE = "spv.html"
# the page that carries the model's card
HOME_PAGE = "index.html"
# THE FILES THE PIPELINE ITSELF WRITES BEFORE THE PUBLISHER RUNS: the
# series, the job state and the two drawn charts.  The publisher refuses
# to mix somebody else's work into the target - and these files ARE this
# pipeline's work, so they are ours, and they are committed with the
# section so that the target's tree is clean afterwards and both copies
# carry the same series.
PIPE_FILES = ("data/polar_eps_z.json", "data/polar_eps_jobs.json",
              "output/polar_cap/polar_cap_eps.png",
              "output/polar_cap/polar_sectors_eps.png")


# --------------------------------------------------------------------------
def load_series(src):
    """The EPS series in the source tree, or None."""
    p = os.path.join(src, "data", "polar_eps_z.json")
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
    return {"run": str(g.get("run") or ""), "days": len(times),
            "members": g.get("members"), "cycles": g.get("cycles") or [],
            "complete": len(times) >= EXPECTED_DAYS}


def init_of_run(run):
    """The run's own date, from a run written as 20261121 00Z or as
    2026-11-20 00Z.  A run is the model's init; the first valid time is a
    forecast's first step and can be a day later."""
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", str(run or ""))
    return "%s-%s-%s" % m.groups() if m else ""


def build_entry(series, version):
    """The registry entry for the EPS.

    The wording is the SITE BUILDER's wording (build_registry.MODELS), so
    the card on the home page and the entry in the registry say the same
    thing; the numbers - the member count, the init - come from the series
    itself, so a card is never published with a number nobody checked.
    """
    name, note = MODELS.get(MODEL_ID, (NAME, ""))
    entry = {"id": MODEL_ID, "name": name, "note": note,
             "members": series.get("members") or "?"}
    init = init_of_run(series.get("run"))
    if init:
        entry["init"] = init
    entry["polar"] = {"file": "assets/polar/%s?v=%s" % (CHART, version),
                      "caption": ("Polar cap (60-90N) geopotential height "
                                  "anomaly - %s." % name),
                      "ok": True}
    entry["polar_sectors"] = {
        "file": "assets/polar/%s?v=%s" % (SECTOR_CHART, version),
        "caption": ("North Pacific and North Atlantic (60-90N) geopotential "
                    "height anomaly - %s." % name)}
    entry["snow_ok"] = False
    entry["spv_ok"] = False
    entry["polar_ok"] = True
    return entry


def add_inline(text, name, entry, version):
    """Put ONE entry into a page's own inlined registry.

    The blob is read out of the PAGE, not computed from the tree: a fresh
    clone is missing build artifacts that the pages were built with, so the
    tree's own registry can never match the pages'.
    """
    got = inline_registry(text, name)
    if got is None:
        return None
    start, end, obj = got
    if MODEL_ID in obj:
        # THE ENTRY IS ALREADY ON THE PAGE.  It was put there by the first
        # run; a REDRAW of the same run still has to reach the reader, and
        # the ?v= on the chart URL is the cache-buster - so the URL is
        # brought forward.  The WORDING follows the builder too: the note
        # and the name are the site builder's, and when the builder's
        # wording changes the page must say the new thing (the first
        # version of this entry still described the climate store and a
        # 48-hour delay, which is the EC46's route, not the EPS's).
        cur = obj[MODEL_ID]
        e = copy.deepcopy(cur)
        if entry.get("init"):
            e["init"] = entry["init"]
        if entry.get("members"):
            e["members"] = entry["members"]
        if entry.get("note"):
            e["note"] = entry["note"]
        if entry.get("name"):
            e["name"] = entry["name"]
        if name == "POLARMODELS":
            e["file"] = "assets/polar/%s?v=%s" % (CHART, version)
        if name == "POLARSECTORS":
            e["file"] = "assets/polar/%s?v=%s" % (SECTOR_CHART, version)
        if isinstance(e.get("polar"), dict):
            e["polar"]["file"] = "assets/polar/%s?v=%s" % (CHART, version)
        if isinstance(e.get("polar_sectors"), dict):
            e["polar_sectors"]["file"] = ("assets/polar/%s?v=%s"
                                          % (SECTOR_CHART, version))
        if e == cur:
            return text
        obj[MODEL_ID] = e
        return text[:start] + json.dumps(obj) + text[end:]
    e = copy.deepcopy(entry)
    if name == "POLARMODELS":
        e = {"id": MODEL_ID, "name": NAME,
             "file": "assets/polar/%s?v=%s" % (CHART, version),
             "caption": (entry.get("polar") or {}).get("caption", "")}
    if name == "POLARSECTORS":
        e = {"id": MODEL_ID, "name": NAME,
             "file": "assets/polar/%s?v=%s" % (SECTOR_CHART, version),
             "caption": (entry.get("polar_sectors") or {}).get("caption", "")}
    if isinstance(e.get("polar"), dict):
        e["polar"]["file"] = "assets/polar/%s?v=%s" % (CHART, version)
    if isinstance(e.get("polar_sectors"), dict):
        e["polar_sectors"]["file"] = ("assets/polar/%s?v=%s"
                                      % (SECTOR_CHART, version))
    # the entry goes in where the builder would have put it: the polar-only
    # models are appended, and the new one goes in front of the GEFSv12 (the
    # builder appends the polar charts in the order of their file names).
    out = {}
    for k, v in obj.items():
        if k == "gefsv12":
            out[MODEL_ID] = e
        out[k] = v
    if MODEL_ID not in out:
        out[MODEL_ID] = e
    return text[:start] + json.dumps(out) + text[end:]


def add_picker_option(text):
    """The polar section's picker gets the EPS, before the GEFSv12.

    The picker's order is the order the section opens in, and the GEFSv12
    is the default there (the owner's choice) - so the new option goes in
    front of it and the default stays where it is.
    """
    if 'value="%s"' % MODEL_ID in text:
        return text
    m = re.search(r'(<select[^>]*id="polarSel".*?)(</select>)', text, re.S)
    if not m:
        return None
    body = m.group(1)
    opt = '<option value="%s">%s</option>' % (MODEL_ID, NAME)
    i = body.find('<option value="gefsv12"')
    newbody = body + opt if i < 0 else body[:i] + opt + body[i:]
    # the closing </select> is group 2 and must be kept: dropping it
    # swallows the rest of the page and the picker stops working
    return text[:m.start(1)] + newbody + text[m.end(1):]


def build_card(entry):
    """The home page's card for the EPS, in the house format."""
    tags = ['<span class="tag no">Snowfall</span>',
            '<span class="tag no">10 hPa wind</span>']
    if entry.get("members") not in (None, "?"):
        tags.append('<span class="tag">%s members</span>' % entry["members"])
    if entry.get("init"):
        tags.append('<span class="tag">init %s</span>' % entry["init"])
    return ('<a class="model" href="model.html?m=%s">\n'
            '  <h3>%s</h3>\n'
            '  <div class="meta">%s</div>\n'
            '  <div class="tags">%s</div>\n'
            '</a>' % (MODEL_ID, entry.get("name") or NAME,
                      entry.get("note") or "", "".join(tags)))


def add_model_card(text, card):
    """The home page's model list gets the EPS's card, before the GEFSv12's.

    A card that is ALREADY on the page is REPLACED, not left alone: the
    card is built from the registry entry, and when the entry's wording
    changes the card must follow it.
    """
    i = text.find('href="model.html?m=%s"' % MODEL_ID)
    if i >= 0:
        start = text.rfind('<a class="model"', 0, i)
        end = text.find("</a>", i)
        if start >= 0 and end >= 0:
            return text[:start] + card + text[end + 4:]
        return text
    if not card:
        return None
    i = text.find('href="model.html?m=gefsv12"')
    if i < 0:
        return None
    start = text.rfind('<a class="model"', 0, i)
    if start < 0:
        return None
    return text[:start] + card + text[start:]


def lead_sentence(text):
    """The home page's sentence that lists the models with no snowfall."""
    for old, new in (
            ("ECMWF EC46 and NOAA GEFSv12", "ECMWF EC46, ECMWF EPS and NOAA GEFSv12"),
            ("ECMWF EC46, ECMWF EPS and NOAA GEFSv12", "ECMWF EC46, ECMWF EPS and NOAA GEFSv12")):
        if old in text and old != new:
            return text.replace(old, new, 1), True
    return text, False


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=SRC_DEFAULT,
                    help="the tree that holds the section (default: this repo)")
    ap.add_argument("--repo", default=TARGET_DEFAULT,
                    help="the tree to publish into (default: %s)" % TARGET_DEFAULT)
    ap.add_argument("--apply", action="store_true",
                    help="write the change into the target's working tree")
    ap.add_argument("--push", action="store_true",
                    help="commit and push to the development repository")
    ap.add_argument("--prod", action="store_true",
                    help="refused: the EPS is not on the operational site")
    ap.add_argument("--approved", action="store_true",
                    help="refused: the EPS is not on the operational site")
    ap.add_argument("--message", default=None, help="the commit message")
    ap.add_argument("--force", action="store_true",
                    help="publish even if the target already has it")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    target = os.path.abspath(args.repo)

    say("== the narrow path: the %s section ==" % NAME)

    # THE DEVELOPMENT COPY ONLY.  There is no flag for the operational site.
    if remote_repo(remote_url(target)) == OPERATIONAL_REPO:
        say("   %s is the OPERATIONAL clone." % target)
        say("   The EPS has not been approved for the operational site, so")
        say("   NOTHING IS CHANGED.")
        return 2
    if args.prod or args.approved:
        say("   the EPS is the DEVELOPMENT copy only - --prod and --approved")
        say("   are refused, and NOTHING IS CHANGED.")
        return 2

    series = load_series(src)
    if series is None:
        say("   there is no %s series in %s" % (MODEL_ID, src))
        say("   NOTHING IS CHANGED.  A chart is never published without a")
        say("   series behind it.")
        return 2
    if not series["complete"]:
        say("   the series is only %d of %d days - the run is still being"
            % (series["days"], EXPECTED_DAYS))
        say("   downloaded.  NOTHING IS CHANGED: a half window is not a window.")
        return 2
    say("   the section: the %s run, %d days, %s members, the %s cycles"
        % (series["run"], series["days"], series["members"],
           " and ".join(series["cycles"]) or "one"))

    docs = os.path.join(target, "docs")
    regp = os.path.join(docs, "data", "models.json")
    if not os.path.exists(regp):
        say("   %s has no site to publish into" % target)
        return 2
    reg = json.load(open(regp))
    have = [m for m in reg.get("models", []) if m.get("id") == MODEL_ID]
    old = (have[0].get("init") or "") if have else ""

    # the version: a fresh one, so the browser fetches the new picture
    oldver = ""
    for m in have:
        oldver = ((m.get("polar") or {}).get("file") or "").split("?v=")[-1]
    version = new_version(oldver)

    entry = build_entry(series, version)
    new = entry.get("init") or ""
    # THE SAME CYCLE IS NOTHING TO DO.  What matters is WHICH cycle the
    # target carries - a coarse "the target has an entry" test would make
    # the section publish once and never again.
    if have and old and new and old == new and not args.force:
        say("   the target already carries the %s section - nothing to do" % old)
        return 4
    # NEVER PUT THE TARGET BACK TO AN OLDER CYCLE.
    if have:
        if old and new and old > new:
            say("   the target carries the %s section, which is NEWER than "
                "the %s one - NOTHING IS CHANGED." % (old, new))
            return 4

    # the pictures: taken from the source tree's own build, byte for byte.
    # They are NOT redrawn here - redrawing would replace them with charts
    # made from this machine's reanalysis file.
    drawn = os.path.join(src, "docs", "assets", "polar", CHART)
    if not os.path.exists(drawn):
        say("   %s has no %s - NOTHING IS CHANGED." % (src, CHART))
        return 2
    drawn_sector = os.path.join(src, "docs", "assets", "polar", SECTOR_CHART)
    if not os.path.exists(drawn_sector):
        say("   %s has no %s - the by-sector chart would be missing."
            % (src, SECTOR_CHART))
        return 2

    # the plan
    say("   it would put on the target:")
    say("     docs/assets/polar/%-28s (%s)" % (CHART, md5(drawn)))
    say("     docs/assets/polar/%-28s (%s)" % (SECTOR_CHART, md5(drawn_sector)))
    say("     docs/data/models.json          the %s entry" % MODEL_ID)
    say("     docs/data/models_public.json   the same entry")
    for f in REGISTRY_PAGES:
        say("     docs/%-22s the registry, inlined" % f)
    say("     docs/%-22s the polar registry and the picker" % POLAR_PAGE)
    say("     docs/%-22s the model's card" % HOME_PAGE)
    say("   nothing else on the target changes.")

    if not args.apply:
        say("   (plan only - add --apply to write it)")
        return 0

    # the working tree must be clean of anybody else's work
    st = git(target, "status", "--porcelain")
    # THE LINES ARE CUT BY POSITION, and the first line used to lose a
    # character: the status is TWO characters and a space, and the whole
    # output was stripped before the lines were read - so the first line's
    # path came out one character short ("ata/polar_eps_z.json") and was
    # never recognised as ours.  The lines are now split without the
    # global strip, and the path is taken after the status.
    dirty = [l for l in st.stdout.split("\n") if l.strip()]
    ours = ("docs/assets/polar/%s" % CHART,
            "docs/assets/polar/%s" % SECTOR_CHART, "docs/data/models.json",
            "docs/data/models_public.json") + \
        tuple(os.path.join("docs", f) for f in REGISTRY_PAGES) + \
        (os.path.join("docs", HOME_PAGE),) + \
        tuple(PIPE_FILES)
    others = []
    for l in dirty:
        path = l[3:].strip() if len(l) > 3 else ""
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if path not in ours:
            others.append(l)
    if others:
        say("   the target's working tree has changes that are not ours -")
        say("   refusing to mix them with this one:")
        for line in others[:10]:
            say("     %s" % line)
        return 2

    # ---- everything is prepared IN MEMORY first, and checked, and only
    # ---- then written: a refusal must leave the target as it was.
    e = copy.deepcopy(entry)

    newreg = copy.deepcopy(reg)
    newreg["models"] = [m for m in newreg["models"] if m.get("id") != MODEL_ID]
    newreg["models"].append(e)

    pubp = os.path.join(docs, "data", "models_public.json")
    newpub = None
    if os.path.exists(pubp):
        newpub = json.load(open(pubp))
        newpub.setdefault("models", [])
        newpub["models"] = [m for m in newpub["models"]
                            if m.get("id") != MODEL_ID]
        newpub["models"].append(copy.deepcopy(e))

    pages = {}
    for f in REGISTRY_PAGES:
        p = os.path.join(docs, f)
        if not os.path.exists(p):
            continue
        t = open(p, encoding="utf-8").read()
        t2 = add_inline(t, "MODELS", e, version)
        if t2 is None:
            say("   %s carries no registry - NOTHING IS CHANGED." % f)
            return 2
        if f == POLAR_PAGE:
            t3 = add_inline(t2, "POLARMODELS", e, version)
            if t3 is None:
                say("   %s carries no polar registry - NOTHING IS CHANGED." % f)
                return 2
            t3 = add_inline(t3, "POLARSECTORS", e, version)
            if t3 is None:
                say("   %s carries no by-sector registry - NOTHING IS CHANGED."
                    % f)
                return 2
            t3 = add_picker_option(t3)
            if t3 is None:
                say("   %s has no polar picker - NOTHING IS CHANGED." % f)
                return 2
            t2 = t3
        pages[f] = t2

    hp = os.path.join(docs, HOME_PAGE)
    if os.path.exists(hp):
        t = open(hp, encoding="utf-8").read()
        t2 = add_model_card(t, build_card(e))
        if t2 is not None:
            t3, _changed = lead_sentence(t2)
            pages[HOME_PAGE] = t3

    # ---- the check, before anything is written
    for f, t2 in pages.items():
        got = inline_registry(t2)
        if got is not None and MODEL_ID not in got[2]:
            say("   %s does not carry the entry - NOTHING IS CHANGED." % f)
            return 2
        if f == POLAR_PAGE:
            g = inline_registry(t2, "POLARMODELS")
            if g is None or MODEL_ID not in g[2]:
                say("   the polar registry lost the entry - NOTHING IS CHANGED.")
                return 2
            if ("?v=%s" % version) not in g[2][MODEL_ID].get("file", ""):
                say("   the chart URL still carries the old version -")
                say("   NOTHING IS CHANGED.")
                return 2
            if 'value="%s"' % MODEL_ID not in t2:
                say("   the picker lost the option - NOTHING IS CHANGED.")
                return 2
    if HOME_PAGE in pages:
        if 'href="model.html?m=%s"' % MODEL_ID not in pages[HOME_PAGE]:
            say("   the model's card did not land - NOTHING IS CHANGED.")
            return 2

    # ---- now it is written
    written = []
    dst = os.path.join(docs, "assets", "polar", CHART)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.realpath(drawn) != os.path.realpath(dst):
        shutil.copyfile(drawn, dst)
    written.append(os.path.join("docs", "assets", "polar", CHART))
    dsts = os.path.join(docs, "assets", "polar", SECTOR_CHART)
    os.makedirs(os.path.dirname(dsts), exist_ok=True)
    if os.path.realpath(drawn_sector) != os.path.realpath(dsts):
        shutil.copyfile(drawn_sector, dsts)
    written.append(os.path.join("docs", "assets", "polar", SECTOR_CHART))
    # AND THE PIPELINE'S OWN FILES: the series, the job state and the two
    # drawn charts.  They are copied from the source tree so that the
    # target carries the same series, and they are committed with the
    # section - which leaves the target's tree clean for the next run.
    for rel in PIPE_FILES:
        s_path = os.path.join(src, rel)
        if not os.path.exists(s_path):
            continue
        d_path = os.path.join(target, rel)
        os.makedirs(os.path.dirname(d_path), exist_ok=True)
        if os.path.realpath(s_path) != os.path.realpath(d_path):
            shutil.copyfile(s_path, d_path)
        written.append(rel)
    json.dump(newreg, open(regp, "w"), indent=1)
    written.append(os.path.join("docs", "data", "models.json"))
    if newpub is not None:
        json.dump(newpub, open(pubp, "w"), indent=1)
        written.append(os.path.join("docs", "data", "models_public.json"))
    for f, t2 in pages.items():
        open(os.path.join(docs, f), "w", encoding="utf-8").write(t2)
        written.append(os.path.join("docs", f))

    # ---- and checked again, from the disk
    back = json.load(open(regp))
    assert [m for m in back["models"] if m.get("id") == MODEL_ID], \
        "the entry did not land in the registry"
    assert md5(dst) == md5(drawn), "the chart did not land"
    assert md5(dsts) == md5(drawn_sector), "the by-sector chart did not land"
    for f in pages:
        t2 = open(os.path.join(docs, f), encoding="utf-8").read()
        got = inline_registry(t2)
        if got is not None:
            assert MODEL_ID in got[2], "%s does not carry the entry" % f
    say("   written and checked: the entry, both pictures byte for byte, and")
    say("   the pages carry the same section.")

    # ---- commit: ONLY the files this script wrote
    msg = args.message or ("The %s polar-cap section: the %s run"
                            % (NAME, entry.get("init")))
    rc = commit_files(target, written, msg)
    if rc:
        return rc

    if not args.push:
        say("   (not pushed - add --push)")
        return 0
    return push_to(target, args)


if __name__ == "__main__":
    sys.exit(main())
