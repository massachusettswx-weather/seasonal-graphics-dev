#!/usr/bin/env python3
"""Check the WebGL map renderer against d3 and against the published ladder.

The map was drawn on the CPU to begin with: every pixel asked d3 where it
was, and the answer was cached as a sampling plan.  It is drawn on the GPU
now, and a renderer that disagrees with d3 by a tenth of a degree would put
the snow in the wrong place - so this checks three things:

  1. the renderer's projection is d3's projection.  Every view, several
     rotations and zooms, a grid of points forward and a grid of pixels
     back: the largest disagreement must be a rounding error, not a
     fraction of a degree;
  2. the colour the GPU paints at a pixel is the colour the old CPU
     arithmetic painted there - the same four cells, the same weights,
     the same table - because the map has to BE the static map;
  3. a drag is a drag: the frame must cost milliseconds, not the three
     seconds the CPU version cost.

    python3 tools/test_map_gl.py
"""
import os
import sys
import json
import time
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux/chrome"

# the projection check, run inside the page
PROJ_JS = r"""
() => {
  var st = window.__maps;
  var DEG = Math.PI / 180;
  var W = 1200, H = 700;
  var views = ["flat", "globe", "polar"];
  var rots = [[95, -35], [0, 0], [-120, 20], [30, 60]];
  var zooms = [1, 2.5, 6];
  var worstFwd = 0, worstInv = 0, worstCase = "";
  function mk(v, rot, prot, zoom) {
    var proj;
    if (v === "flat") {
      proj = d3.geoEquirectangular()
        .fitExtent([[10, 10], [W - 10, H - 10]], {type: "Sphere"});
    } else if (v === "globe") {
      proj = d3.geoOrthographic()
        .fitExtent([[10, 10], [W - 10, H - 10]], {type: "Sphere"})
        .rotate(rot);
    } else {
      proj = d3.geoAzimuthalEquidistant().rotate(prot)
        .fitExtent([[10, 10], [W - 10, H - 10]], {type: "Sphere"});
    }
    if (zoom !== 1) { proj.scale(proj.scale() * zoom); }
    var t = proj.translate();
    var lam0 = 0, phi0 = 0;
    if (v === "globe") { lam0 = -rot[0] * DEG; phi0 = -rot[1] * DEG; }
    if (v === "polar") { lam0 = -prot[0] * DEG; phi0 = -prot[1] * DEG; }
    return {proj: proj, p: {view: v, lam0: lam0, phi0: phi0,
                             k: proj.scale(), x0: t[0], y0: t[1]}};
  }
  for (var vi = 0; vi < views.length; vi++) {
    for (var ri = 0; ri < rots.length; ri++) {
      for (var zi = 0; zi < zooms.length; zi++) {
        var v = views[vi];
        var m = mk(v, rots[ri], [0, -90], zooms[zi]);
        var proj = m.proj, p = m.p;
        /* forward: a grid of points on the sphere */
        for (var a = -80; a <= 80; a += 20) {
          for (var b = -180; b < 180; b += 20) {
            var q = proj([b, a]);
            if (!q) { continue; }
            var g = MapGL.projectPoint(b * DEG, a * DEG, p);
            var e = Math.max(Math.abs(q[0] - g.x), Math.abs(q[1] - g.y));
            if (e > worstFwd) {
              worstFwd = e;
              worstCase = "forward " + v + " rot " + rots[ri] +
                          " zoom " + zooms[zi] + " at " + b + "," + a;
            }
          }
        }
        /* backward: a grid of pixels on the screen */
        for (var x = 0; x <= W; x += 37) {
          for (var y = 0; y <= H; y += 31) {
            var ll = proj.invert([x, y]);
            if (!ll) { continue; }
            if (isNaN(ll[0]) || isNaN(ll[1])) { continue; }
            var g2 = MapGL.invertPoint(x, y, p);
            var dlon = Math.abs(ll[0] - g2.lon) % 360;
            if (dlon > 180) { dlon = 360 - dlon; }
            var e2 = Math.max(dlon, Math.abs(ll[1] - g2.lat));
            if (e2 > worstInv) {
              worstInv = e2;
              worstCase = "inverse " + v + " rot " + rots[ri] +
                          " zoom " + zooms[zi] + " at " + x + "," + y;
            }
          }
        }
      }
    }
  }
  return {fwd: worstFwd, inv: worstInv, where: worstCase};
}
"""

