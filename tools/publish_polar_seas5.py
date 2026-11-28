"""The narrow path: the ECMWF SEAS5's polar-cap section.

WHY THIS EXISTS.  The SEAS5's polar chart is one of the site's own models,
so it used to go out with the general build - and the general build is OFF
(the owner's instruction, 22 Nov 2026).  So the SEAS5's picture, its
by-sector picture and the four registries that carry them have no way to
reach the development copy.

WHAT IT CARRIES: the SEAS5's two polar charts, the SEAS5's entry in
`docs/data/models.json` and `docs/data/models_public.json`, and the SEAS5's
entry in every inlined registry of the pages (`MODELS`, `POLARMODELS`,
`POLARSECTORS`).  Nothing else on the target changes.

WHAT IT NEVER DOES: it does not rebuild the site, it does not touch
another model's entry, and it does not push to the operational repository
without `--prod --approved`.

THE `?v=` ON THE CHART URL IS THE POINT.  It is the cache-buster: without a
new one the browser keeps serving the old picture, which is what the owner
reported as "I don't see the latest runs".  All THREE blobs carry it.

THE MACHINERY IS IMPORTED, NEVER EDITED: the GEFSv12 script runs nightly
and must not be touched.
"""
import copy
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from publish_polar_subseasonal import (            # noqa: E402
    git, remote_url, remote_repo, token_for, push, commit_files, push_to,
    inline_registry, new_version, md5, say, publish_lock, LockTimeout,
)

SRC_DEFAULT = os.path.dirname(HERE)
TARGET_DEFAULT = "/workspace/repo"
OPERATIONAL_REPO = ("massachusettswx-weather", "seasonal-graphics")

# the one product.  A constant, not a record of the last run.
MODEL_ID = "ecmwf-seas5"
NAME = "ECMWF SEAS5"
# the two pictures that make up the product
CHARTS = ("polar_cap_ecmwf-seas5.png", "polar_sectors_ecmwf-seas5.png")
# the pages that carry the main registry (the snowfall page reads the
# registry out of models.json, so it follows the registry)
REGISTRY_PAGES = ("model.html", "spv.html")
# the page that carries the polar section's own registries
POLAR_PAGE = "spv.html"


def source_entry(src):
    """The SEAS5's registry entry, taken from the source tree's own build."""
    p = os.path.join(src, "docs", "data", "models.json")
    if not os.path.exists(p):
        return None
    try:
        reg = json.load(open(p))
    except Exception:                               # noqa: BLE001
        return None
    for m in reg.get("models", []):
        if m.get("id") == MODEL_ID:
            return copy.deepcopy(m)
    return None


def patch_entry(entry, version):
    """The SEAS5's entry, with its two chart URLs brought forward."""
    if not isinstance(entry, dict):
        return None
    e = copy.deepcopy(entry)
    for key, fn in (("polar", CHARTS[0]), ("polar_sectors", CHARTS[1])):
        if isinstance(e.get(key), dict):
            e[key]["file"] = "assets/polar/%s?v=%s" % (fn, version)
    return e


def patch_inline(text, entry, version):
    """The page's own registries, with the SEAS5's entry brought forward.

    The blob is read out of the PAGE, not computed from the tree: a fresh
    clone is missing build artifacts that the pages were built with, so the
    tree's own registry can never match the pages'.  All THREE blobs are
    patched - the ?v= that busts the browser's cache is on the chart URL in
    each of them.
    """
    out = text
    for name in ("MODELS", "POLARMODELS", "POLARSECTORS"):
        got = inline_registry(out, name)
        if got is None:
            continue
        start, end, obj = got
        cur = obj.get(MODEL_ID)
        if not isinstance(cur, dict):
            continue
        if name == "MODELS":
            e = patch_entry(cur, version)
        else:
            fn = CHARTS[0] if name == "POLARMODELS" else CHARTS[1]
            e = copy.deepcopy(cur)
            if "file" in e:
                e["file"] = "assets/polar/%s?v=%s" % (fn, version)
        obj[MODEL_ID] = e
        out = out[:start] + json.dumps(obj) + out[end:]
    return out


