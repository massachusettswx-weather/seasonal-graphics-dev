#!/usr/bin/env python3
"""Make a SYNTHETIC model for the maps page and check the page in a browser.

The real model data comes from the Copernicus store, which needs a queue
slot and a key.  While that is being sorted out, the renderer can still be
tested end to end: this writes a fake model - a plausible snowfall field on
a 1 degree global grid, with a matching anomaly - into docs/data, and
then the page is opened in a headless browser to see that it draws, that
the timeline works, that the anomaly toggle works, and that nothing throws.

    python3 tools/test_maps_page.py            # make the fake model + test
    python3 tools/test_maps_page.py --keep     # leave the fake files behind
"""
import os
import sys
import json
import shutil
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
DATA = os.path.join(DOCS, "data")
TAG = "testmodel"
CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux/chrome"
sys.path.insert(0, ROOT)


def make_field(nlat=181, nlon=360):
    import numpy as np
    lats = np.linspace(90, -90, nlat)
    lons = np.linspace(-180, 179.5, nlon)
    LAT, LON = np.meshgrid(lats, lons, indexing="ij")
    # a plausible seasonal snowfall field: heavy over the northern
    # continents, a lobe over the Rockies, a little in the south
    f = np.zeros((nlat, nlon))
    for clon, clat, amp, wid in ((-105, 47, 26, 16), (10, 62, 30, 18),
                                  (100, 55, 22, 20), (-60, -8, 6, 12),
                                  (140, -45, 8, 10)):
        dlon = (LON - clon + 180) % 360 - 180
        f += amp * np.exp(-(((dlon / wid) ** 2) + (((LAT - clat) / (wid * 0.6)) ** 2)))
    return f


def make_model():
    import numpy as np
    from PIL import Image
    f = make_field()
    nlat, nlon = f.shape

    # the published ladder, the same way the exporter reads it
    d = json.load(open(os.path.join(ROOT, "data", "snow_depth_scale.json")))
    levels = list(reversed(list(d["levels"])))
    lo, hi = float(levels[0]), float(levels[-1])
    t = (np.log10(np.maximum(f, lo)) - np.log10(lo)) / (np.log10(hi) - np.log10(lo))
    total = np.round(np.clip(t, 0, 1) * 254).astype(np.uint8)

    # the anomaly: this model's own climate, with the field shifted
    clim = f * 0.8
    a = f - clim
    scale = 20.0
    anom = np.round(np.clip((a + scale) / (2 * scale), 0, 1) * 254).astype(np.uint8)

    months = []
    for k, label in enumerate(["November 2026", "December 2026", "January 2027"]):
        fn_t = "snowmap_%s_m%02d_total.png" % (TAG, k + 1)
        fn_a = "snowmap_%s_m%02d_anom.png" % (TAG, k + 1)
        Image.fromarray(total, mode="L").save(os.path.join(DATA, fn_t))
        Image.fromarray(anom, mode="L").save(os.path.join(DATA, fn_a))
        months.append({"ym": "2026-11", "label": label, "total": fn_t, "anom": fn_a})

    fn_t = "snowmap_%s_m00_total.png" % TAG
    fn_a = "snowmap_%s_m00_anom.png" % TAG
    Image.fromarray(total, mode="L").save(os.path.join(DATA, fn_t))
    Image.fromarray(anom, mode="L").save(os.path.join(DATA, fn_a))

    import plot_snow_models as PSM
    from plot_snow_totals import boost_saturation
    dd = json.load(open(os.path.join(ROOT, "data", "snow_depth_scale.json")))
    colors = list(reversed(list(boost_saturation(list(dd["colors"])))))
    colors[0] = "#ffffff"
    ramp = []
    RAMP = 48
    for k in range(RAMP):
        u = k * (len(colors) - 1) / float(RAMP - 1)
        i0 = int(u)
        i1 = min(i0 + 1, len(colors) - 1)
        fr = u - i0
        a = colors[i0].lstrip("#")
        b = colors[i1].lstrip("#")
        ca = [int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)]
        cb = [int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)]
        ramp.append("#" + "".join("%02x" % int(round(ca[t] + (cb[t] - ca[t]) * fr))
                                  for t in range(3)))

    man = {
        "tag": TAG, "name": "TEST MODEL", "init": "2026-11", "members": 51,
        "grid": {"lat0": 90.0, "dlat": 1.0, "nlat": nlat,
                 "lon0": -180.0, "dlon": 1.0, "nlon": nlon},
        "levels": levels, "colors": colors, "ramp": ramp,
        "anom_colors": [c for c in PSM.anom_cmap().colors],
        "anom_scale": scale,
        "months": months,
        "total": {"total": fn_t, "anom": fn_a},
    }
    with open(os.path.join(DATA, "snowmap_%s.json" % TAG), "w") as fh:
        json.dump(man, fh)
    with open(os.path.join(DATA, "snowmap_tags.json"), "w") as fh:
        json.dump([{"tag": TAG, "name": "TEST MODEL", "init": "2026-11"}], fh)
    return man