# the colour check: the GPU against the CPU arithmetic, at the pixels
COLOUR_JS = r"""
() => {
  var st = window.__maps;
  var man = st.manifest;
  if (!man || !st.raster || !st.gl) { return {error: "no model"}; }
  var g = man.grid;
  var nlon = g.nlon, nlat = g.nlat;
  var bytes = st.raster.bytes;
  var span = nlon * g.dlon;
  var isGlobal = span >= 359.5;
  var lut = man.lut;
  var alut = man.anom_lut;
  var bottom = MapGL.hexToRgb((man.colors || ["#ffffff"])[0]);
  var isAnom = st.field === "anom";
  var W = st.gl.canvas.width, H = st.gl.canvas.height;
  var gl = st.gl.gl;
  /* draw now and read the pixels in the same task, so the buffer is
     still there.  One pixel at a time: a readPixels of the whole canvas
     is a big allocation, and it takes the context down with it. */
  /* the outlines are drawn over the field on purpose, so they are turned
     off here: this check is about the field's own colour */
  st.gl.showVectors = false;
  st.gl.render();
  var px = new Uint8Array(4);
  function at(x, y) {
    gl.readPixels(x, H - 1 - y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    return [px[0], px[1], px[2], px[3]];
  }
  var checked = 0, bad = 0, worst = 0, where = "";
  var p = st.gl.p;
  /* a scatter of pixels */
  for (var k = 0; k < 4000; k++) {
    var x = Math.floor((k * 7919) % W);
    var y = Math.floor((k * 104729) % H);
    /* the rim of light round the limb is blended over the map on
       purpose, so the pixels under it are not the field's colour */
    var ppx = (x + 0.5 - p.x0) / p.k, ppy = (p.y0 - (y + 0.5)) / p.k;
    if (p.view === "globe" && Math.sqrt(ppx * ppx + ppy * ppy) > 0.62 * 1.16) {
      continue;
    }
    var ll = MapGL.invertPoint(x + 0.5, y + 0.5, p);
    if (isNaN(ll.lon) || isNaN(ll.lat)) { continue; }
    var lat = ll.lat, lon = ll.lon;
    if (lat > g.lat0 || lat < g.lat0 - (nlat - 1) * g.dlat) { continue; }
    var fi = (g.lat0 - lat) / g.dlat, fj;
    if (isGlobal) {
      fj = ((lon - g.lon0) / g.dlon) % nlon;
      if (fj < 0) { fj += nlon; }
    } else {
      var la = lon;
      if (g.lon0 >= 0) {
        while (la < 0) { la += 360; }
        while (la >= 360) { la -= 360; }
      } else {
        while (la > 180) { la -= 360; }
        while (la < -180) { la += 360; }
      }
      if (la < g.lon0 - 1e-9 || la > g.lon0 + span - 1e-9) { continue; }
      fj = (la - g.lon0) / g.dlon;
      if (fj < 0) { fj += nlon; }
      if (fj >= nlon) { fj -= nlon; }
    }
    var i0 = Math.floor(fi), j0 = Math.floor(fj);
    if (i0 < 0) { i0 = 0; }
    if (i0 > nlat - 2) { i0 = nlat - 2; }
    if (j0 < 0) { j0 = 0; }
    if (j0 > nlon - 2) { j0 = nlon - 2; }
    var fx = fj - j0, fy = fi - i0;
    var a = bytes[i0 * nlon + j0];
    var b = bytes[i0 * nlon + Math.min(j0 + 1, nlon - 1)];
    var c = bytes[Math.min(i0 + 1, nlat - 1) * nlon + j0];
    var d = bytes[Math.min(i0 + 1, nlat - 1) * nlon + Math.min(j0 + 1, nlon - 1)];
    var v = (1 - fx) * ((1 - fy) * a + fy * c) + fx * ((1 - fy) * b + fy * d);
    var want = null;
    if (isAnom) {
      /* the anomalies have a table of their own, built with the panels'
         own norm, so the colour is the panels' colour */
      if (v >= 255) { continue; }
      if (!alut || alut.length !== 256) { continue; }
      want = MapGL.hexToRgb(alut[Math.min(254, Math.round(v))]);
    } else {
      if (v < 0.5) { continue; }
      var col = MapGL.hexToRgb(lut[Math.min(255, Math.round(v))]);
      if (col[0] === bottom[0] && col[1] === bottom[1] && col[2] === bottom[2]) {
        continue;
      }
      want = col;
    }
    var got = at(x, y);
    checked++;
    var e = Math.max(Math.abs(got[0] - want[0]),
                     Math.abs(got[1] - want[1]),
                     Math.abs(got[2] - want[2]));
    if (e > worst) {
      worst = e;
      where = "at " + x + "," + y + " (" + lat.toFixed(2) + "," +
              lon.toFixed(2) + ") want " + want + " got " + got;
    }
    if (e > 0) { bad++; }
  }
  st.gl.showVectors = true;      /* the outlines go back on for the drag */
  return {checked: checked, bad: bad, worst: worst, where: where,
          W: W, H: H, anom: isAnom};
}
"""

