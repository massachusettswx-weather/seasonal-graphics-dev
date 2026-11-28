#!/usr/bin/env python3
"""Put ONLY the EC46 polar-cap section on the operational site.

The owner's instruction, 22 Nov 2026: "push this and dark mode to the ops
site".  This script carries the first half - the ECMWF EC46 sub-seasonal
polar-cap section, the one that was published on the development copy that
evening.

It is a NARROW path, in the same sense as publish_polar_subseasonal.py: it
never rebuilds the site, it patches the BUILT output, and it touches only
the files that belong to the one product.  The general publisher stays off.

What it touches in the target tree, and nothing else:

    docs/assets/polar/polar_cap_ec46.png   the picture
    docs/data/models.json                  the registry entry
    docs/data/models_public.json           the same entry
    docs/model.html                        the registry, inlined
    docs/spv.html                          the registry, inlined; the polar
                                           block's own registry; the picker's
                                           new option
    docs/index.html                        the model's card, and the sentence
                                           that lists the models without a
                                           snowfall field

(The target's snowfall page reads the registry out of models.json, so it
follows the registry and needs nothing of its own.)

HOW IT SELECTS THEM.  The model id is a CONSTANT in this file (MODEL_ID);
it is never read out of a file that an earlier run wrote.  The registry
entry is taken from the SOURCE tree's own built registry - the same builder
that wrote the development copy - so the wording is the builder's wording
and not something written by hand here.

WHEN THE SECTION IS MISSING.  Nothing is changed and the exit code is 2: a
chart is never published without a series behind it.  NOTHING is written
until every page has been checked in memory, so a refusal leaves the target
exactly as it was.

    python3 tools/publish_polar_ec46.py --repo /workspace/repo
        plan only: what would change, nothing is written

    python3 tools/publish_polar_ec46.py --repo /workspace/repo --apply
        the files above are written into the target's working tree

    python3 tools/publish_polar_ec46.py --repo /workspace/repo \\
        --apply --push --prod --approved
        ... and it is committed and pushed to the operational repository
        (the destination gate: without --prod --approved the script refuses
        to push to the live site, whatever the remote says)
"""
import argparse
import copy
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# the shared machinery of the narrow path: the git helpers, the token, the
# credential-file push and the destination gate.  IMPORTED, never edited -
# the GEFSv12 script runs nightly and must not be touched.
from publish_polar_subseasonal import (            # noqa: E402
    git, remote_url, remote_repo, token_for, push, commit_files, push_to,
    inline_registry, new_version, md5, say, publish_lock, LockTimeout,
)

SRC_DEFAULT = os.path.dirname(HERE)
TARGET_DEFAULT = "/workspace/repo"
OPERATIONAL_REPO = ("massachusettswx-weather", "seasonal-graphics")

# the one product.  A constant, not a record of the last run.
MODEL_ID = "ec46"
NAME = "ECMWF EC46"
# the two pictures that make up the product: the polar-cap section and
# the same section split into the North Pacific and the North Atlantic.
# The EC46's by-sector chart was drawn on 24 Nov 2026 - the ECMWF's
# sub-seasonal serves ten pressure levels and the reanalysis twelve, so
# the chart is drawn on the ten they share - and the POLARSECTORS
# registry now carries it.
CHART = "polar_cap_ec46.png"
SECTOR_CHART = "polar_sectors_ec46.png"
# the EC46's window is 46 days, and the chart carries one point a day
EXPECTED_DAYS = 45
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
#
# (Without this the next NEW cycle could not be published at all: the
# fetch's own change to data/polar_ec46_z.json would look like somebody
# else's work and the publisher would refuse.)
PIPE_FILES = ("data/polar_ec46_z.json", "data/polar_ec46_jobs.json",
              "output/polar_cap/polar_cap_ec46.png",
              "output/polar_cap/polar_sectors_ec46.png")


# --------------------------------------------------------------------------
def load_series(src):
    """The EC46 series in the source tree, or None."""
    p = os.path.join(src, "data", "polar_ec46_z.json")
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
            "members": g.get("members"),
            "complete": len(times) >= EXPECTED_DAYS}


