#!/usr/bin/env python3
"""Check the map exporter against a SYNTHETIC model.

The real fields come from the Copernicus store, which needs a key and a
queue slot.  The exporter can still be checked without either: this writes
a fake model in the same .npz convention the NOAA systems use (a rate in m
w.e. s-1, the latitudes descending), runs the exporter over it, and checks
the numbers:

  * the unit arithmetic: a rate of 1e-8 m s-1 over a 30-day month is
    0.02592 m of water = 1.02 in of water = 10.2 in of snow;
  * the anomaly against the model's own hindcast climate;
  * the mask where the model's own climate expects no snow;
  * the ladder quantisation: the byte is the position on the PUBLISHED log
    ladder, so 10 in of snow lands where 10 in lands on the colour bar;
  * the manifest, the rasters and their sizes.

    python3 tools/test_export_map.py
"""
import os
import sys
import json
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
DATA = os.path.join(ROOT, "data")
MDIR = os.path.join(DATA, "models")
TAG = "synthetic-test"

FAILS = []


def check(name, ok, detail=""):
    print("  %-52s %s%s" % (name, "ok" if ok else "FAIL",
                            ("  " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


def write_model():
    """A fake model: two systems' worth of members on a 1 degree global
    grid, and a hindcast climate that is a little drier than the
    forecast."""
    import numpy as np
    nlat, nlon = 181, 360
    lats = np.linspace(90, -90, nlat)
    lons = np.linspace(-180, 179.5, nlon)
    LAT, LON = np.meshgrid(lats, lons, indexing="ij")

    # a plausible snowfall field, in m w.e. s-1
    f = np.zeros((nlat, nlon))
    for clon, clat, amp, wid in ((-105, 47, 3.0e-8, 16), (10, 62, 3.5e-8, 18),
                                  (100, 55, 2.5e-8, 20)):
        dlon = (LON - clon + 180) % 360 - 180
        f += amp * np.exp(-(((dlon / wid) ** 2) +
                            (((LAT - clat) / (wid * 0.6)) ** 2)))

    months = ["2026-11", "2026-12", "2027-01"]
    nm = 7
    vals = np.zeros((nm, len(months), nlat, nlon))
    for m in range(nm):
        for k in range(len(months)):
            vals[m, k] = f * (1.0 + 0.02 * (m - nm / 2))
    d = os.path.join(MDIR, TAG)
    os.makedirs(d, exist_ok=True)
    np.savez_compressed(os.path.join(d, "snowfall_monthly.npz"),
                        months=np.array(months), lat=lats, lon=lons,
                        values=vals)

    # the model's own hindcast climate: a quarter drier
    clim = vals * 0.75
    np.savez_compressed(os.path.join(d, "snowfall_hindcast.npz"),
                        months=np.array(months), lat=lats, lon=lons,
                        values=clim)
    return months


def main():
    import numpy as np
    import export_snow_map as EX
    import plot_snow_models as PSM

    print("writing the synthetic model")
    write_model()

    # the registry: the exporter works from it
    reg_p = os.path.join(DATA, "models_fetched.json")
    backup = open(reg_p).read()
    state = json.loads(backup)
    state[TAG] = {"name": "SYNTHETIC TEST", "init": "2026-11",
                  "members": 7, "centre": "test", "system": "1",
                  "leads": 3}
    json.dump(state, open(reg_p, "w"), indent=1)

    tags_p = os.path.join(DATA, "snowmap_tags.json")
    tags_backup = open(tags_p).read() if os.path.exists(tags_p) else "[]"

    try:
        print("running the exporter")
        EX.main()

        man_p = os.path.join(EX.OUT, "snowmap_%s.json" % TAG)
        check("the manifest is written", os.path.exists(man_p))
        man = json.load(open(man_p))
        check("the grid is the model's own 1 degree global grid",
              man["grid"]["nlat"] == 181 and man["grid"]["nlon"] == 360,
              "%dx%d" % (man["grid"]["nlat"], man["grid"]["nlon"]))
        check("three lead months", len(man["months"]) == 3)
        check("the run total is there too", "total" in man and
              man["total"]["total"].endswith(".png"))

        # the rasters
        import PIL.Image
        tot = np.asarray(PIL.Image.open(
            os.path.join(EX.OUT, man["total"]["total"])), dtype=int)
        check("the total raster is the model's own grid",
              tot.shape == (181, 360), str(tot.shape))
        check("the rasters are 8 bit", tot.max() <= 255)

        # the unit arithmetic, from the source field
        d = os.path.join(MDIR, TAG)
        vals = np.load(os.path.join(d, "snowfall_monthly.npz"))["values"]
        months = ["2026-11", "2026-12", "2027-01"]
        ens = vals[:, 0].mean(axis=0)
        # the exporter's arithmetic for December (31 days)
        want_in = ens * 31 * 86400.0 * 1000.0 / 25.4 * PSM.SNOW_RATIO
        # the ladder position of that value
        levels = man["levels"]
        lo, hi = float(levels[0]), float(levels[-1])
        t = (np.log10(np.maximum(want_in, lo)) - np.log10(lo)) / \
            (np.log10(hi) - np.log10(lo))
        want_byte = np.round(np.clip(t, 0, 1) * 254).astype(int)
        got = np.asarray(PIL.Image.open(
            os.path.join(EX.OUT, man["months"][1]["total"])), dtype=int)
        diff = np.abs(got - want_byte)
        check("the monthly raster matches the unit arithmetic",
              diff.max() <= 1, "the biggest byte off by %d" % diff.max())

        # the anomaly: the forecast minus the model's own climate
        clim = np.load(os.path.join(d, "snowfall_hindcast.npz"))["values"]
        anom_in = (ens - clim[:, 0].mean(axis=0)) * 31 * 86400.0 * \
            1000.0 / 25.4 * PSM.SNOW_RATIO
        scale = man["anom_scale"]
        want = np.round(np.clip((anom_in + scale) / (2 * scale), 0, 1) *
                        254).astype(int)
        got = np.asarray(PIL.Image.open(
            os.path.join(EX.OUT, man["months"][1]["anom"])), dtype=int)
        # the mask: where the model's climate expects no snow
        clim_in = clim[:, 0].mean(axis=0) * 31 * 86400.0 * 1000.0 / 25.4 * \
            PSM.SNOW_RATIO
        mask = clim_in < PSM.ANOM_MASK_CLIM
        want[mask] = 255
        d2 = np.abs(got - want)
        check("the anomaly raster matches the model's own climate",
              d2.max() <= 1, "the biggest byte off by %d" % d2.max())
        check("the anomaly is masked where the model expects no snow",
              int((got == 255).sum()) > 0,
              "%d masked cells" % int((got == 255).sum()))

        # the ladder: 10 in of snow must land where 10 in lands on the bar
        v = 10.0
        t10 = (np.log10(v) - np.log10(lo)) / (np.log10(hi) - np.log10(lo))
        b10 = int(round(t10 * 254))
        check("the byte is the position on the published ladder",
              b10 == EX.quantise_total(np.array([v]), levels)[0],
              "10 in -> byte %d" % b10)

        # the sizes: the rasters must be small enough to serve
        tot_kb = sum(os.path.getsize(os.path.join(EX.OUT, f)) for f in
                     [m["total"] for m in man["months"]] +
                     [m["anom"] for m in man["months"]] +
                     [man["total"]["total"], man["total"]["anom"]]) / 1024.0
        check("the rasters for one model are under 1.5 MB",
              tot_kb < 1500, "%.0f kB" % tot_kb)
        print("  the manifest is %.0f kB" %
              (os.path.getsize(man_p) / 1024.0))
    finally:
        json.dump(json.loads(backup), open(reg_p, "w"), indent=1)
        with open(tags_p, "w") as f:
            f.write(tags_backup)
        shutil.rmtree(os.path.join(MDIR, TAG), ignore_errors=True)
        for f in os.listdir(EX.OUT):
            if f.startswith("snowmap_%s" % TAG):
                os.remove(os.path.join(EX.OUT, f))
        print("cleaned up")

    print("")
    print("FAILED: %d" % len(FAILS) if FAILS else "all the checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
