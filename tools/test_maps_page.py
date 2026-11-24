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
import glob
import json
import shutil
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
DATA = os.path.join(DOCS, "data")
TAG = "testmodel"
# the tag the page OPENS on: the multi-model, whose manifest the test
# stands in for - so the archived run has to be the multi-model's
ATAG = "c3s-multi"
# The browser: playwright's own download, wherever this sandbox put it.
# The path is not hard-coded - a rebuild of the sandbox moves it, and a
# test that cannot find the browser is not a test of the page.
CHROME = None
for _c in glob.glob("/root/.cache/ms-playwright/chromium-*/chrome-linux/chrome"):
    CHROME = _c
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
        entry = {"ym": "2026-11", "label": label, "total": fn_t, "anom": fn_a}
        # THE THREE-MONTH WINDOW: only the first month of this little run
        # has a full window (NDJ), exactly as the house's own four sit
        # at the start of a six-month run.
        if k == 0:
            fn_3t = "snowmap_%s_m%02d_avg3_total.png" % (TAG, k + 1)
            fn_3a = "snowmap_%s_m%02d_avg3_anom.png" % (TAG, k + 1)
            Image.fromarray(total, mode="L").save(os.path.join(DATA, fn_3t))
            Image.fromarray(anom, mode="L").save(os.path.join(DATA, fn_3a))
            entry["avg3_total"] = fn_3t
            entry["avg3_anom"] = fn_3a
            entry["avg3_label"] = "NDJ"
            entry["avg3_months"] = 3
        months.append(entry)

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

    # AN EARLIER RUN OF THE SAME MODEL, in the archive: the page's
    # "Compare with" picker reads docs/data/maps_index.json, and the
    # archived run's files live under docs/data/maps/<tag>/<init>/.
    adir = os.path.join(DATA, "maps", ATAG, "2026-10")
    os.makedirs(adir, exist_ok=True)
    import numpy as np
    from PIL import Image
    # the same field, a little different: the difference must not be zero
    f2 = make_field() * 0.85 + 2.0
    t2 = np.round(np.clip((np.log10(np.maximum(f2, lo)) - np.log10(lo)) /
                          (np.log10(hi) - np.log10(lo)), 0, 1) * 254).astype(np.uint8)
    a2 = np.round(np.clip(((f2 - clim) + scale) / (2 * scale), 0, 1) * 254).astype(np.uint8)
    for k in range(3):
        Image.fromarray(t2, mode="L").save(
            os.path.join(adir, "snowmap_%s_m%02d_total.png" % (ATAG, k + 1)))
        Image.fromarray(a2, mode="L").save(
            os.path.join(adir, "snowmap_%s_m%02d_anom.png" % (ATAG, k + 1)))
    aman = json.loads(json.dumps(man))
    aman["init"] = "2026-10"
    aman["archived"] = True
    rel = "maps/%s/2026-10" % ATAG
    for entry in aman["months"]:
        for k in ("total", "anom"):
            if entry.get(k):
                entry[k] = "%s/%s" % (rel, entry[k].replace("snowmap_%s_" % TAG,
                                                           "snowmap_%s_" % ATAG))
    with open(os.path.join(adir, "snowmap_%s.json" % ATAG), "w") as fh:
        json.dump(aman, fh)
    # the index of runs: the current one and the archived one
    idx_p = os.path.join(DATA, "maps_index.json")
    if os.path.exists(idx_p):
        shutil.copyfile(idx_p, os.path.join(DATA, "maps_index.json.bak"))
    with open(idx_p, "w") as fh:
        json.dump([{"tag": ATAG, "init": "2026-11", "name": "TEST MODEL",
                    "current": True, "manifest": "snowmap_%s.json" % ATAG},
                   {"tag": ATAG, "init": "2026-10", "name": "TEST MODEL",
                    "current": False,
                    "manifest": "maps/%s/2026-10/snowmap_%s.json"
                               % (ATAG, ATAG)}], fh)

    # A SECOND entry that points at the same rasters, under the tag the
    # page is supposed to open on.  It is deliberately NOT first in the
    # index, so the test proves the page picks the multi-model by NAME
    # and not merely because it happens to be the first entry.
    #
    # The REAL multi-model manifest is set aside and put back afterwards:
    # this file lives beside it in the published data directory.
    real_multi = os.path.join(DATA, "snowmap_c3s-multi.json")
    if os.path.exists(real_multi):
        shutil.copyfile(real_multi, os.path.join(DATA, "snowmap_c3s-multi.json.bak"))

    man2 = dict(man)
    man2["tag"] = "c3s-multi"
    man2["name"] = "C3S Multi-Model Mean"
    with open(real_multi, "w") as fh:
        json.dump(man2, fh)

    # the index the page reads: the REAL one is kept, so the page is not
    # left pointing at a model that is not there
    tags = os.path.join(DATA, "snowmap_tags.json")
    if os.path.exists(tags):
        shutil.copyfile(tags, os.path.join(DATA, "snowmap_tags.json.bak"))
    with open(tags, "w") as fh:
        json.dump([{"tag": TAG, "name": "TEST MODEL", "init": "2026-11"},
                   {"tag": "c3s-multi", "name": "C3S Multi-Model Mean",
                    "init": "2026-11"}], fh)
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
    # A THREADED server: python's own http.server handles ONE request at
    # a time, and the page asks for a dozen rasters at once, so the
    # listen backlog overflowed and the browser recorded the overflow as
    # ERR_CONNECTION_REFUSED - a fault in the test harness, not on the
    # page.
    _srv_code = (
        "import http.server, socketserver, functools, sys\n"
        "class H(http.server.SimpleHTTPRequestHandler):\n"
        "    def log_message(self, *a): pass\n"
        "class S(socketserver.ThreadingMixIn, http.server.HTTPServer):\n"
        "    daemon_threads = True\n"
        "    allow_reuse_address = True\n"
        "S(('127.0.0.1', int(sys.argv[1])), "
        "functools.partial(H, directory=sys.argv[2])).serve_forever()\n"
    )
    srv = subprocess.Popen([sys.executable, "-c", _srv_code, str(port),
                             DOCS],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    try:
        from playwright.sync_api import sync_playwright
        errors = []
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"]) if CHROME \
                else p.chromium.launch(args=["--no-sandbox"])
            pg = b.new_page(viewport={"width": 1280, "height": 1000})
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errors.append(
                "PAGEERROR " + str(e) + " || " + (getattr(e, "stack", "") or "")))
            pg.on("requestfailed", lambda r: errors.append("FAILED " + r.url))
            pg.add_init_script("localStorage.setItem('devgate', %r);" % gate)
            pg.goto("http://127.0.0.1:%d/_test_maps.html" % port)
            pg.wait_for_timeout(4000)
            pg.screenshot(path="/tmp/maps_globe.png")

            # THE PAGE OPENS ON THE MULTI-MODEL MEAN.  The index in this
            # test has the test model FIRST, so the page can only land on
            # the multi-model by asking for it by name.
            sel = pg.evaluate("() => { var s = document.querySelector('#snowModel');"
                              " return s ? s.value : ''; }")
            print("the page opens on:", sel)
            if sel != "c3s-multi":
                print("   FAIL: the page should open on the C3S Multi-Model Mean")
                errors.append("the page opened on %r, not the multi-model" % sel)
            else:
                print("   ok")

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

            # the globe view
            vb = pg.query_selector_all("#mapviews button")
            if len(vb) > 1:
                vb[1].click()
                pg.wait_for_timeout(2500)
                pg.screenshot(path="/tmp/maps_globe.png")

            # the polar SECTION's sectors must NOT be painted on the
            # snowfall map - they belong to the stratosphere page
            furniture = pg.evaluate(
                "() => document.querySelectorAll("
                "'#mapsvg .sector, #mapsvg .sectorlabel, #mapsvg .capedge').length")
            print("polar-section furniture on the map:", furniture)

            # the zoom: the buttons, the label, and the picture changing
            before = pg.evaluate("() => document.querySelector('.mapctl .zlabel').textContent")
            pg.query_selector('.mapctl button[data-z="in"]').click()
            pg.wait_for_timeout(1500)
            after = pg.evaluate("() => document.querySelector('.mapctl .zlabel').textContent")
            print("zoom:", before, "->", after)
            pg.screenshot(path="/tmp/maps_zoom.png")
            pg.query_selector('.mapctl button[data-z="reset"]').click()
            pg.wait_for_timeout(1200)
            reset = pg.evaluate("() => document.querySelector('.mapctl .zlabel').textContent")
            print("after reset:", reset)

            # THE THREE-MONTH WINDOW: the switch must move the map onto a
            # month that HAS a window, dim the ones that have not, and the
            # caption must name the window.
            pg.query_selector('#snowwindow button[data-window="3"]').click()
            pg.wait_for_timeout(2000)
            win3 = pg.evaluate("""() => {
              var st = window.__maps;
              var btns = document.querySelectorAll('#maptimeline .tlbtn');
              var off = 0, totalOff = 0;
              for (var i = 0; i < btns.length; i++) {
                if (btns[i].disabled) { off++; }
              }
              totalOff = btns.length && btns[0].disabled ? 1 : 0;
              var cap = (document.querySelector('#maplegend') || {}).textContent || '';
              return {win3: st.win3, month: st.month, dimmed: off,
                      totalDimmed: totalOff, cap: cap};
            }""")
            print("the three-month window:", win3["win3"],
                  "month", win3["month"],
                  "| dimmed", win3["dimmed"], "of which the run total",
                  win3["totalDimmed"])
            print("   the caption names the window:",
                  "NDJ" in win3["cap"])
            print("   FAIL: the window switch did not move onto a month"
                  if not (win3["win3"] and win3["month"] >= 0 and
                          "NDJ" in win3["cap"]) else "   ok")
            pg.query_selector('#snowwindow button[data-window="1"]').click()
            pg.wait_for_timeout(1200)

            # THE GLOBE'S TILT ALONE (the owner's choice, 22 Nov 2026).
            # The flat map pans and does not turn on the screen, and the
            # tilt button belongs to the globe alone.
            pg.query_selector_all("#mapviews button")[1].click()
            pg.wait_for_timeout(1800)
            tilt = pg.evaluate("""() => {
              var st = window.__maps;
              var b = document.querySelector(".mapctl [data-z='tilt']");
              var vis = b ? (b.offsetParent !== null || b.style.display !== 'none')
                          : false;
              return {has: !!b, vis: vis, mode: st ? !!st.tiltMode : null,
                      tilt: st ? st.tilt : null,
                      hasTurn: st ? ('turn' in st) : null};
            }""")
            print("the tilt on the globe:", tilt)
            if not (tilt["has"] and tilt["vis"]):
                print("   FAIL: the globe must offer the tilt")
                errors.append("the globe has no tilt button")
            elif tilt["hasTurn"]:
                print("   FAIL: the flat turn is still in the state")
                errors.append("the flat turn is still in the state")
            else:
                print("   ok")
            if tilt["has"]:
                pg.query_selector(".mapctl [data-z='tilt']").click()
                pg.wait_for_timeout(600)
                on = pg.evaluate("""() => {
                  var st = window.__maps;
                  return {mode: st ? !!st.tiltMode : null,
                          note: (document.querySelector('#mapnote') ||
                                 {textContent: ''}).textContent};
                }""")
                print("the tilt switched on:", on)
                if not on["mode"]:
                    print("   FAIL: the tilt button does not switch the tilt on")
                    errors.append("the tilt button does nothing")
                elif "tilt is on" not in on["note"]:
                    print("   FAIL: the note does not say the tilt is on")
                    errors.append("the note does not mention the tilt")
                else:
                    print("   ok")
                pg.query_selector(".mapctl [data-z='tilt']").click()
                pg.wait_for_timeout(400)
            # and on the flat map there is no tilt button at all
            pg.query_selector_all("#mapviews button")[0].click()
            pg.wait_for_timeout(1500)
            flat = pg.evaluate("""() => {
              var b = document.querySelector(".mapctl [data-z='tilt']");
              var st = window.__maps;
              return {hidden: b ? (b.style.display === 'none' ||
                                    b.offsetParent === null) : true,
                      tilt: st ? st.tilt : null,
                      pan: st ? st.pan.slice() : null};
            }""")
            print("the flat map:", flat)
            if not flat["hidden"]:
                print("   FAIL: the flat map must not offer the tilt")
                errors.append("the flat map offers the tilt button")
            elif flat["tilt"]:
                print("   FAIL: the flat map carries a tilt")
                errors.append("the flat map carries a tilt")
            else:
                print("   ok")

            # THE ARCHIVE: the picker must offer the earlier run, and
            # choosing it must draw the CHANGE between the two runs.
            arch = pg.evaluate("""() => {
              var s = document.getElementById('snowArchive');
              if (!s) { return {none: true}; }
              var opts = [];
              for (var i = 0; i < s.options.length; i++) {
                opts.push(s.options[i].value + '|' + s.options[i].textContent);
              }
              return {none: false, disabled: s.disabled, opts: opts};
            }""")
            print("the archive picker:", arch)
            if arch.get("none") or arch.get("disabled"):
                print("   FAIL: the archive picker is missing or disabled")
                errors.append("the archive picker offers no earlier run")
            elif len(arch["opts"]) < 2:
                print("   FAIL: the archive picker lists only one run")
                errors.append("the archive picker lists one run")
            else:
                print("   ok")
            if not arch.get("none"):
                pg.select_option("#snowArchive", "2026-10")
                pg.wait_for_timeout(2500)
                cmp_ = pg.evaluate("""() => {
                  var st = window.__maps;
                  var cap = (document.querySelector('#maplegend') ||
                             {textContent: ''}).textContent || '';
                  return {archive: st ? st.archive : null,
                          diff: st ? !!st.diff : null,
                          kind: st && st.diff ? st.diff.kind : null,
                          mode: st && st.gl ? st.gl.mode : null,
                          cap: cap};
                }""")
                print("the comparison:", cmp_["archive"], cmp_["kind"])
                print("   the caption:", (cmp_["cap"] or "")[:120])
                if cmp_["archive"] != "2026-10" or not cmp_["diff"]:
                    print("   FAIL: the comparison did not switch on")
                    errors.append("the archive comparison did not draw")
                elif cmp_["mode"] != 1:
                    print("   FAIL: the comparison is not drawn with the "
                          "diverging table")
                    errors.append("the comparison uses the wrong colour table")
                elif "change since" not in (cmp_["cap"] or "").lower():
                    print("   FAIL: the caption does not say what is drawn")
                    errors.append("the comparison caption is wrong")
                else:
                    print("   ok")
                pg.screenshot(path="/tmp/maps_compare.png")
                # and back to the current run alone
                pg.select_option("#snowArchive", "")
                pg.wait_for_timeout(2000)
                back = pg.evaluate("() => window.__maps ? !!window.__maps.diff : null")
                print("   back to the current run, the comparison is off:",
                      back is False)
                if back is not False:
                    errors.append("the comparison stayed on")

            # is anything actually painted on the canvas?
            # the canvas is drawn on the GPU now, so it is read with
            # readPixels, a pixel at a time: a read of the whole canvas
            # takes the context down with it
            painted = pg.evaluate("""() => {
              var st = window.__maps;
              if (!st || !st.gl) { return 'no renderer'; }
              var gl = st.gl.gl, c = st.gl.canvas;
              /* draw again first: the drawing buffer is cleared once the
                 page has taken it, and a read outside the frame would
                 come back empty */
              st.gl.render();
              var W = c.width, H = c.height;
              var buf = new Uint8Array(4);
              var n = 0, land = 0, total = 0;
              for (var y = 0; y < H; y += 23) {
                for (var x = 0; x < W; x += 23) {
                  gl.readPixels(x, H - 1 - y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, buf);
                  total++;
                  if (buf[3] > 0) { n++; }
                  /* our own land colour: the slate the map is painted with */
                  if (Math.abs(buf[0] - 51) < 6 && Math.abs(buf[1] - 68) < 6 &&
                      Math.abs(buf[2] - 90) < 6) { land++; }
                }
              }
              return n + ' painted pixels of ' + total + ', ' + land +
                     ' of them land';
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
            # the REAL multi-model manifest goes back: the test stood in
            # for it, and the published data directory must not keep the
            # test's copy
            multi = os.path.join(DATA, "snowmap_c3s-multi.json")
            bak = os.path.join(DATA, "snowmap_c3s-multi.json.bak")
            if os.path.exists(bak):
                shutil.copyfile(bak, multi)
                os.remove(bak)
            # the saved copy of the index is a safety net, not a file the
            # published data directory should carry
            tbak = os.path.join(DATA, "snowmap_tags.json.bak")
            if os.path.exists(tbak):
                os.remove(tbak)
            # the archive the test made, and the index of runs
            adir = os.path.join(DATA, "maps", ATAG, "2026-10")
            if os.path.isdir(adir):
                shutil.rmtree(adir)
                up = os.path.dirname(adir)
                if os.path.isdir(up) and not os.listdir(up):
                    os.rmdir(up)
            # THE INDEX OF RUNS IS REBUILT, never restored from a saved
            # copy: the saved copy can be the test's own, and the site's
            # index must never carry a model that is not there.
            import export_snow_map as ESM2
            ESM2.write_archive_index()
            # put the real model index back, rebuilt from the manifests
            # that are actually there - restoring a saved copy can put
            # back a picker entry for a model the site does not have
            import export_snow_map as ESM
            tags = []
            state = {}
            for f in sorted(os.listdir(DATA)):
                if not (f.startswith("snowmap_") and f.endswith(".json")):
                    continue
                if f in ("snowmap_tags.json",):
                    continue
                tag = f[len("snowmap_"):-len(".json")]
                if tag == TAG:
                    continue
                m = json.load(open(os.path.join(DATA, f)))
                tags.append(tag)
                state[tag] = {"name": m.get("name", tag), "init": m.get("init", "")}
            ESM.write_index(tags, state)
            print("cleaned up the test files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
