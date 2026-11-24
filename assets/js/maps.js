/* ------------------------------------------------------------------
   Interactive Natural Earth maps for the seasonal graphics site.

   One map, one timeline.  The whole world, drawn from Natural Earth
   1:50m data that is committed to the repository, with the seasonal
   snowfall painted on it:

     2D Map   the flat world on an equirectangular grid
     3D Globe the same world on an orthographic globe you can spin

   The field is the model's OWN output - the whole world, at the grid the
   model came on, with no resampling - and it comes in two flavours: the
   accumulated snowfall, and the anomaly against that model's own
   hindcast climate.

   HOW THE FIELD IS DRAWN
   ----------------------
   The exporter writes each field as an 8-bit greyscale PNG, one byte per
   cell, on the model's own grid.  Here the PNG is decoded into a byte
   array and handed to the WebGL renderer in mapgl.js.

   The renderer asks, for every pixel of the canvas, where that pixel is
   on the globe, and reads the model's own grid there - with the same
   four cells, the same weights and the same published colour table the
   static panels use, so the map IS the static map and not merely a map
   of the same data.  Doing that on the CPU meant two million
   projections a frame and a three second drag; on the GPU it is two
   draw calls.

   The earth (the sea, the land and the lakes) is baked once into an
   equirectangular mask, and the coastlines are drawn as GPU lines, so
   nothing has to be rebuilt while the map is being dragged.
   ------------------------------------------------------------------ */