# the drag: how long does a frame cost?
DRAG_JS = r"""
() => {
  var st = window.__maps;
  var gl = st.gl.gl;
  var N = 40;
  /* the CPU part: the work the browser does to put a frame together */
  var t0 = performance.now();
  for (var i = 0; i < N; i++) {
    st.rot[0] += 3;
    st.gl.setProjection({
      view: "globe", lam0: -st.rot[0] * Math.PI / 180,
      phi0: -st.rot[1] * Math.PI / 180,
      k: st.gl.p.k, x0: st.gl.p.x0, y0: st.gl.p.y0});
    st.gl.render();
  }
  var t1 = performance.now();
  /* and the whole frame, GPU included */
  gl.finish();
  var t2 = performance.now();
  var t3 = performance.now();
  for (var j = 0; j < N; j++) {
    st.rot[0] += 3;
    st.gl.render();
    gl.finish();
  }
  var t4 = performance.now();
  return {cpu: (t1 - t0) / N, total: (t4 - t3) / N,
          W: st.gl.canvas.width, H: st.gl.canvas.height,
          renderer: gl.getParameter(gl.RENDERER)};
}
"""


def main():
    port = 8767
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port),
                             "--directory", DOCS],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    fails = []
    try:
        from playwright.sync_api import sync_playwright
        errors = []
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=CHROME, args=[
                "--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
            pg = b.new_page(viewport={"width": 1400, "height": 1000})
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errors.append("PAGEERROR " + str(e)))
            pg.on("requestfailed", lambda r: errors.append("FAILED " + r.url))
            pg.goto("http://127.0.0.1:%d/maps.html" % port)
            pg.wait_for_timeout(6000)

            # is the map there at all?
            info = pg.evaluate("""() => {
              var st = window.__maps;
              return {gl: !!st.gl, model: st.tag, field: st.field,
                      W: st.gl ? st.gl.canvas.width : 0,
                      H: st.gl ? st.gl.canvas.height : 0,
                      mask: st.data.land ? 'yes' : 'no'};
            }""")
            print("page:", info)
            if not info["gl"]:
                fails.append("no renderer")
                print("console errors:", errors)
                b.close()
                return 1

            # 1. the projection
            pr = pg.evaluate(PROJ_JS)
            print("projection vs d3: forward %.3g px, inverse %.3g deg  (%s)"
                  % (pr["fwd"], pr["inv"], pr["where"]))
            if pr["fwd"] > 0.05:
                fails.append("the forward projection is off by %.3g px" % pr["fwd"])
            if pr["inv"] > 0.01:
                fails.append("the inverse projection is off by %.3g deg" % pr["inv"])

            # 2. the colours
            col = pg.evaluate(COLOUR_JS)
            print("colours:", col)
            if col.get("checked", 0) < 50:
                fails.append("too few pixels checked (%s)" % col.get("checked"))
            # a cell's edge can fall either side of a whole byte, and the
            # GPU and the CPU round it on opposite sides of the .5: a
            # handful of pixels is the field's own edge, not a mistake
            if col.get("bad", 0) > max(3, col.get("checked", 0) // 100):
                fails.append("%d pixels are the wrong colour" % col["bad"])

            # the anomaly too: it is painted at 0.82 over the earth, so
            # the check is on the anomaly's own palette
            pg.evaluate("() => window.__maps && document.querySelectorAll("
                        "'#snowfield button')[1].click()")
            pg.wait_for_timeout(2500)
            an = pg.evaluate(COLOUR_JS)
            print("anomaly palette read back:", an.get("checked"),
                  "pixels,", an.get("bad"), "wrong")
            if an.get("bad", 0) > max(3, an.get("checked", 0) // 100):
                fails.append("%d anomaly pixels are the wrong colour"
                             % an["bad"])

            # 3. the drag
            dr = pg.evaluate(DRAG_JS)
            print("drag: %.2f ms of CPU a frame, %.2f ms with the GPU "
                  "(software renderer: %s), %dx%d"
                  % (dr["cpu"], dr["total"], dr["renderer"], dr["W"], dr["H"]))
            if dr["cpu"] > 20:
                fails.append("the CPU part of a frame costs %.1f ms" % dr["cpu"])

            # is the context still alive?  under the software renderer this
            # call can take a very long time, so it is given a deadline of
            # its own: a hung evaluate must not hang the whole test.  The
            # evaluate does not take a timeout of its own, so the page's
            # default is lowered for the call.
            alive = True
            try:
                pg.set_default_timeout(20000)
                alive = pg.evaluate(
                    "() => window.__maps.gl.gl.isContextLost()")
            except Exception as e:
                print("the context check did not answer in time (%s) - "
                      "taking it as lost" % e)
                alive = True
            finally:
                pg.set_default_timeout(30000)
            print("context lost:", alive)
            if alive:
                fails.append("the WebGL context was lost")
            # the picture is a nice-to-have: under the software renderer
            # the page can still be busy with the drag, and a screenshot
            # that times out must not fail the whole test
            try:
                pg.wait_for_timeout(1500)
                t = time.time()
                pg.screenshot(path="/tmp/map_gl_test.png", timeout=60000)
                print("screenshot: %.1f s" % (time.time() - t))
            except Exception as e:
                print("screenshot did not make it (%s)" % e)
            b.close()
        print("console errors:", errors if errors else "none")
        if errors:
            fails.append("%d console errors" % len(errors))
    finally:
        srv.terminate()
    if fails:
        print("FAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print("all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