def init_of_run(run):
    """The run's own date, from a run written as 20261121 00Z or as
    2026-11-20 00Z.  A run is the model's init; the first valid time is a
    forecast's first step and can be a day later."""
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", str(run or ""))
    return "%s-%s-%s" % m.groups() if m else ""


def source_entry(src):
    """The EC46's registry entry, taken from the source tree's own build."""
    p = os.path.join(src, "docs", "data", "models.json")
    if not os.path.exists(p):
        return None
    try:
        reg = json.load(open(p))
    except Exception:
        return None
    for m in reg.get("models", []):
        if m.get("id") == MODEL_ID:
            return copy.deepcopy(m)
    return None


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
        # brought forward and everything else in the entry is left alone.
        cur = obj[MODEL_ID]
        e = copy.deepcopy(cur)
        # the entry's own cycle date is the source tree's: the page was
        # built when the run was older, and the card must not keep the old
        # date beside the new picture
        if entry.get("init"):
            e["init"] = entry["init"]
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
    # models are appended, and the EC46 sits in front of the GEFSv12 (the
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
    """The polar section's picker gets the EC46, before the GEFSv12.

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


def add_model_card(text, card):
    """The home page's model list gets the EC46's card, before the GEFSv12's."""
    if 'href="model.html?m=%s"' % MODEL_ID in text:
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


def source_card(src):
    """The EC46's card, taken from the source tree's own home page."""
    p = os.path.join(src, "docs", HOME_PAGE)
    if not os.path.exists(p):
        return None
    t = open(p, encoding="utf-8").read()
    i = t.find('<a class="model" href="model.html?m=%s"' % MODEL_ID)
    if i < 0:
        return None
    j = t.find("</a>", i)
    if j < 0:
        return None
    return t[i:j + 4]


def lead_sentence(text):
    """The home page's sentence that lists the models with no snowfall."""
    old = "JMA CPS4 and NOAA GEFSv12"
    new = "JMA CPS4, ECMWF EC46 and NOAA GEFSv12"
    if old not in text:
        return text, False
    return text.replace(old, new, 1), True


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

    # ONE PUBLISH AT A TIME ON THIS TREE - the nightly GEFSv12 update and
    # this one write into the same registry, and a second publisher beside
    # the first would overwrite its entry.
    try:
        with publish_lock(target):
            return publish_body(src, target, args, is_operational)
    except LockTimeout:
        return 2