def patch_models_json(obj, entry, version):
    """The registry file's SEAS5 entry, with its chart URLs brought forward."""
    for m in obj.get("models", []):
        if m.get("id") == MODEL_ID:
            obj["models"][obj["models"].index(m)] = patch_entry(m, version)
            return True
    return False


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=SRC_DEFAULT)
    ap.add_argument("--repo", default=TARGET_DEFAULT)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--prod", action="store_true")
    ap.add_argument("--approved", action="store_true")
    ap.add_argument("--message", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    target = os.path.abspath(args.repo)

    # ONE PUBLISH AT A TIME ON THIS TREE - the seasonal's charts and the
    # daily GEFSv12 update write into the same registry and the same pages.
    try:
        with publish_lock(target):
            return publish_body(src, target, args)
    except LockTimeout:
        return 2


def publish_body(src, target, args):
    say("== the narrow path: the ECMWF SEAS5 polar-cap section ==")
    entry = source_entry(src)
    if entry is None:
        say("   the source tree has no %s entry - NOTHING IS CHANGED."
            % MODEL_ID)
        return 2
    docs = os.path.join(target, "docs")
    charts = {}
    for fn in CHARTS:
        p = os.path.join(src, "docs", "assets", "polar", fn)
        if not os.path.exists(p):
            p = os.path.join(src, "output", "polar_cap", fn)
        if not os.path.exists(p):
            say("   the source tree has no %s - NOTHING IS CHANGED." % fn)
            return 2
        charts[fn] = p
    # the version: a fresh one, so the browser fetches the new picture
    oldver = ""
    pol = entry.get("polar") or {}
    if isinstance(pol, dict):
        oldver = (pol.get("file") or "").split("?v=")[-1]
    version = new_version(oldver)

    files = []
    pages = {}
    for fn in CHARTS:
        rel = os.path.join("docs", "assets", "polar", fn)
        files.append(rel)
    for fn in ("models.json", "models_public.json"):
        rel = os.path.join("docs", "data", fn)
        p = os.path.join(target, rel)
        if not os.path.exists(p):
            say("   the target has no %s - NOTHING IS CHANGED." % rel)
            return 2
        try:
            obj = json.load(open(p))
        except Exception:                           # noqa: BLE001
            say("   %s does not parse - NOTHING IS CHANGED." % rel)
            return 2
        if not patch_models_json(obj, entry, version):
            say("   the target's %s has no %s entry - NOTHING IS CHANGED."
                % (rel, MODEL_ID))
            return 2
        files.append(rel)
        pages[rel] = json.dumps(obj, indent=1)
    for fn in REGISTRY_PAGES:
        rel = os.path.join("docs", fn)
        p = os.path.join(target, rel)
        if not os.path.exists(p):
            continue
        t = open(p, encoding="utf-8").read()
        t2 = patch_inline(t, entry, version)
        if t2 == t:
            say("   %s carries no %s registry - it is left alone."
                % (fn, MODEL_ID))
            continue
        files.append(rel)
        pages[rel] = t2

    # ---- the check, before anything is written
    for rel, t in pages.items():
        if rel.endswith(".json"):
            obj = json.loads(t)
            got = [m for m in obj.get("models", []) if m.get("id") == MODEL_ID]
            if not got:
                say("   %s lost the entry - NOTHING IS CHANGED." % rel)
                return 2
            if ("?v=%s" % version) not in json.dumps(got[0]):
                say("   the chart URL still carries the old version -")
                say("   NOTHING IS CHANGED.")
                return 2
        else:
            for name in ("MODELS", "POLARMODELS", "POLARSECTORS"):
                got = inline_registry(t, name)
                if got is None or MODEL_ID not in got[2]:
                    continue
                if ("?v=%s" % version) not in json.dumps(got[2][MODEL_ID]):
                    say("   %s: the chart URL still carries the old version -"
                        % name)
                    say("   NOTHING IS CHANGED.")
                    return 2

    say("   it would put on the target:")
    for rel in files:
        if rel.endswith(".json"):
            say("     %-40s the %s entry" % (rel, MODEL_ID))
        else:
            say("     %-40s %s" % (rel, os.path.basename(rel)))

    if not args.apply:
        say("   (nothing is written - --apply to write it)")
        return 0

    for fn in CHARTS:
        dst = os.path.join(docs, "assets", "polar", fn)
        if os.path.realpath(charts[fn]) != os.path.realpath(dst):
            shutil.copyfile(charts[fn], dst)
    for rel, t in pages.items():
        with open(os.path.join(target, rel), "w", encoding="utf-8") as f:
            f.write(t)
    say("   written and checked: the %s entries carry ?v=%s" % (MODEL_ID,
                                                                version))

    msg = args.message or ("The ECMWF SEAS5 polar-cap section: the chart, "
                            "redrawn")
    rc = commit_files(target, files, msg)
    if rc:
        return rc

    if not args.push:
        say("   (not pushed - add --push, with the destination gate)")
        return 0
    return push_to(target, args)


if __name__ == "__main__":
    sys.exit(main())
