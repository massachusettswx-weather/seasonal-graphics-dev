/* ------------------------------------------------------------------
   Interactive Natural Earth maps for the seasonal graphics site.

   One map, one timeline.  The whole world, drawn from Natural Earth
   1:50m data that is committed to the repository, with the seasonal
   snowfall painted on it:

     2D Map   the flat world on an equirectangular grid
     3D Globe the same world on an orthographic globe you can spin
     Polar    the same world on a north polar projection - the whole
              Earth, centred on the pole

   The field is the model's OWN output - the whole world, at the grid the
   model came on, with no resampling - and it comes in two flavours: the
   accumulated snowfall, and the anomaly against that model's own
   hindcast climate.

   HOW THE FIELD IS DRAWN
   ----------------------
   The exporter writes each field as an 8-bit greyscale PNG, one byte per
   cell, on the model's own grid.  Here the PNG is decoded into a byte
   array and the map is painted PIXEL BY PIXEL: d3's projection can invert
   a screen point back to a longitude and a latitude, so every pixel of
   the canvas asks the projection where it is and samples the field
   there.

   That inverse is the expensive part, and the timeline makes it expensive
   a lot: moving along the months must not re-invert the map.  So the
   inverse is done ONCE per view and cached as a sampling plan - for
   every pixel, which cell it lands in and how far into it - and moving
   along the timeline then only re-reads the field and re-colours the
   pixels, which is fast.

   The earth itself (the ocean and the land) is painted on the same
   canvas underneath the field, with the coastlines drawn over it in the
   SVG above, so nothing is hidden by an opaque fill.
   ------------------------------------------------------------------ */
