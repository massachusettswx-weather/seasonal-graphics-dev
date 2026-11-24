"""Build an ARCHIVED RUN of the map from an earlier seasonal init.

WHY: the map on the site is the CURRENT run, and every export overwrites
the last one's manifest and rasters - so there was nothing for a reader
to go back to.  This builds the same exports for an EARLIER init and
keeps them under docs/data/maps/<tag>/<init>/, where the page's
"Compare with" picker finds them.

HOW: the C3S seasonal archive still serves every past init, so the run
is fetched from the same route the pipeline uses, with the init's own
year and month.  The model's OWN hindcast climate does not change from
one init to the next - it is the model's climate, not the run's - so it
is taken from the run already on disk rather than fetched again.

The export itself is the exporter, run against a shadow tree: the same
code that draws the current run draws the archived one, so the two are
the same map by construction.

usage:  python3 tools/build_map_archive.py 2026-10 [tag ...]
"""
import os
import shutil
import subprocess
import sys
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

DATA = os.path.join(ROOT, "data")
SITE = os.path.join(ROOT, "docs")
SDATA = os.path.join(SITE, "data")
SHADOW = os.path.join(DATA, "models_shadow")
SCRATCH = os.path.join(DATA, "map_scratch")

# the centres that can be built on their own.  The ECCC's canSIPS is a
# build of three ECCC systems and the multi-model mean needs all six of
# its members, so neither is archived here: an archive entry that is
# missing a member would compare two different things.
DEFAULT_TAGS = ["ukmo-gloseas6", "cmcc-sps4", "dwd-gcfs2", "ecmwf-seas5"]


def fetch_init(tag, centre, system, leads, y, m, out):
    """The monthly snowfall for one init, from the same route the
    pipeline uses for the current one."""
    import fetch_models as FM
    req = {"originating_centre": centre, "system": system,
           "variable": "snowfall", "product_type": "monthly_mean",
           "year": y, "month": m,
           "leadtime_month": [str(k) for k in range(1, leads + 1)],
           "data_format": FM.GC}
    print("   %-16s the %04d-%02d init" % (tag, y, m), flush=True)
    # A RUN THAT IS ALREADY ON DISK IS NOT FETCHED AGAIN: the CDS's
    # queue can take hours, and a fetch that is already paid for must
    # not be paid for twice.
    if os.path.exists(out) and os.path.getsize(out) > 10000:
        print("      already fetched", flush=True)
        return True
    if not FM.retrieve("seasonal-monthly-single-levels", req, out, tries=3):
        return False
    return os.path.getsize(out) > 10000


def build_shadow(tag, grib):
    """The tree the exporter reads for the archived run.

    It holds the earlier run's forecast and the model's own climate -
    the climate is the same for every init, so it is copied rather than
    fetched.  It must NOT hold the current run's global field: the
    exporter prefers that one, and it is the current run's field.
    """
    d = os.path.join(SHADOW, tag)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    shutil.copyfile(grib, os.path.join(d, "snowfall_monthly.grib"))
    src = os.path.join(DATA, "models", tag)
    for fn in ("snowfall_hindcast.grib", "snowfall_hindcast.npz"):
        p = os.path.join(src, fn)
        if os.path.exists(p):
            shutil.copyfile(p, os.path.join(d, fn))
    return d


def run_export(tags, init):
    """The exporter, run against the shadow tree and a scratch output."""
    if os.path.isdir(SCRATCH):
        shutil.rmtree(SCRATCH)
    os.makedirs(SCRATCH, exist_ok=True)
    state_p = os.path.join(DATA, "map_archive_state.json")
    state = json.load(open(os.path.join(DATA, "models_fetched.json")))
    shadow_state = {}
    for tag in tags:
        rec = dict(state.get(tag, {}))
        rec["init"] = init
        rec["name"] = rec.get("name", tag)
        shadow_state[tag] = rec
    json.dump(shadow_state, open(state_p, "w"), indent=1)
    env = dict(os.environ)
    env["MAP_MDIR"] = SHADOW
    env["MAP_OUT"] = SCRATCH
    env["MAP_STATE"] = state_p
    r = subprocess.run([sys.executable, "-u", "export_snow_map.py"],
                       cwd=ROOT, env=env)
    if r.returncode != 0:
        print("   the export failed", flush=True)
        return False
    return True


def collect(tags, init):
    """The exported run, moved into the site's archive."""
    n = 0
    for tag in tags:
        src = os.path.join(SCRATCH, "maps", tag, init)
        if not os.path.isdir(src):
            print("   %-16s nothing was exported for this init" % tag)
            continue
        dst = os.path.join(SDATA, "maps", tag, init)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copytree(src, dst)
        n += 1
        print("   %-16s the %s run is in the archive" % (tag, init))
    return n


def main():
    init = sys.argv[1] if len(sys.argv) > 1 else "2026-10"
    tags = sys.argv[2:] or DEFAULT_TAGS
    try:
        y, m = init.split("-")
        y, m = int(y), int(m)
    except Exception:
        print("the init must be YYYY-MM")
        return 1
    import fetch_models as FM
    cfg = {t[0]: t for t in FM.SYSTEMS}
    state = json.load(open(os.path.join(DATA, "models_fetched.json")))

    ok = []
    for tag in tags:
        if tag not in cfg:
            print("   %-16s not a C3S centre - skipped" % tag)
            continue
        name, centre, system, leads = cfg[tag][1], cfg[tag][2], cfg[tag][3], cfg[tag][4]
        grib = os.path.join(DATA, "_archive_%s.grib" % tag)
        if not fetch_init(tag, centre, system, leads, y, m, grib):
            print("   %-16s the fetch failed" % tag)
            continue
        build_shadow(tag, grib)
        ok.append(tag)
    if not ok:
        print("nothing was fetched - the archive is unchanged")
        return 1
    if not run_export(ok, init):
        return 1
    n = collect(ok, init)
    # the index lists the current run and every archived one
    sys.path.insert(0, ROOT)
    import export_snow_map as E
    runs = E.write_archive_index()
    print("the archive holds %d runs (%d just built)"
          % (len(runs), n))
    for r in runs:
        if r["tag"] in ok:
            print("   %-16s %-8s %s" % (r["tag"], r["init"],
                                        "current" if r["current"] else "archived"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