(function () {
  "use strict";

  var NE = "assets/ne/";
  var SRC = {
    countries: NE + "ne_50m_admin_0_countries.geojson",
    lakes: NE + "ne_50m_lakes.geojson",
    land: NE + "ne_50m_land.geojson",
    states: NE + "ne_50m_admin_1_states_us_can.geojson"
  };

  /* the globe opens over North America, where the snowfall field is:
     d3's rotate() puts (-lambda, -phi) at the centre */
  var GLOBE_ROT = [95, -35];

  var state = {view: "globe", rot: GLOBE_ROT.slice(), win3: false,
               /* THE GLOBE'S TILT: the axis tips over toward the viewer.
                  The owner asked for the tilt alone (22 Nov 2026) - the
                  flat map pans, it does not turn on the screen.  The
                  angle is in degrees here and radians in the projection. */
               tilt: 0, tiltMode: false,
               drag: null, zoom: 1,
               pan: [0, 0], field: "total", month: -1, tag: null,
               manifest: null, raster: null, index: null,
               /* THE ARCHIVE: the runs that came before this one, so a
                  reader can put the current run beside an older one.
                  runs is the whole list the exporter wrote;
                  archive is the init of the run being compared with
                  (null = the current run alone); diff carries the
                  comparison's own scale while one is showing. */
               runs: [], archive: null, archiveManifest: null,
               diff: null,
               timer: null, data: {}, gl: null, hover: -1,
               base: null, baseKey: null, pending: false,
               boxW: null, svgW: null, svgH: null, canvasW: null, canvasH: null};

  function el(id) { return document.getElementById(id); }

  /* ---------------------------------------------------------------- */
  /* the earth, painted under the field                               */

  /* OUR earth, floating in space: a deep blue sea and a slate land, with
     the coastlines in a cool steel blue.  The sea is a clear step lighter
     than the sky behind it, so the globe never dissolves into the
     background, and the field's own colours are the only bright thing on
     the map. */
  var OCEAN = "#12395c";
  var LAND = "#33445a";
  var SPACE = "#02060d";

  /* the sky: a deterministic starfield and a faint nebula, drawn under
     the globe.  The same seed every time, so the sky does not jump about
     as the map is redrawn. */
  function paintSpace(ctx, W, H) {
    ctx.fillStyle = SPACE;
    ctx.fillRect(0, 0, W, H);
    /* the nebula: two soft glows, nothing more */
    var g1 = ctx.createRadialGradient(W * 0.72, H * 0.18, 0,
                                      W * 0.72, H * 0.18, Math.max(W, H) * 0.55);
    g1.addColorStop(0, "rgba(70,110,170,0.20)");
    g1.addColorStop(1, "rgba(70,110,170,0)");
    ctx.fillStyle = g1;
    ctx.fillRect(0, 0, W, H);
    var g2 = ctx.createRadialGradient(W * 0.22, H * 0.82, 0,
                                      W * 0.22, H * 0.82, Math.max(W, H) * 0.45);
    g2.addColorStop(0, "rgba(120,70,150,0.16)");
    g2.addColorStop(1, "rgba(120,70,150,0)");
    ctx.fillStyle = g2;
    ctx.fillRect(0, 0, W, H);
    /* the stars */
    var seed = 20261117;
    function rnd() {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      return seed / 0x7fffffff;
    }
    var n = Math.round((W * H) / 2600);
    for (var i = 0; i < n; i++) {
      var x = rnd() * W, y = rnd() * H;
      var r = 0.35 + rnd() * 0.95;
      var a = 0.18 + rnd() * 0.72;
      ctx.beginPath();
      ctx.fillStyle = "rgba(226,238,255," + a.toFixed(3) + ")";
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fill();
    }
  }

  /* ---------------------------------------------------------------- */
  /* the earth, baked once                                             */

  /* The sea, the land and the lakes do not change while the map is
     being dragged, so they are drawn ONCE into an equirectangular mask
     - the land in red, the lakes in green - and the GPU reads that mask
     for every pixel.  Re-projecting and re-filling the earth on every
     frame of a drag is what used to make the map crawl. */
  var MASK_W = 4096, MASK_H = 2048;

  /* There are hundreds of lakes in the 1:50m file, and at the scale of
     the map the small ones are a speckle of dots rather than lakes.  The
     ones a reader would name are the big ones, so the small ones are
     left out - in the mask and in the outlines alike, or the map would
     show them twice. */
  function bigLakes(lakes) {
    if (!lakes) { return lakes; }
    var keep = [];
    for (var f = 0; f < lakes.features.length; f++) {
      var feat = lakes.features[f];
      var g = feat.geometry;
      if (!g) { continue; }
      var polys = (g.type === "MultiPolygon") ? g.coordinates : [g.coordinates];
      var ok = false;
      for (var p = 0; p < polys.length && !ok; p++) {
        for (var r = 0; r < polys[p].length && !ok; r++) {
          var ring = polys[p][r];
          var x0 = 999, x1 = -999, y0 = 999, y1 = -999;
          for (var i = 0; i < ring.length; i++) {
            var x = ring[i][0], y = ring[i][1];
            if (x < x0) { x0 = x; }
            if (x > x1) { x1 = x; }
            if (y < y0) { y0 = y; }
            if (y > y1) { y1 = y; }
          }
          if (Math.max(x1 - x0, y1 - y0) >= 1.0) { ok = true; }
        }
      }
      if (ok) { keep.push(feat); }
    }
    return {type: "FeatureCollection", features: keep};
  }

  function bakeMask() {
    if (!state.data.land || !state.data.lakes || !state.gl) { return; }
    var c = document.createElement("canvas");
    c.width = MASK_W;
    c.height = MASK_H;
    var ctx = c.getContext("2d");
    ctx.fillStyle = "#000000";
    ctx.fillRect(0, 0, MASK_W, MASK_H);
    var proj = d3.geoEquirectangular()
      .scale(MASK_W / (2 * Math.PI))
      .translate([MASK_W / 2, MASK_H / 2]);
    var path = d3.geoPath(proj, ctx);
    /* d3's geoPath does not start a new path: it draws into the one
       that is there, so each shape has to begin its own */
    ctx.fillStyle = "#ff0000";
    ctx.beginPath();
    path(state.data.land);
    ctx.fill();
    /* the lakes are holes in the land: they are added, so the red of
       the land stays underneath them */
    ctx.globalCompositeOperation = "lighter";
    ctx.fillStyle = "#00ff00";
    ctx.beginPath();
    path(bigLakes(state.data.lakes));
    ctx.fill();
    state.gl.setMask(c);
  }

  /* ---------------------------------------------------------------- */
  /* the field                                                         */

  function hexToRgb(h) {
    return [parseInt(h.substr(1, 2), 16),
            parseInt(h.substr(3, 2), 16),
            parseInt(h.substr(5, 2), 16)];
  }

  /* the value a byte stands for, for the tooltip */
  function byteValue(byte) {
    var man = state.manifest;
    /* A COMPARISON: the byte is a difference between two runs, and it
       stands for the change, not for the field itself. */
    if (state.diff) {
      if (byte >= 255) { return null; }
      if (state.diff.kind === "totals") {
        var t = byte / 254 * 2 - 1;
        var mag = Math.pow(10, Math.abs(t) * state.diff.k) - 1;
        return (t >= 0 ? 1 : -1) * mag * DIFF_FLOOR;
      }
      return (byte / 254 * 2 - 1) * state.diff.scale;
    }
    if (state.field === "anom") {
      if (byte >= 255) { return null; }
      var s = man.anom_scale || 10;
      return (byte / 254 * 2 - 1) * s;
    }
    var levels = man.levels;
    var t = Math.min(byte, 254) / 254 * (levels.length - 1);
    var i = Math.floor(t), f = t - i;
    var lo = levels[Math.min(i, levels.length - 1)];
    var hi = levels[Math.min(i + 1, levels.length - 1)];
    if (hi <= lo) { return lo; }
    return Math.pow(lo, 1 - f) * Math.pow(hi, f);
  }

  /* ---------------------------------------------------------------- */
  /* the interaction                                                    */

  /* How far the map moves for one pixel of pointer movement.

     The globe used to spin at a fixed 0.45 degrees a pixel, which meant
     the SAME drag threw it much further once the map was zoomed in: at
     306% the visible face moved seven pixels for every pixel of the
     pointer, and the map was impossible to hold still.  The spin is now
     divided by the zoom, so the face moves the same distance on the
     screen whatever the magnification, and the base rate is gentler.

     The flat map pans under the pointer.  It follows more slowly than
     the pointer now: the map drifts a little behind the hand, which
     makes it easier to stop on the thing you are looking at. */
  var DRAG_GAIN = {flat: 0.75, globe: 0.30};

  /* The coastlines are drawn by the GPU now, so the SVG is only the
     sheet the pointer talks to - and, on the globe, the marker for the
     pole when the pole is on the near side. */
  function setupInteraction(svg) {
    svg.selectAll("*").remove();
    state.pole = null;
    if (state.view === "globe") {
      state.pole = svg.append("circle").attr("class", "pole").attr("r", 3);
    }
    /* the drag: the flat map pans, the globe spins */
    svg.call(d3.drag()
      .on("start", function (ev) { state.drag = d3.pointer(ev, this); })
      .on("drag", function (ev) {
        var p = d3.pointer(ev, this);
        var dx = p[0] - state.drag[0], dy = p[1] - state.drag[1];
        if (state.tiltMode && state.view === "globe") {
          /* THE GLOBE IS TIPPED OVER: the north pole leans toward the
             viewer.  The horizontal part of the drag still spins the
             globe, so the earth can be turned on its side AND round its
             axis.  The flat map is not turned - it pans, and it always
             has. */
          state.tilt = Math.max(-75, Math.min(75,
              state.tilt + dy * DRAG_GAIN.globe / state.zoom));
          state.rot[0] += dx * DRAG_GAIN.globe / state.zoom;
        } else if (state.view === "flat") {
          state.pan[0] += dx * DRAG_GAIN.flat;
          state.pan[1] += dy * DRAG_GAIN.flat;
        } else {
          /* the spin is divided by the zoom, so the map moves the same
             distance on the screen at every magnification */
          var g = DRAG_GAIN.globe / state.zoom;
          state.rot[0] += dx * g;
          state.rot[1] = Math.max(-90, Math.min(90, state.rot[1] - dy * g));
        }
        state.drag = p;
        requestDraw();
      }));
    svg.on("wheel", function (ev) {
      ev.preventDefault();
      zoomAt(ev, ev.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP);
    });
  }

  function viewNote() {
    var tilt = (state.tiltMode && state.view === "globe")
      ? " The tilt is on: drag down to tip the globe over, sideways to " +
        "spin it." : "";
    if (state.view === "flat") {
      note("The whole world on an equirectangular grid. Drag it to pan, " +
           "scroll or use the buttons to zoom. The equirectangular " +
           "projection squeezes the polar regions.");
    } else {
      note("The same world on an orthographic globe - drag it to spin, scroll " +
           "or use the buttons to zoom." + tilt);
    }
  }

  /* ---------------------------------------------------------------- */
  /* the zoom                                                          */

  /* The zoom is the one thing a world map cannot do without: the field
     is the model's own grid, so a 1 degree model has to be looked at
     from close up to be worth looking at.  Every view can be zoomed
     (the buttons, the scroll wheel, or the keyboard) and the flat map
     can be panned. */

  var ZOOM_MIN = 1, ZOOM_MAX = 12;

  /* The zoom step.  It used to be a tenth of the map's size for every
     notch of the wheel, which is a big jump when the map is small on the
     screen and a small one when it is zoomed in - so it is now a step of
     a tenth of the way to the next size, and the buttons take the same
     step. */
  var ZOOM_STEP = 1.12;

  function setZoom(z) {
    state.zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
    requestDraw();
  }

  /* Zoom about the pointer, so the place under the cursor stays under
     the cursor.  On the globe the zoom is about the centre of the
     sphere - that is where the point being looked at is. */
  function zoomAt(ev, factor) {
    var z = state.zoom * factor;
    if (z < ZOOM_MIN) { z = ZOOM_MIN; }
    if (z > ZOOM_MAX) { z = ZOOM_MAX; }
    if (z === state.zoom) { return; }
    if (state.view === "flat" && ev && ev.clientX !== undefined) {
      var box = el("mapbox");
      var W = box ? box.clientWidth : 0;
      var H = box ? box.clientHeight : 0;
      var cx = W / 2, cy = H / 2;
      var px = ev.clientX - (box ? box.getBoundingClientRect().left : 0);
      var py = ev.clientY - (box ? box.getBoundingClientRect().top : 0);
      state.pan[0] += (px - cx) * (1 - z / state.zoom);
      state.pan[1] += (py - cy) * (1 - z / state.zoom);
    }
    state.zoom = z;
    requestDraw();
  }

  function resetView() {
    state.zoom = 1;
    state.pan = [0, 0];
    state.rot = GLOBE_ROT.slice();
    /* the earth goes back the way it was: no tilt */
    state.tilt = 0;
    requestDraw();
  }

  function buildControls() {
    var box = el("mapbox");
    if (!box || box.querySelector(".mapctl")) { return; }
    var c = document.createElement("div");
    c.className = "mapctl";
    c.innerHTML =
      '<button type="button" data-z="out" title="zoom out">−</button>' +
      '<span class="zlabel">100%</span>' +
      '<button type="button" data-z="in" title="zoom in">+</button>' +
      '<button type="button" data-z="tilt" title="tip the globe over: drag ' +
      'down to tip it, sideways to spin it">↻</button>' +
      '<button type="button" data-z="reset" title="reset the view">⟲</button>';
    box.appendChild(c);
    c.addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest("button") : null;
      if (!b) { return; }
      ev.preventDefault();
      ev.stopPropagation();
      var z = b.getAttribute("data-z");
      if (z === "in") { setZoom(state.zoom * ZOOM_STEP); }
      else if (z === "out") { setZoom(state.zoom / ZOOM_STEP); }
      else if (z === "tilt") {
        state.tiltMode = !state.tiltMode;
        b.classList.toggle("on", state.tiltMode);
        viewNote();
      }
      else { resetView(); }
    });
    c.addEventListener("wheel", function (ev) { ev.stopPropagation(); },
                      {passive: true});
    /* the tilt is the globe's: the button is not offered on the flat map */
    var tb = c.querySelector("[data-z='tilt']");
    if (tb) { tb.style.display = state.view === "globe" ? "" : "none"; }
  }

  function updateZoomLabel() {
    var l = document.querySelector(".mapctl .zlabel");
    if (!l) { return; }
    var txt = Math.round(state.zoom * 100) + "%";
    /* the label only changes when the zoom does: writing it on every
       frame would make the browser lay the page out again */
    if (l.textContent !== txt) { l.textContent = txt; }
  }

  /* ---------------------------------------------------------------- */
  /* the field files                                                   */

  function fieldFile() {
    var man = state.manifest;
    if (!man) { return null; }
    var f = state.field === "anom" ? "anom" : "total";
    /* THE THREE-MONTH WINDOW: the house publishes the overlapping
       three-month windows of the run (NDJ, DJF, JFM, FMA) and the
       anomaly in them is the mean per month.  The map carries the same
       thing: the window's accumulation for the snowfall, and the
       window's mean per month for the anomaly. */
    if (state.win3) {
      var g = state.field === "anom" ? "avg3_anom" : "avg3_total";
      if (state.month < 0) { return null; }
      var mw = man.months[state.month];
      return mw ? (mw[g] || null) : null;
    }
    if (state.month < 0) { return man.total[f]; }
    var m = man.months[state.month];
    return m ? m[f] : null;
  }

  /* the window the map is showing: one month, or the three months
     centred on it */
  function windowLabel() {
    var man = state.manifest;
    if (!man || state.month < 0) { return null; }
    var m = man.months[state.month];
    if (!m) { return null; }
    if (!state.win3) { return null; }
    return m.avg3_label || null;
  }

  /* the months that carry a three-month window: the house's own four
     (NDJ, DJF, JFM, FMA) - the ones with a full window */
  function monthHasWindow(i) {
    var man = state.manifest;
    if (!man || i < 0 || !man.months || !man.months[i]) { return false; }
    return !!man.months[i].avg3_total;
  }

  function firstWindowMonth() {
    var man = state.manifest;
    if (!man || !man.months) { return -1; }
    for (var i = 0; i < man.months.length; i++) {
      if (man.months[i].avg3_total) { return i; }
    }
    return -1;
  }

  function loadField() {
    var file = fieldFile();
    if (!file) { return; }
    /* A COMPARISON WITH AN EARLIER RUN: both fields are fetched and the
       difference between them is drawn, because that is what "compare
       with the previous run" means on a map.  The difference is computed
       here, in the browser, and uploaded as an ordinary field - the
       renderer needs no second texture and no new mode. */
    var arch = archiveFile();
    if (arch) { loadPair(file, arch); return; }
    if (state.archive) {
      note("That run does not cover the month on the timeline.");
    }
    state.diff = null;
    var img = new Image();
    img.onload = function () {
      var r = readBytes(img);
      if (!r) { return; }
      state.raster = r;
      uploadField();
      requestDraw();
    };
    img.onerror = function () {
      var n = el("mapload");
      if (n) {
        n.style.display = "block";
        n.textContent = "The field " + file + " could not be loaded.";
      }
    };
    img.src = "data/" + file;
  }

  /* the bytes of a field image, in the order the grid wants them */
  function readBytes(img) {
    var c = document.createElement("canvas");
    c.width = img.width; c.height = img.height;
    var ctx = c.getContext("2d");
    ctx.drawImage(img, 0, 0);
    var data = ctx.getImageData(0, 0, img.width, img.height).data;
    var bytes = new Uint8Array(img.width * img.height);
    for (var i = 0, j = 0; i < bytes.length; i++, j += 4) {
      bytes[i] = data[j];
    }
    return {w: img.width, h: img.height, bytes: bytes};
  }

  /* ---------------------------------------------------------------- */
  /* THE ARCHIVE: the runs that came before this one                   */

  var MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                     "July", "August", "September", "October", "November",
                     "December"];

  function initLabel(init) {
    if (!init || init.length < 7) { return init || ""; }
    var y = init.slice(0, 4), m = parseInt(init.slice(5, 7), 10);
    if (!m || m < 1 || m > 12) { return init; }
    return MONTH_NAMES[m - 1] + " " + y;
  }

  function modelRuns(tag) {
    return (state.runs || []).filter(function (r) { return r.tag === tag; });
  }

  /* the picker: the current run, and every earlier run of this model */
  function buildArchivePicker() {
    var sel = el("snowArchive");
    if (!sel) { return; }
    var mine = modelRuns(state.tag);
    sel.innerHTML = "";
    if (mine.length < 2) {
      var none = document.createElement("option");
      none.value = "";
      none.textContent = "no earlier run";
      sel.appendChild(none);
      sel.disabled = true;
      return;
    }
    sel.disabled = false;
    mine.forEach(function (r) {
      var o = document.createElement("option");
      o.value = r.current ? "" : r.init;
      o.textContent = r.current
        ? ("the current run (" + initLabel(r.init) + ")")
        : ("the " + initLabel(r.init) + " run");
      sel.appendChild(o);
    });
    sel.value = state.archive || "";
  }

  /* choose the run to compare the current one with */
  function setArchive(init) {
    state.archive = init || null;
    state.archiveManifest = null;
    state.diff = null;
    if (!state.archive) {
      loadField();
      drawLegend();
      return;
    }
    var run = modelRuns(state.tag).filter(function (r) {
      return r.init === state.archive;
    })[0];
    if (!run) { state.archive = null; loadField(); return; }
    d3.json("data/" + run.manifest).then(function (man) {
      state.archiveManifest = {run: run.manifest, man: man};
      loadField();
      drawLegend();
    }).catch(function () {
      state.archive = null;
      loadField();
      drawLegend();
    });
  }

  /* the archived run's own file for the month the map is showing */
  function archiveFile() {
    if (!state.archive || !state.manifest) { return null; }
    var man = state.archiveManifest && state.archiveManifest.man;
    if (!man || !man.months) { return null; }
    var cur = state.manifest.months ? state.manifest.months[state.month] : null;
    if (!cur || !cur.ym) { return null; }
    /* THE SAME VALID MONTH, NOT THE SAME INDEX: two runs have different
       month lists - a November run starts in December and a December run
       starts in January - so the month is matched by its own label. */
    var g = state.win3
      ? (state.field === "anom" ? "avg3_anom" : "avg3_total")
      : (state.field === "anom" ? "anom" : "total");
    for (var i = 0; i < man.months.length; i++) {
      if (man.months[i].ym === cur.ym) { return man.months[i][g] || null; }
    }
    return null;
  }

  /* THE DIFFERENCE BETWEEN TWO RUNS.

     The anomaly is in standard deviations and the totals in inches, so
     the difference is worked out in those units and then put back on a
     byte scale of its own: the anomaly on +-2 sigma, the totals on a
     signed log scale (a snowfall difference is almost always a small
     number of inches, and a linear scale would show nothing). */
  var DIFF_SIGMA = 2.0;      /* the anomaly's difference scale, sigma */
  var DIFF_INCH = 5.0;       /* the totals' difference scale, inches */
  var DIFF_FLOOR = 0.02;     /* the totals' log scale's floor, inches */

  function diffK() { return Math.log10(1 + DIFF_INCH / DIFF_FLOOR); }

  function differenceBytes(nowB, archB) {
    var n = Math.min(nowB.length, archB.length);
    var out = new Uint8Array(n);
    if (state.field === "anom") {
      var s = (state.manifest.anom_scale || 10);
      for (var i = 0; i < n; i++) {
        var a = nowB[i], b = archB[i];
        if (a >= 255 || b >= 255) { out[i] = 255; continue; }
        var d = ((a / 254 * 2 - 1) - (b / 254 * 2 - 1)) * s;
        var t = d / DIFF_SIGMA;
        if (t > 1) { t = 1; } else if (t < -1) { t = -1; }
        out[i] = Math.round((t + 1) * 127);
      }
      return out;
    }
    var k = diffK();
    for (var j = 0; j < n; j++) {
      var a2 = nowB[j], b2 = archB[j];
      if (a2 >= 255 || b2 >= 255) { out[j] = 255; continue; }
      var dd = byteValue(a2) - byteValue(b2);
      var tt = (dd >= 0 ? 1 : -1) * Math.log10(1 + Math.abs(dd) / DIFF_FLOOR) / k;
      if (tt > 1) { tt = 1; } else if (tt < -1) { tt = -1; }
      out[j] = Math.round((tt + 1) * 127);
    }
    return out;
  }

  /* both fields, and the difference between them */
  function loadPair(nowFile, archFile) {
    var img1 = new Image(), img2 = new Image();
    var got = 0;
    var done = function () {
      got++;
      if (got < 2) { return; }
      var b1 = readBytes(img1), b2 = readBytes(img2);
      if (!b1 || !b2) { return; }
      state.raster = {w: b1.w, h: b1.h, bytes: differenceBytes(b1.bytes, b2.bytes)};
      state.diff = state.field === "anom"
        ? {kind: "anom", scale: DIFF_SIGMA}
        : {kind: "totals", scale: DIFF_INCH, k: diffK()};
      /* the legend describes what is on the map, so it is drawn once the
         difference is known - not when the archive was chosen */
      drawLegend();
      uploadField();
      requestDraw();
    };
    img1.onload = done;
    img1.onerror = function () { fail("the current field could not be loaded"); };
    img2.onload = done;
    img2.onerror = function () { fail("the earlier run's field could not be loaded"); };
    img1.src = "data/" + nowFile;
    img2.src = "data/" + archFile;
  }

  function loadModel(tag) {
    state.tag = tag;
    state.manifest = null;
    state.raster = null;
    state.month = -1;
    /* a new model means a new set of runs: the archive that was chosen
       belonged to the model before */
    state.archive = null;
    state.archiveManifest = null;
    state.diff = null;
    buildArchivePicker();
    if (!tag) { draw(); return; }
    d3.json("data/snowmap_" + tag + ".json").then(function (d) {
      try {
        state.manifest = d;
        /* a model without its own hindcast climate has no honest anomaly:
           the toggle is switched off and says why */
        var ab = document.querySelectorAll("#snowfield button");
        Array.prototype.forEach.call(ab, function (b) {
          if (b.dataset.field !== "anom") { return; }
          if (d.anom_available === false) {
            b.disabled = true;
            b.style.opacity = 0.45;
            b.title = "this model has no hindcast climate, so there is " +
              "nothing to measure the anomaly against";
          } else {
            b.disabled = false;
            b.style.opacity = "";
            b.title = "";
          }
        });
        if (d.anom_available === false && state.field === "anom") {
          state.field = "total";
          Array.prototype.forEach.call(ab, function (b) {
            b.classList.toggle("on", b.dataset.field === "total");
          });
        }
        buildTimeline();
        drawLegend();
        loadField();
        draw();
      } catch (e) {
        fail("the field could not be drawn: " + e);
      }
    }).catch(function (e) {      var n = el("mapload");
      if (n) {
        n.style.display = "block";
        n.textContent = "The snowfall field could not be loaded: " + e;
      }
    });
  }

  /* ---------------------------------------------------------------- */
  /* the timeline                                                      */

  function buildTimeline() {
    var box = el("maptimeline");
    if (!box) { return; }
    box.innerHTML = "";
    var man = state.manifest;
    if (!man) { return; }

    var play = document.createElement("button");
    play.className = "ctrl ghost";
    play.textContent = "▶";
    play.title = "play the run";
    play.addEventListener("click", function () { togglePlay(); });
    box.appendChild(play);

    var mk = function (label, month, value, disabled, why) {
      var b = document.createElement("button");
      b.className = "tlbtn" + (state.month === value ? " on" : "");
      b.textContent = label;
      b.dataset.month = String(value);
      /* THE THREE-MONTH WINDOW: only the months with a full window can
         be picked - a run of six months has four windows (NDJ, DJF,
         JFM, FMA), the house's own four - and the run total has none.
         The buttons that cannot be shown are dimmed and say why. */
      if (disabled) {
        b.classList.add("off");
        b.disabled = true;
        if (why) { b.title = why; }
      }
      b.addEventListener("click", function () {
        if (b.disabled) { return; }
        stopPlay();
        state.month = value;
        markTimeline();
        loadField();
        /* the caption names the window, so it has to be redrawn with
           the month - otherwise it keeps the last window's name */
        drawLegend();
      });
      box.appendChild(b);
    };
    mk("Total", -1, -1, state.win3,
       state.win3 ? "the run total has no three-month window" : "");
    man.months.forEach(function (m, i) {
      mk(m.label, i, i, state.win3 && !m.avg3_total,
         (state.win3 && !m.avg3_total) ?
         "this month has no full three-month window" : "");
    });
  }

  function markTimeline() {
    var btns = document.querySelectorAll("#maptimeline .tlbtn");
    Array.prototype.forEach.call(btns, function (b) {
      b.classList.toggle("on", parseInt(b.dataset.month, 10) === state.month);
    });
  }

  function togglePlay() {
    if (state.timer) { stopPlay(); return; }
    var man = state.manifest;
    if (!man) { return; }
    var next = state.month + 1;
    if (next > man.months.length - 1) { next = -1; }
    state.month = next;
    markTimeline();
    loadField();
    drawLegend();
    state.timer = setInterval(function () {
      var m = state.manifest;
      if (!m) { stopPlay(); return; }
      var n = state.month + 1;
      if (n > m.months.length - 1) { stopPlay(); return; }
      state.month = n;
      markTimeline();
      loadField();
      drawLegend();
    }, 1100);
    var pb = document.querySelector("#maptimeline button");
    if (pb) { pb.textContent = "❚❚"; }
  }

  function stopPlay() {
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
    var pb = document.querySelector("#maptimeline button");
    if (pb) { pb.textContent = "▶"; }
  }

  /* ---------------------------------------------------------------- */
  /* the legend                                                        */

  function drawLegend() {
    var box = el("maplegend");
    if (!box) { return; }
    box.innerHTML = "";
    var man = state.manifest;
    if (!man) { return; }
    var wrap = document.createElement("div");
    wrap.style.width = "100%";
    var bar = document.createElement("div");
    bar.className = "bar";
    var ends = document.createElement("div");
    ends.className = "ends";
    var lo = document.createElement("span");
    var hi = document.createElement("span");
    var cap = document.createElement("div");
    cap.style.marginTop = "4px";

    if (state.diff) {
      /* THE COMPARISON'S OWN SCALE: the change since the earlier run,
         on the same diverging palette the anomaly uses - brown is less
         snow than the earlier run said, teal is more. */
      (man.anom_colors || []).forEach(function (c) {
        var i = document.createElement("i");
        i.style.background = c;
        bar.appendChild(i);
      });
      var run = (state.runs || []).filter(function (r) {
        return r.tag === state.tag && r.init === state.archive;
      })[0];
      var when = run ? initLabel(run.init) : "the earlier run";
      if (state.diff.kind === "anom") {
        lo.textContent = "-" + state.diff.scale.toFixed(1) + " sigma";
        hi.textContent = "+" + state.diff.scale.toFixed(1) + " sigma";
        cap.textContent = "The change since the " + when + " run - the " +
          "current run minus that run, in standard deviations of the " +
          "model's own hindcast climate (" + man.name + "). Brown is less " +
          "snow than the earlier run said, teal is more" +
          (windowLabel() ? " - " + windowLabel() + ", the 3-month mean" : "");
      } else {
        lo.textContent = "-" + state.diff.scale + " in";
        hi.textContent = "+" + state.diff.scale + " in";
        cap.textContent = "The change since the " + when + " run - the " +
          "current run minus that run, inches of snowfall (" + man.name +
          "), on a log scale so that a few hundredths of an inch still " +
          "shows" +
          (windowLabel() ? " - " + windowLabel() + ", 3-month total" : "");
      }
    } else if (state.field === "anom") {
      (man.anom_colors || []).forEach(function (c) {
        var i = document.createElement("i");
        i.style.background = c;
        bar.appendChild(i);
      });
      var s = man.anom_scale || 10;
      lo.textContent = "-" + s + " in";
      hi.textContent = "+" + s + " in";
      cap.textContent = "Snowfall anomaly against the model's own hindcast " +
        "climate (" + man.name + "), inches - brown is less " +
        "snow than the model expects, teal is more" +
        (windowLabel() ? " - " + windowLabel() + ", the 3-month mean" : "");
    } else {
      /* the bar: the ladder's intervals, the same boundaries the static
         panels' colour bar is drawn on, and the keys on those boundaries.
         The bar used to be 32 fixed-width blocks in a full-width row, so
         it stopped half way across and the keys sat on nothing. */
      var lv = man.levels || [];
      var nseg = Math.max(1, lv.length - 1);
      (man.colors || []).slice(0, nseg).forEach(function (c) {
        var i = document.createElement("i");
        i.style.background = c;
        bar.appendChild(i);
      });
      lo.textContent = man.levels[0] + " in";
      hi.textContent = man.levels[man.levels.length - 1] + " in";
      cap.textContent = "Accumulated snowfall, inches (" +
        man.name + ", " + man.members + " members" +
        (man.init ? ", " + man.init + " init" : "") +
        ") on the published 0-300 in scale" +
        (windowLabel() ? " - " + windowLabel() + ", 3-month total" : "");
      /* THE KEYS: the ladder's own levels, every other one - the same set
         the static panels' colour bar carries, on the same boundaries. */
      var keys = document.createElement("div");
      keys.className = "keys";
      for (var j = 0; j < lv.length; j += 2) {
        var sp = document.createElement("span");
        sp.textContent = (lv[j] < 1 && lv[j] !== 0.25 ? lv[j] : Math.round(lv[j]));
        sp.style.left = (j * 100 / nseg) + "%";
        if (j === 0) { sp.className = "first"; }
        keys.appendChild(sp);
      }
      wrap.appendChild(keys);
    }
    ends.appendChild(lo);
    ends.appendChild(hi);
    wrap.appendChild(bar);
    wrap.appendChild(ends);
    box.appendChild(wrap);
    box.appendChild(cap);
  }

  /* ---------------------------------------------------------------- */
  /* the tooltip                                                       */

  var tip = null;
  function showTip(ev, text, x, y) {
    if (!tip) { tip = el("maptip"); }
    tip.textContent = text;
    tip.style.left = (x + 14) + "px";
    tip.style.top = (y + 10) + "px";
    tip.style.display = "block";
  }
  function hideTip() { if (tip) { tip.style.display = "none"; } }

  function note(text) {
    var n = el("mapnote");
    if (n) { n.textContent = text; }
  }

  /* anything that goes wrong has to say so on the page - a map that is
     silently blank is worse than one that says it failed */
  function fail(text) {
    var n = el("mapload");
    if (n) {
      n.style.display = "block";
      n.textContent = text;
    }
    if (window.console) { console.error(text); }
  }

  /* ---------------------------------------------------------------- */
  /* drawing                                                          */

  /* ---------------------------------------------------------------- */
  /* the projection                                                     */

  /* d3 works out the scale and the translate: the map is fitted into the
     box exactly as it always was.  The zoom and the pan go on top of
     that, and the renderer is told where the centre of the projection
     is - which is the point the sphere is being looked from.

     d3's rotate() puts (-lambda, -phi) at the centre, and that is what
     mapgl.js works in. */
  function baseProjection(W, H) {
    var key = state.view + ":" + W + "x" + H;
    if (state.baseKey !== key) {
      var proj;
      if (state.view === "flat") {
        proj = d3.geoEquirectangular()
          .fitExtent([[10, 10], [W - 10, H - 10]], {type: "Sphere"});
      } else {
        proj = d3.geoOrthographic()
          .fitExtent([[10, 10], [W - 10, H - 10]], {type: "Sphere"})
          .rotate(state.rot);
      }
      state.base = {k: proj.scale(), t: proj.translate()};
      state.baseKey = key;
    }
    return state.base;
  }

  function projParams(W, H) {
    var b = baseProjection(W, H);
    var lam0 = 0, phi0 = 0;
    if (state.view === "globe") {
      lam0 = -state.rot[0] * Math.PI / 180;
      phi0 = -state.rot[1] * Math.PI / 180;
    }
    return {view: state.view, lam0: lam0, phi0: phi0,
            k: b.k * state.zoom,
            /* THE TILT, in radians for the renderer */
            tilt: state.tilt * Math.PI / 180,
            x0: b.t[0] + state.pan[0],
            y0: b.t[1] + state.pan[1]};
  }

  function mapHeight(W) {
    if (state.view === "flat") {
      /* the whole world is twice as wide as it is tall, so the flat map
         is given a 2:1 box: it fills the width of the page instead of
         sitting in a letterbox with empty ocean at the sides */
      return Math.round(Math.min(900, Math.max(320, W * 0.52)));
    }
    return Math.round(Math.min(640, Math.max(400, W * 0.64)));
  }

  /* ---------------------------------------------------------------- */
  /* the redraw                                                        */

  /* A drag fires far more events than the screen can show, and only the
     last one matters: the redraws are coalesced into one per frame. */
  function requestDraw() {
    if (state.pending) { return; }
    state.pending = true;
    requestAnimationFrame(function () {
      state.pending = false;
      draw();
    });
  }

  function draw() {
    if (!state.gl || !state.data.countries) { return; }
    var svg = d3.select("#mapsvg");
    var box = el("mapbox");
    /* The size of the box is read ONCE and cached: reading clientWidth
       every frame forces the browser to lay the page out again, which
       is exactly the kind of thing that makes a drag stutter.  The
       resize handler clears the cache. */
    if (!state.boxW) {
      state.boxW = Math.max(320, Math.round(box.clientWidth));
      state.svgW = null;
    }
    var W = state.boxW;
    var H = mapHeight(W);
    /* the SVG's size only changes when the box does: writing it on every
       frame makes the browser lay the page out again for nothing */
    if (state.svgW !== W || state.svgH !== H) {
      state.svgW = W; state.svgH = H;
      svg.attr("width", W).attr("height", H)
        .attr("viewBox", "0 0 " + W + " " + H);
    }

    var canvas = el("mapcanvas");
    if (canvas) {
      if (canvas.width !== W) { canvas.width = W; }
      if (canvas.height !== H) { canvas.height = H; }
      if (state.canvasW !== W || state.canvasH !== H) {
        state.canvasW = W; state.canvasH = H;
        canvas.style.width = W + "px";
        canvas.style.height = H + "px";
      }
    }
    /* the sky the globe floats in does not move when the globe spins,
       so it is painted once on the canvas behind it */
    var bg = el("mapbg");
    if (bg) {
      if (bg.width !== W) { bg.width = W; }
      if (bg.height !== H) { bg.height = H; }
      bg.style.width = W + "px";
      bg.style.height = H + "px";
      var key = state.view + ":" + W + "x" + H;
      if (state.view === "flat") {
        bg.getContext("2d").clearRect(0, 0, W, H);
        bg.setAttribute("data-painted", "");
      } else if (bg.getAttribute("data-painted") !== key) {
        paintSpace(bg.getContext("2d"), W, H);
        bg.setAttribute("data-painted", key);
      }
    }

    var params = projParams(W, H);
    state.params = params;
    state.gl.setProjection(params);
    state.gl.setMode(state.field === "anom" ? 1 : 0);
    state.gl.render();

    /* the pole, when it is on the near side of the globe */
    if (state.pole) {
      var pole = MapGL.projectPoint(0, Math.PI / 2, params);
      if (pole.z > 0) {
        state.pole.attr("cx", pole.x).attr("cy", pole.y)
          .style("display", null);
      } else {
        state.pole.style("display", "none");
      }
    }
    updateZoomLabel();
  }

  /* the field goes to the GPU as it is: the model's own grid, one byte
     a cell, and the published ladder's own table for the colours */
  function uploadField() {
    if (!state.gl || !state.raster || !state.manifest) { return; }
    var man = state.manifest;
    var g = man.grid;
    var span = g.nlon * g.dlon;
    state.gl.setField(state.raster.bytes, {
      lat0: g.lat0, dlat: g.dlat, lon0: g.lon0, dlon: g.dlon,
      nlat: g.nlat, nlon: g.nlon, isGlobal: span >= 359.5
    });
    state.gl.setBytes(state.raster.bytes);
    var bottom = MapGL.hexToRgb((man.colors || ["#ffffff"])[0]);
    /* the anomalies have a table of their own, built with the panels'
       own norm: the colour of a cell is decided by the value it stands
       for, not by where the byte sits in a ramp */
    var anomLut = (man.anom_lut && man.anom_lut.length === 256)
                  ? man.anom_lut : null;
    if (man.lut && man.lut.length === 256) {
      state.gl.setLut(man.lut, anomLut, bottom);
    } else {
      /* a manifest with no table of its own: build one from the ramp */
      var ramp = man.colors || man.ramp || [];
      var lut = [];
      for (var b = 0; b < 256; b++) {
        var i = Math.round(b / 254 * (ramp.length - 1));
        lut.push(ramp[Math.min(i, ramp.length - 1)]);
      }
      state.gl.setLut(lut, anomLut, bottom);
    }
    state.gl.setAnom(man.anom_colors || []);
  }

  /* the outlines and the earth, once */
  function buildGeometry() {
    if (!state.gl) { return; }
    state.gl.setGeometry(state.data.countries.features,
                         bigLakes(state.data.lakes).features,
                         state.data.states.features);
    state.gl.setSplitGeometry(state.data.countries.features,
                              bigLakes(state.data.lakes).features,
                              state.data.states.features);
    state.gl.setGraticule(MapGL.graticule10());
    bakeMask();
  }

  /* The tooltip reads the field under the pointer.

     A mousemove is what a drag is made of, so the work here is kept as
     small as it can be: the country under the pointer is found through
     a bounding-box index (not by walking every coastline in the world),
     and the tooltip itself is written once per frame rather than once
     per event, so a fast drag does not make the browser lay the page
     out a hundred times a second. */
  function setupTip(svg) {
    var pendingTip = null;
    var tipRaf = false;
    function flushTip() {
      tipRaf = false;
      if (!pendingTip) { return; }
      var t = pendingTip;
      pendingTip = null;
      showTip(t.ev, t.txt, t.x, t.y);
    }
    svg.on("mousemove", function (ev) {
      if (!state.gl || !state.raster || !state.manifest) {
        hideTip();
        return;
      }
      var p = d3.pointer(ev, svg.node());
      var hit = state.gl.pick(p[0], p[1]);
      if (hit.byte === null || hit.byte === undefined) {
        hideTip();
        return;
      }
      var v = hit.byte;
      var val = byteValue(v);
      var txt;
      if (state.field === "anom") {
        txt = (val === null) ? "no snow expected here"
          : ((val >= 0 ? "+" : "") + val.toFixed(1) +
             " in vs the model's own climate");
      } else {
        txt = (v < 0.5) ? "no snow" : (val.toFixed(1) + " in");
      }
      txt = Math.abs(hit.lat).toFixed(1) + (hit.lat >= 0 ? "N" : "S") + " " +
        Math.abs(hit.lon).toFixed(1) + (hit.lon >= 0 ? "E" : "W") + " · " + txt;
      pendingTip = {ev: ev, txt: txt, x: p[0], y: p[1]};
      if (!tipRaf) {
        tipRaf = true;
        requestAnimationFrame(flushTip);
      }
      /* the country under the pointer, in the house's amber */
      var h = MapGL.hitCountry(state.data.countries.features,
                               hit.lon, hit.lat);
      if (h !== state.hover) {
        state.hover = h;
        state.gl.setHover(h);
        requestDraw();
      }
    }).on("mouseleave", function () {
      hideTip();
      if (state.hover !== -1) {
        state.hover = -1;
        if (state.gl) { state.gl.setHover(-1); }
        requestDraw();
      }
    });
  }

  function load() {
    var todo = [];
    if (!state.data.countries) { todo.push(SRC.countries); }
    if (!state.data.lakes) { todo.push(SRC.lakes); }
    if (!state.data.land) { todo.push(SRC.land); }
    if (!state.data.states) { todo.push(SRC.states); }
    if (!todo.length) { draw(); return; }
    var n = el("mapload");
    if (n) { n.style.display = "block"; }
    Promise.all(todo.map(function (u) { return d3.json(u); }))
      .then(function (res) {
        var i = 0;
        if (!state.data.countries) { state.data.countries = res[i++]; }
        if (!state.data.lakes) { state.data.lakes = res[i++]; }
        if (!state.data.land) { state.data.land = res[i++]; }
        if (!state.data.states) { state.data.states = res[i++]; }
        var n2 = el("mapload");
        if (n2) { n2.style.display = "none"; }
        buildGeometry();
        draw();
      }).catch(function (e) {
        var n3 = el("mapload");
        if (n3) {
          n3.style.display = "block";
          n3.textContent = "The map data could not be loaded: " + e;
        }
      });
  }

  function setView(v) {
    state.view = v;
    state.pan = [0, 0];
    /* the tilt belongs to the globe it was made in */
    state.tilt = 0;
    state.tiltMode = false;
    state.hover = -1;
    var btns = document.querySelectorAll("#mapviews button");
    Array.prototype.forEach.call(btns, function (b) {
      b.classList.toggle("active", b.dataset.view === v);
    });
    var tb = document.querySelector(".mapctl [data-z='tilt']");
    if (tb) {
      tb.style.display = v === "globe" ? "" : "none";
      tb.classList.remove("on");
    }
    var box = el("mapbox");
    if (box) { box.className = "mapbox " + v; }
    var svg = d3.select("#mapsvg");
    setupInteraction(svg);
    setupTip(svg);
    viewNote();
    if (state.gl) {
      state.gl.setGraticule(MapGL.graticule10());
      state.gl.setHover(-1);
    }
    load();
  }

  function setField(f) {
    state.field = f;
    var btns = document.querySelectorAll("#snowfield button");
    Array.prototype.forEach.call(btns, function (b) {
      b.classList.toggle("on", b.dataset.field === f);
    });
    drawLegend();
    loadField();
  }

  function initSnow() {
    var msel = el("snowModel");
    d3.json("data/snowmap_tags.json").then(function (index) {
      state.index = index;
      if (!msel) { return; }
      index.forEach(function (m) {
        var o = document.createElement("option");
        o.value = m.tag;
        o.textContent = m.name + (m.init ? " (" + m.init + ")" : "");
        msel.appendChild(o);
      });
      msel.addEventListener("change", function () { loadModel(msel.value); });
      /* THE ARCHIVE: the runs that came before this one, so a reader can
         put an earlier run beside the current one.  The list is a separate
         file because the model index is about the models and this is
         about their runs. */
      d3.json("data/maps_index.json").then(function (runs) {
        state.runs = runs || [];
        buildArchivePicker();
      }).catch(function () {
        state.runs = [];
        buildArchivePicker();
      });
      var asel = el("snowArchive");
      if (asel) {
        asel.addEventListener("change", function () {
          setArchive(asel.value);
        });
      }
      /* THE PAGE OPENS ON THE MULTI-MODEL MEAN.  The index puts it first,
         but the page asks for it by name as well: the index on disk may be
         an older one, written before the mean existed or before it was
         given its climate, and a reader should still land on the mean
         whenever it is there.  If it is not there, the first model in the
         index is the fallback. */
      var def = null;
      for (var i = 0; i < index.length; i++) {
        if (index[i].tag === "c3s-multi") { def = index[i].tag; break; }
      }
      if (!def && index.length) { def = index[0].tag; }
      if (!def) { return; }
      msel.value = def;
      loadModel(def);
    }).catch(function () {});
  }

  function init() {
    if (typeof d3 === "undefined") { return; }
    var canvas = el("mapcanvas");
    try {
      state.gl = new MapGL.Renderer(canvas);
    } catch (e) {
      fail("This map needs WebGL2, which this browser does not have: " + e);
      return;
    }
    var btns = document.querySelectorAll("#mapviews button");
    Array.prototype.forEach.call(btns, function (b) {
      b.addEventListener("click", function () { setView(b.dataset.view); });
    });
    var fbtns = document.querySelectorAll("#snowfield button");
    Array.prototype.forEach.call(fbtns, function (b) {
      b.addEventListener("click", function () { setField(b.dataset.field); });
    });
    /* THE THREE-MONTH WINDOW: the house publishes the overlapping
       three-month windows of the run (NDJ, DJF, JFM, FMA) and the
       anomaly in them is the mean per month, so the map carries the same
       thing. */
    var wbtns = document.querySelectorAll("#snowwindow button");
    Array.prototype.forEach.call(wbtns, function (b) {
      b.addEventListener("click", function () {
        state.win3 = (b.dataset.window === "3");
        Array.prototype.forEach.call(wbtns, function (o) {
          o.classList.toggle("on", o === b);
        });
        /* the window belongs to a month: the run total has none, so the
           map moves to the first month that has one */
        if (state.win3 && !monthHasWindow(state.month)) {
          state.month = firstWindowMonth();
        }
        buildTimeline();
        loadField();
        drawLegend();
        draw();
      });
    });
    window.addEventListener("resize", function () {
      state.baseKey = null;
      state.boxW = null;      /* the box is measured again */
      state.svgW = null;
      requestDraw();
    });
    /* The box's width is cached, so something has to tell us when it
       changes.  A ResizeObserver does that on its own, and only when
       the size really changed. */
    if (window.ResizeObserver && el("mapbox")) {
      var ro = new ResizeObserver(function () {
        var box = el("mapbox");
        if (!box) { return; }
        var w = Math.max(320, Math.round(box.clientWidth));
        if (w !== state.boxW) {
          state.boxW = w;
          state.svgW = null;
          state.baseKey = null;
          requestDraw();
        }
      });
      ro.observe(el("mapbox"));
    }
    /* the keyboard, for the people who scroll with it */
    window.addEventListener("keydown", function (ev) {
      if (!ev.ctrlKey && !ev.metaKey && !ev.altKey) {
        if (ev.key === "+" || ev.key === "=") {
          setZoom(state.zoom * 1.25); ev.preventDefault();
        } else if (ev.key === "-" || ev.key === "_") {
          setZoom(state.zoom / 1.25); ev.preventDefault();
        } else if (ev.key === "0") {
          resetView(); ev.preventDefault();
        }
      }
    });
    /* a handle on the state, for the browser console */
    window.__maps = state;
    buildControls();
    initSnow();
    setView(state.view);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