(function () {
  "use strict";

  var NE = "assets/ne/";
  var SRC = {
    countries: NE + "ne_50m_admin_0_countries.geojson",
    lakes: NE + "ne_50m_lakes.geojson",
    land: NE + "ne_50m_land.geojson"
  };

  /* the globe opens over North America, where the snowfall field is:
     d3's rotate() puts (-lambda, -phi) at the centre */
  var GLOBE_ROT = [95, -35];

  var state = {view: "globe", rot: GLOBE_ROT.slice(), prot: [0, -90],
               drag: null, zoom: 1,
               pan: [0, 0], field: "total", month: -1, tag: null,
               manifest: null, raster: null, plan: null, index: null,
               timer: null, data: {}};

  function el(id) { return document.getElementById(id); }

  /* ---------------------------------------------------------------- */
  /* the earth, painted under the field                               */

  var OCEAN = "#dce8f2";
  var LAND = "#f2ede0";

  function paintEarth(ctx, proj, W, H) {
    /* the ocean: the sphere, or the rectangle on the flat map */
    ctx.clearRect(0, 0, W, H);
    var path = d3.geoPath(proj, ctx);
    if (state.view === "flat") {
      ctx.fillStyle = OCEAN;
      ctx.fillRect(0, 0, W, H);
    } else {
      ctx.fillStyle = OCEAN;
      ctx.beginPath();
      path({type: "Sphere"});
      ctx.fill();
    }
    /* the land and the lakes, clipped to the sphere: on the polar
       projection Antarctica's ring runs right around the disc and would
       otherwise paint over the sky */
    ctx.save();
    ctx.beginPath();
    path({type: "Sphere"});
    ctx.clip();
    if (state.data.land) {
      ctx.fillStyle = LAND;
      ctx.beginPath();
      path(state.data.land);
      ctx.fill();
    }
    if (state.data.lakes) {
      ctx.fillStyle = OCEAN;
      ctx.beginPath();
      path(state.data.lakes);
      ctx.fill();
    }
    ctx.restore();
  }

  /* ---------------------------------------------------------------- */
  /* the sampling plan: the expensive part, done once per view         */

  function buildPlan(proj, W, H) {
    var man = state.manifest;
    var g = man.grid;
    var nlat = g.nlat, nlon = g.nlon;
    var plan = {W: W, H: H,
                i0: new Int32Array(W * H), j0: new Int32Array(W * H),
                fx: new Float32Array(W * H), fy: new Float32Array(W * H),
                ok: new Uint8Array(W * H)};
    var lat0 = g.lat0, dlat = g.dlat, lon0 = g.lon0, dlon = g.dlon;
    /* A field that does not cover the whole world must not be painted
       outside its own domain.  The longitude is checked against the
       model's own grid - in the model's own convention - and a pixel
       outside that box is left alone.  (A global field covers every
       longitude, so there the longitude wraps, which is what it must
       do.)  Without this the box of a regional field is smeared around
       the whole world, once round for every degree of longitude. */
    var span = nlon * dlon;
    var isGlobal = span >= 359.5;
    /* On the globe, d3's invert() answers for the WHOLE sphere - it does
       not clip to the visible hemisphere - so without this the field would
       be painted on the dark sky outside the limb, showing the far side of
       the world through the back of the planet.  The polar projection has
       the same problem: its disc is the northern hemisphere, and the
       azimuthal projection can invert the southern one as well. */
    var disc = null;
    if (state.view === "globe") {
      var t = proj.translate();
      disc = {cx: t[0], cy: t[1], r: proj.scale()};
    } else if (state.view === "polar") {
      var t2 = proj.translate();
      /* the equidistant azimuthal projection puts the equator at
         r = k * pi/2 */
      disc = {cx: t2[0], cy: t2[1], r: proj.scale() * Math.PI / 2};
    }
    for (var y = 0; y < H; y++) {
      for (var x = 0; x < W; x++) {
        if (disc) {
          var dx = x - disc.cx, dy = y - disc.cy;
          if (dx * dx + dy * dy > disc.r * disc.r) { continue; }
        }
        var ll = proj.invert([x, y]);
        if (!ll) { continue; }
        var lon = ll[0], lat = ll[1];
        if (lat > lat0 || lat < lat0 - (nlat - 1) * dlat) { continue; }
        var fi = (lat0 - lat) / dlat;
        var fj;
        if (isGlobal) {
          fj = ((lon - lon0) / dlon) % nlon;
          if (fj < 0) { fj += nlon; }
        } else {
          var la = lon;
          if (lon0 >= 0) {
            while (la < 0) { la += 360; }
            while (la >= 360) { la -= 360; }
          } else {
            while (la > 180) { la -= 360; }
            while (la < -180) { la += 360; }
          }
          if (la < lon0 - 1e-9 || la > lon0 + span - 1e-9) { continue; }
          fj = (la - lon0) / dlon;
          if (fj < 0) { fj += nlon; }
          if (fj >= nlon) { fj -= nlon; }
        }
        var i0 = Math.floor(fi);
        var j0 = Math.floor(fj);
        if (i0 < 0) { i0 = 0; }
        if (i0 > nlat - 2) { i0 = nlat - 2; }
        if (j0 > nlon - 2) { j0 = nlon - 2; }
        var k = y * W + x;
        plan.i0[k] = i0;
        plan.j0[k] = j0;
        plan.fy[k] = fi - i0;
        plan.fx[k] = fj - j0;
        plan.ok[k] = 1;
      }
    }
    return plan;
  }

  /* ---------------------------------------------------------------- */
  /* the field                                                         */

  /* the colour of a byte on the published ladder.

     The exporter ships the ladder's own table: byte -> colour, bucket for
     bucket, made with the same BoundaryNorm(clip=True) the static panels
     use.  So the map and the static panels are the same map - over the
     top of the ladder is the top colour, not a white hole, and a trace of
     snow is the bottom colour.  The old interpolated ramp of its own is
     only a fallback for a manifest that carries no table. */
  function rampIndex(byte, ramp) {
    if (byte >= 255) { return ramp.length - 1; }
    return Math.round(byte / 254 * (ramp.length - 1));
  }

  function anomIndex(byte, colors) {
    if (byte >= 255) { return -1; }          /* masked */
    return Math.round(byte / 254 * (colors.length - 1));
  }

  function hexToRgb(h) {
    return [parseInt(h.substr(1, 2), 16),
            parseInt(h.substr(3, 2), 16),
            parseInt(h.substr(5, 2), 16)];
  }

  function paintField(ctx, W, H) {
    var plan = state.plan, r = state.raster, man = state.manifest;
    if (!plan || !r) { return; }
    var nlon = man.grid.nlon;
    var base = ctx.getImageData(0, 0, W, H);
    var bp = base.data;
    var isAnom = state.field === "anom";
    /* the ladder table: byte -> the colour the static panels give it */
    var lutRGB = null;
    if (man.lut && man.lut.length === 256) {
      lutRGB = man.lut.map(hexToRgb);
    }
    var ramp = man.colors || man.ramp;
    var rampRGB = lutRGB || (ramp || []).map(hexToRgb);
    var anomRGB = (man.anom_colors || []).map(hexToRgb);
    var bytes = r.bytes;
    var alpha = isAnom ? 0.82 : 1.0;

    for (var y = 0; y < H; y++) {
      for (var x = 0; x < W; x++) {
        var k = y * W + x;
        if (!plan.ok[k]) { continue; }
        var i0 = plan.i0[k], j0 = plan.j0[k];
        var fx = plan.fx[k], fy = plan.fy[k];
        var a = bytes[i0 * nlon + j0];
        var b = bytes[i0 * nlon + Math.min(j0 + 1, nlon - 1)];
        var c = bytes[Math.min(i0 + 1, man.grid.nlat - 1) * nlon + j0];
        var d = bytes[Math.min(i0 + 1, man.grid.nlat - 1) * nlon +
                      Math.min(j0 + 1, nlon - 1)];
        var v = (1 - fx) * ((1 - fy) * a + fy * c) +
                fx * ((1 - fy) * b + fy * d);
        if (isAnom) {
          var ai = anomIndex(v, anomRGB);
          if (ai < 0) { continue; }          /* masked: no snow expected */
          if (v < 1.5 && v > 252.5) { continue; }   /* nothing to say */
          var col = anomRGB[ai];
        } else {
          if (v < 0.5) { continue; }          /* no snow */
          var col = lutRGB ? lutRGB[Math.min(255, Math.round(v))]
                           : rampRGB[rampIndex(v, ramp)];
        }
        var o = k * 4;
        bp[o] = col[0] * alpha + bp[o] * (1 - alpha);
        bp[o + 1] = col[1] * alpha + bp[o + 1] * (1 - alpha);
        bp[o + 2] = col[2] * alpha + bp[o + 2] * (1 - alpha);
        bp[o + 3] = 255;
      }
    }
    ctx.putImageData(base, 0, 0);
  }

  /* the value a byte stands for, for the tooltip */
  function byteValue(byte) {
    var man = state.manifest;
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
  /* the vector layer                                                  */

  function drawFlat(svg, proj, W, H) {
    var path = d3.geoPath(proj);
    svg.append("path").datum(d3.geoGraticule10()).attr("class", "grat")
      .attr("d", path);
    var g = svg.append("g");
    g.selectAll("path.country").data(state.data.countries.features)
      .join("path").attr("class", "country").attr("d", path);
    g.selectAll("path.lake").data(state.data.lakes.features)
      .join("path").attr("class", "lake").attr("d", path);

    /* the flat map is dragged to pan and scrolled to zoom */
    svg.call(d3.drag()
      .on("start", function (ev) { state.drag = d3.pointer(ev, this); })
      .on("drag", function (ev) {
        var p = d3.pointer(ev, this);
        var dx = p[0] - state.drag[0], dy = p[1] - state.drag[1];
        state.pan[0] += dx;
        state.pan[1] += dy;
        state.drag = p;
        state.plan = null;
        draw();
      }));
    svg.on("wheel", function (ev) {
      ev.preventDefault();
      zoomAt(ev, ev.deltaY < 0 ? 1.15 : 1 / 1.15);
    });
    note("The whole world on an equirectangular grid. Drag it to pan, " +
         "scroll or use the buttons to zoom. The equirectangular " +
         "projection squeezes the polar regions, which is why the polar " +
         "view exists.");
  }

  function drawGlobe(svg, proj, W, H) {
    var path = d3.geoPath(proj);
    var defs = svg.append("defs");
    var grad = defs.append("radialGradient")
      .attr("id", "atmosgrad").attr("cx", "50%").attr("cy", "50%")
      .attr("r", "50%");
    grad.append("stop").attr("offset", "62%").attr("stop-color", "#3d8fe8")
      .attr("stop-opacity", 0);
    grad.append("stop").attr("offset", "82%").attr("stop-color", "#4f9df0")
      .attr("stop-opacity", .35);
    grad.append("stop").attr("offset", "93%").attr("stop-color", "#79b9ff")
      .attr("stop-opacity", .75);
    grad.append("stop").attr("offset", "100%").attr("stop-color", "#a8d2ff")
      .attr("stop-opacity", 0);
    svg.append("circle").attr("class", "atmos")
      .attr("cx", W / 2).attr("cy", H / 2).attr("r", path({type: "Sphere"}).length * 1.16)
      .attr("fill", "url(#atmosgrad)");

    svg.append("path").datum(d3.geoGraticule10()).attr("class", "grat")
      .attr("d", path);
    var g = svg.append("g");
    g.selectAll("path.country").data(state.data.countries.features)
      .join("path").attr("class", "country").attr("d", path);
    g.selectAll("path.lake").data(state.data.lakes.features)
      .join("path").attr("class", "lake").attr("d", path);

    /* the pole, when it is on the near side of the globe */
    var pole = proj([0, 90]);
    if (pole) {
      svg.append("circle").attr("class", "pole")
        .attr("cx", pole[0]).attr("cy", pole[1]).attr("r", 3);
    }

    /* the globe is dragged to spin */
    svg.call(d3.drag()
      .on("start", function (ev) { state.drag = d3.pointer(ev, this); })
      .on("drag", function (ev) {
        var p = d3.pointer(ev, this);
        var dx = p[0] - state.drag[0], dy = p[1] - state.drag[1];
        state.rot[0] += dx * 0.45;
        state.rot[1] = Math.max(-90, Math.min(90, state.rot[1] - dy * 0.45));
        state.drag = p;
        state.plan = null;
        draw();
      }));

    svg.on("wheel", function (ev) {
      ev.preventDefault();
      zoomAt(ev, ev.deltaY < 0 ? 1.15 : 1 / 1.15);
    });

    note("The same world on an orthographic globe - drag it to spin, scroll " +
         "or use the buttons to zoom.");
  }

  function drawPolar(svg, proj, W, H) {
    var path = d3.geoPath(proj);
    var g = svg.append("g");
    g.selectAll("path.country").data(state.data.countries.features)
      .join("path").attr("class", "country").attr("d", path);
    g.selectAll("path.lake").data(state.data.lakes.features)
      .join("path").attr("class", "lake").attr("d", path);
    var grat = {type: "MultiLineString", coordinates: []};
    [60, 30].forEach(function (lat) {
      var c = [];
      for (var i = 0; i <= 360; i++) { c.push([i % 360, lat]); }
      grat.coordinates.push(c);
    });
    for (var lon = 0; lon < 360; lon += 30) {
      grat.coordinates.push([[lon, 60], [lon, 90]]);
    }
    svg.append("path").datum(grat).attr("class", "grat").attr("d", path);

    /* the polar view is dragged to spin around the pole */
    svg.call(d3.drag()
      .on("start", function (ev) { state.drag = d3.pointer(ev, this); })
      .on("drag", function (ev) {
        var p = d3.pointer(ev, this);
        var dx = p[0] - state.drag[0];
        state.prot[0] = (state.prot[0] + dx * 0.5) % 360;
        state.drag = p;
        state.plan = null;
        draw();
      }));
    svg.on("wheel", function (ev) {
      ev.preventDefault();
      zoomAt(ev, ev.deltaY < 0 ? 1.15 : 1 / 1.15);
    });

    note("The whole world on a north polar projection: the pole at the " +
         "centre, every continent radiating from it. Drag it to spin around " +
         "the pole, scroll or use the buttons to zoom.");
  }

  /* ---------------------------------------------------------------- */
  /* the zoom                                                          */

  /* The zoom is the one thing a world map cannot do without: the field
     is the model's own grid, so a 1 degree model has to be looked at
     from close up to be worth looking at.  Every view can be zoomed
     (the buttons, the scroll wheel, or the keyboard) and the flat map
     can be panned. */

  var ZOOM_MIN = 1, ZOOM_MAX = 12;

  function setZoom(z) {
    state.zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
    state.plan = null;
    draw();
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
    state.plan = null;
    draw();
  }

  function resetView() {
    state.zoom = 1;
    state.pan = [0, 0];
    state.rot = GLOBE_ROT.slice();
    state.prot = [0, -90];
    state.plan = null;
    draw();
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
      '<button type="button" data-z="reset" title="reset the view">⟲</button>';
    box.appendChild(c);
    c.addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest("button") : null;
      if (!b) { return; }
      ev.preventDefault();
      ev.stopPropagation();
      var z = b.getAttribute("data-z");
      if (z === "in") { setZoom(state.zoom * 1.35); }
      else if (z === "out") { setZoom(state.zoom / 1.35); }
      else { resetView(); }
    });
    c.addEventListener("wheel", function (ev) { ev.stopPropagation(); },
                      {passive: true});
  }

  function updateZoomLabel() {
    var l = document.querySelector(".mapctl .zlabel");
    if (l) { l.textContent = Math.round(state.zoom * 100) + "%"; }
  }

  /* ---------------------------------------------------------------- */
  /* the field files                                                   */

  function fieldFile() {
    var man = state.manifest;
    if (!man) { return null; }
    var f = state.field === "anom" ? "anom" : "total";
    if (state.month < 0) { return man.total[f]; }
    var m = man.months[state.month];
    return m ? m[f] : null;
  }

  function loadField() {
    var file = fieldFile();
    if (!file) { return; }
    var img = new Image();
    img.onload = function () {
      var c = document.createElement("canvas");
      c.width = img.width; c.height = img.height;
      var ctx = c.getContext("2d");
      ctx.drawImage(img, 0, 0);
      var data = ctx.getImageData(0, 0, img.width, img.height).data;
      var bytes = new Uint8Array(img.width * img.height);
      for (var i = 0, j = 0; i < bytes.length; i++, j += 4) {
        bytes[i] = data[j];
      }
      state.raster = {w: img.width, h: img.height, bytes: bytes};
      draw();
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

  function loadModel(tag) {
    state.tag = tag;
    state.manifest = null;
    state.raster = null;
    state.plan = null;
    state.month = -1;
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

    var mk = function (label, month, value) {
      var b = document.createElement("button");
      b.className = "tlbtn" + (state.month === value ? " on" : "");
      b.textContent = label;
      b.dataset.month = String(value);
      b.addEventListener("click", function () {
        stopPlay();
        state.month = value;
        markTimeline();
        loadField();
      });
      box.appendChild(b);
    };
    mk("Total", -1, -1);
    man.months.forEach(function (m, i) { mk(m.label, i, i); });
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
    state.timer = setInterval(function () {
      var m = state.manifest;
      if (!m) { stopPlay(); return; }
      var n = state.month + 1;
      if (n > m.months.length - 1) { stopPlay(); return; }
      state.month = n;
      markTimeline();
      loadField();
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

    if (state.field === "anom") {
      (man.anom_colors || []).forEach(function (c) {
        var i = document.createElement("i");
        i.style.background = c;
        bar.appendChild(i);
      });
      var s = man.anom_scale || 10;
      lo.textContent = "-" + s + " in";
      hi.textContent = "+" + s + " in";
      cap.textContent = "Snowfall anomaly against the model's own hindcast " +
        "climate (" + man.name + "), inches of snow depth - brown is less " +
        "snow than the model expects, teal is more";
    } else {
      (man.colors || man.ramp || []).forEach(function (c) {
        var i = document.createElement("i");
        i.style.background = c;
        bar.appendChild(i);
      });
      lo.textContent = man.levels[0] + " in";
      hi.textContent = man.levels[man.levels.length - 1] + " in of snow";
      cap.textContent = "Accumulated snowfall, inches of snow depth (" +
        man.name + ", " + man.members + " members" +
        (man.init ? ", " + man.init + " init" : "") +
        ") on the published 0-300 in snow-depth scale";
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

  function makeProjection(W, H) {
    var proj;
    if (state.view === "flat") {
      proj = d3.geoEquirectangular()
        .fitExtent([[10, 10], [W - 10, H - 10]], {type: "Sphere"});
    } else if (state.view === "globe") {
      proj = d3.geoOrthographic()
        .fitExtent([[10, 10], [W - 10, H - 10]], {type: "Sphere"})
        .rotate(state.rot);
    } else {
      proj = d3.geoAzimuthalEquidistant()
        .rotate(state.prot)
        .fitExtent([[10, 10], [W - 10, H - 10]], {type: "Sphere"});
    }
    /* the zoom: the scale goes up about the centre of the projection, and
       the flat map can then be panned away from that centre */
    if (state.zoom !== 1) {
      proj.scale(proj.scale() * state.zoom);
    }
    if (state.pan[0] || state.pan[1]) {
      var t = proj.translate();
      proj.translate([t[0] + state.pan[0], t[1] + state.pan[1]]);
    }
    return proj;
  }

  function draw() {
    if (!state.data.countries) { return; }
    var svg = d3.select("#mapsvg");
    svg.selectAll("*").remove();
    var box = el("mapbox");
    var W = Math.max(320, Math.round(box.clientWidth));
    var H;
    if (state.view === "flat") {
      /* the whole world is twice as wide as it is tall, so the flat map
         is given a 2:1 box: it fills the width of the page instead of
         sitting in a letterbox with empty ocean at the sides */
      H = Math.round(Math.min(900, Math.max(320, W * 0.52)));
    } else if (state.view === "polar") {
      H = Math.round(Math.min(720, Math.max(380, W * 0.64)));
    } else {
      H = Math.round(Math.min(640, Math.max(400, W * 0.64)));
    }
    svg.attr("width", W).attr("height", H)
      .attr("viewBox", "0 0 " + W + " " + H);

    var canvas = el("mapcanvas");
    if (canvas) {
      canvas.width = W;
      canvas.height = H;
      canvas.style.width = W + "px";
      canvas.style.height = H + "px";
    }

    var proj = makeProjection(W, H);
    if (state.manifest && !state.plan) {
      state.plan = buildPlan(proj, W, H);
    }
    if (canvas) {
      var ctx = canvas.getContext("2d");
      paintEarth(ctx, proj, W, H);
      paintField(ctx, W, H);
    }

    if (state.view === "flat") { drawFlat(svg, proj, W, H); }
    else if (state.view === "globe") { drawGlobe(svg, proj, W, H); }
    else { drawPolar(svg, proj, W, H); }
    updateZoomLabel();

    /* the tooltip reads the field under the pointer */
    svg.on("mousemove", function (ev) {
      if (!state.plan || !state.raster) { hideTip(); return; }
      var p = d3.pointer(ev, svg.node());
      var k = Math.round(p[1]) * state.plan.W + Math.round(p[0]);
      if (k < 0 || k >= state.plan.W * state.plan.H || !state.plan.ok[k]) {
        hideTip();
        return;
      }
      var ll = proj.invert(p);
      if (!ll) { hideTip(); return; }
      var nlon = state.manifest.grid.nlon;
      var i0 = state.plan.i0[k], j0 = state.plan.j0[k];
      var v = state.raster.bytes[i0 * nlon + j0];
      var val = byteValue(v);
      var txt;
      if (state.field === "anom") {
        txt = (val === null) ? "no snow expected here"
          : ((val >= 0 ? "+" : "") + val.toFixed(1) +
             " in vs the model's own climate");
      } else {
        txt = (v < 0.5) ? "no snow" : (val.toFixed(1) + " in of snow");
      }
      txt = Math.abs(ll[1]).toFixed(1) + (ll[1] >= 0 ? "N" : "S") + " " +
        Math.abs(ll[0]).toFixed(1) + (ll[0] >= 0 ? "E" : "W") + " · " + txt;
      showTip(ev, txt, p[0], p[1]);
    }).on("mouseleave", hideTip);
  }

  function load() {
    var todo = [];
    if (!state.data.countries) { todo.push(SRC.countries); }
    if (!state.data.lakes) { todo.push(SRC.lakes); }
    if (!state.data.land) { todo.push(SRC.land); }
    if (!todo.length) { draw(); return; }
    var n = el("mapload");
    if (n) { n.style.display = "block"; }
    Promise.all(todo.map(function (u) { return d3.json(u); }))
      .then(function (res) {
        var i = 0;
        if (!state.data.countries) { state.data.countries = res[i++]; }
        if (!state.data.lakes) { state.data.lakes = res[i++]; }
        if (!state.data.land) { state.data.land = res[i++]; }
        var n2 = el("mapload");
        if (n2) { n2.style.display = "none"; }
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
    state.plan = null;
    state.pan = [0, 0];
    var btns = document.querySelectorAll("#mapviews button");
    Array.prototype.forEach.call(btns, function (b) {
      b.classList.toggle("active", b.dataset.view === v);
    });
    var box = el("mapbox");
    if (box) { box.className = "mapbox " + v; }
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
      index.forEach(function (m, i) {
        var o = document.createElement("option");
        o.value = m.tag;
        o.textContent = m.name + (m.init ? " (" + m.init + ")" : "");
        if (i === 0) { o.selected = true; }
        msel.appendChild(o);
      });
      msel.addEventListener("change", function () { loadModel(msel.value); });
      if (index.length) { loadModel(index[0].tag); }
    }).catch(function () {});
  }

  function init() {
    if (typeof d3 === "undefined") { return; }
    var btns = document.querySelectorAll("#mapviews button");
    Array.prototype.forEach.call(btns, function (b) {
      b.addEventListener("click", function () { setView(b.dataset.view); });
    });
    var fbtns = document.querySelectorAll("#snowfield button");
    Array.prototype.forEach.call(fbtns, function (b) {
      b.addEventListener("click", function () { setField(b.dataset.field); });
    });
    window.addEventListener("resize", function () {
      state.plan = null;
      draw();
    });
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