def main():
    keep = "--keep" in sys.argv
    print("making the test model")
    make_model()

    # a copy of the maps page without the development gate
    src = os.path.join(DOCS, "maps.html")
    test = os.path.join(DOCS, "_test_maps.html")
    html = open(src).read()
    open(test, "w").write(html)
    # the development gate: the page needs its key in localStorage
    import re
    m = re.search(r"var H=\"([0-9a-f]+)\"", html)
    gate = m.group(1) if m else ""

    port = 8765
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port),
                             "--directory", DOCS],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    try:
        from playwright.sync_api import sync_playwright
        errors = []
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            pg = b.new_page(viewport={"width": 1280, "height": 1000})
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errors.append(
                "PAGEERROR " + str(e) + " || " + (getattr(e, "stack", "") or "")))
            pg.on("requestfailed", lambda r: errors.append("FAILED " + r.url))
            pg.add_init_script("localStorage.setItem('devgate', %r);" % gate)
            pg.goto("http://127.0.0.1:%d/_test_maps.html" % port)
            pg.wait_for_timeout(4000)
            pg.screenshot(path="/tmp/maps_globe.png")

            # the timeline: the second month
            btns = pg.query_selector_all("#maptimeline .tlbtn")
            print("timeline buttons:", len(btns))
            if len(btns) > 2:
                btns[2].click()
                pg.wait_for_timeout(1500)
                pg.screenshot(path="/tmp/maps_month2.png")

            # the anomaly
            ab = pg.query_selector_all("#snowfield button")
            if len(ab) > 1:
                ab[1].click()
                pg.wait_for_timeout(1500)
                pg.screenshot(path="/tmp/maps_anom.png")

            # the flat view
            vb = pg.query_selector_all("#mapviews button")
            if len(vb) > 0:
                vb[0].click()
                pg.wait_for_timeout(2500)
                pg.screenshot(path="/tmp/maps_flat.png")

            # the polar view
            vb = pg.query_selector_all("#mapviews button")
            if len(vb) > 2:
                vb[2].click()
                pg.wait_for_timeout(2500)
                pg.screenshot(path="/tmp/maps_polar.png")

            # is anything actually painted on the canvas?
            painted = pg.evaluate("""() => {
              var c = document.getElementById('mapcanvas');
              if (!c) { return 'no canvas'; }
              var d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
              var n = 0, land = 0;
              for (var i = 0; i < d.length; i += 4) {
                if (d[i+3] > 0) { n++; }
                if (Math.abs(d[i] - 242) < 6 && Math.abs(d[i+1] - 237) < 6) { land++; }
              }
              return n + ' painted pixels, ' + land + ' of them land';
            }""")
            print("canvas:", painted)
            b.close()
        print("console errors:", errors if errors else "none")
    finally:
        srv.terminate()
        if not keep:
            os.remove(test)
            for f in os.listdir(DATA):
                if f.startswith("snowmap_%s" % TAG):
                    os.remove(os.path.join(DATA, f))
            print("cleaned up the test files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