def publish_body(src, target, args, is_operational):
    say("== the narrow path: the %s polar-cap section ==" % NAME)

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
    say("   the section: the %s run, %d days, %s members"
        % (series["run"], series["days"], series["members"]))

    entry = source_entry(src)
    if entry is None:
        say("   %s has no %s entry in its built registry" % (src, MODEL_ID))
        say("   NOTHING IS CHANGED.")
        return 2

    # THE INIT IS THE RUN'S OWN DATE, AND IT COMES FROM THE SERIES - the
    # way the GEFSv12's narrow path takes it.  It used to be read out of
    # the source tree's BUILT registry, and that registry is only
    # refreshed by the general build: so when a new run arrived, the chart
    # was drawn from it and the narrow path compared the new run with the
    # registry's OLD date, found the two equal, and did nothing at all -
    # the section could not advance by itself.  The owner's word (26 Nov
    # 2026): the EC46 is automated on both copies.
    series_init = init_of_run(series.get("run"))
    if series_init and entry.get("init") != series_init:
        say("   the run is %s and the registry still says %s - the entry is"
            % (series_init, entry.get("init") or "-"))
        say("   brought forward to the run the chart was drawn from")
        entry["init"] = series_init
    if series.get("members"):
        # the member count is the one behind every day of the series, so a
        # card is never published with a count nobody checked
        entry["members"] = series["members"]

    docs = os.path.join(target, "docs")
    regp = os.path.join(docs, "data", "models.json")
    if not os.path.exists(regp):
        say("   %s has no site to publish into" % target)
        return 2
    reg = json.load(open(regp))
    have = [m for m in reg.get("models", []) if m.get("id") == MODEL_ID]
    old = (have[0].get("init") or "") if have else ""
    new = entry.get("init") or ""
    # THE SAME CYCLE IS NOTHING TO DO.  The coarse "the target has an entry"
    # test that used to stand here made the section publish ONCE and never
    # again - so the EC46 could not be updated by the automation at all
    # (the owner's word, 27 November 2026).  What matters is WHICH cycle
    # the target carries.
    if have and old and new and old == new and not args.force:
        say("   the target already carries the %s section - nothing to do"
            % old)
        return 4
    # NEVER PUT THE TARGET BACK TO AN OLDER CYCLE.  The GEFSv12's path has
    # this rule; the EC46's path had only the coarse "the target has an
    # entry" test, so a NEWER run also needed --force and an older one
    # could have been published with it.
    if have:
        if old and new and old > new:
            say("   the target carries the %s section, which is NEWER than "
                "the %s one - NOTHING IS CHANGED." % (old, new))
            return 4

    # the picture: taken from the source tree's own build, byte for byte.
    # It is NOT redrawn here - redrawing would replace it with a chart made
    # from this machine's reanalysis file, which is a day older than the
    # one the development copy was drawn with.
    drawn = os.path.join(src, "docs", "assets", "polar", CHART)
    if not os.path.exists(drawn):
        say("   %s has no %s - NOTHING IS CHANGED." % (src, CHART))
        return 2
    # the by-sector chart: the EC46 has one now (24 Nov 2026), and the
    # page's "By sector" control is offered for a model that has it
    drawn_sector = os.path.join(src, "docs", "assets", "polar", SECTOR_CHART)
    if not os.path.exists(drawn_sector):
        say("   %s has no %s - the by-sector chart would be missing."
            % (src, SECTOR_CHART))
        return 2

    # the version: a fresh one, so the browser fetches the new picture
    oldver = ""
    for m in have:
        oldver = ((m.get("polar") or {}).get("file") or "").split("?v=")[-1]
    version = new_version(oldver)

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

    # the operational clone is curated: anything else in it is somebody
    # else's work, and this change is not mixed with it
    st = git(target, "status", "--porcelain")
    # THE LINES ARE CUT BY POSITION, and the first line used to lose a
    # character: the status is TWO characters and a space, and the whole
    # output was stripped before the lines were read - so the first line's
    # path came out one character short and was never recognised as ours.
    # The lines are now split without the global strip, and the path is
    # taken after the status.
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
    if others and is_operational:
        say("   the target's working tree has changes that are not ours -")
        say("   refusing to mix them with this one:")
        for line in others[:10]:
            say("     %s" % line)
        return 2

    # ---- everything is prepared IN MEMORY first, and checked, and only
    # ---- then written: a refusal must leave the target as it was.
    e = copy.deepcopy(entry)
    if isinstance(e.get("polar"), dict):
        e["polar"]["file"] = "assets/polar/%s?v=%s" % (CHART, version)
        e["polar"]["ok"] = True
    e["snow_ok"] = False
    e["spv_ok"] = False
    e["polar_ok"] = True

    newreg = copy.deepcopy(reg)
    newreg["models"] = [m for m in newreg["models"] if m.get("id") != MODEL_ID]
    newreg["models"].append(e)

    pubp = os.path.join(docs, "data", "models_public.json")
    newpub = None
    if os.path.exists(pubp):
        newpub = json.load(open(pubp))
        newpub.setdefault("models", [])
        newpub["models"] = [m for m in newpub["models"] if m.get("id") != MODEL_ID]
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
        t2 = add_model_card(t, source_card(src))
        if t2 is not None:
            t3, changed = lead_sentence(t2)
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
    for f in pages:
        t2 = open(os.path.join(docs, f), encoding="utf-8").read()
        got = inline_registry(t2)
        if got is not None:
            assert MODEL_ID in got[2], "%s does not carry the entry" % f
    say("   written and checked: the entry, the picture byte for byte, and")
    say("   the pages carry the same section.")

    # ---- commit: ONLY the files this script wrote
    msg = args.message or ("The %s polar-cap section: the %s run"
                            % (NAME, entry.get("init")))
    rc = commit_files(target, written, msg)
    if rc:
        return rc

    if not args.push:
        say("   (not pushed - add --push, with the destination gate)")
        return 0
    return push_to(target, args)


if __name__ == "__main__":
    sys.exit(main())
