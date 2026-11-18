/* ------------------------------------------------------------------
   The WebGL2 renderer for the seasonal world map.

   THE MAP IS THE STATIC MAP.  Whatever else happens here, the field is
   the model's OWN grid, the colours are the published ladder's own
   256-entry table, and every cell is decided exactly as the static
   panels decide it: the same byte, the same bucket, the same colour.
   The only thing that changed is HOW the map is drawn.

   WHY THIS FILE EXISTS
   --------------------
   The first version of this map asked d3 where every single pixel was.
   A big map is 1.3 million pixels, so a redraw cost two million
   projections - about two seconds - and the vector layer was rebuilt
   from 120 000 coastline points on every frame of a drag as well.  The
   whole frame cost about three and a third seconds: the map was a
   slideshow, and dragging it at high zoom was hopeless.

   Here the GPU does that work:

     * the fragment shader works out where each pixel is on the globe
       and reads the model's own grid there, with the same bilinear
       arithmetic the CPU version used, so the colours are unchanged;
     * the coastlines are GPU lines built from the same geometry, with
       the horizon cut exactly where the sphere's limb is;
     * the earth (sea, land, lakes) is a mask baked once into an
       equirectangular texture, so the sea and the land cost nothing
       per frame.

   A frame is now two draw calls and a handful of uniforms.
   ------------------------------------------------------------------ */
(function (global) {
  "use strict";

  var DEG = Math.PI / 180;
  var PI = Math.PI;

  /* ---------------------------------------------------------------- */
  /* the projection                                                     */

  /* d3 works out the scale and the translate and says where the centre
     of the projection is; this is the spherical geometry that goes with
     them, in the same terms d3 uses (the projected coordinates have y
     up, and the screen has y down).

     The centre of the projection is the point (lam0, phi0).  In the
     frame centred on it a point (lam, phi) has the components

         X = cos(phi) sin(lam - lam0)          east
         Y = cos(phi0) sin(phi)
             - sin(phi0) cos(phi) cos(lam-lam0)   north
         Z = sin(phi0) sin(phi)
             + cos(phi0) cos(phi) cos(lam-lam0)   towards the centre

     and d3's raw projections are the orthographic (X, Y) and the
     azimuthal equidistant (d/sin d)(X, Y) with d = acos(Z).  The
     equirectangular one is the plain (lam, phi). */

  function projectPoint(lam, phi, p) {
    var cp = Math.cos(phi), sp = Math.sin(phi);
    var dlam = lam - p.lam0;
    var cd = Math.cos(dlam), sd = Math.sin(dlam);
    var cl0 = Math.cos(p.phi0), sl0 = Math.sin(p.phi0);
    var X = cp * sd;
    var Y = cl0 * sp - sl0 * cp * cd;
    var Z = sl0 * sp + cl0 * cp * cd;
    var px, py;
    if (p.view === "flat") {
      px = lam; py = phi; Z = 1;
    } else if (p.view === "globe") {
      px = X; py = Y;
    } else {
      var d = Math.acos(Math.max(-1, Math.min(1, Z)));
      var ss = Math.sin(d);
      var kk = (d < 1e-9) ? 0 : ((Math.abs(ss) < 1e-9) ? 1e9 : d / ss);
      px = kk * X; py = kk * Y;
    }
    return {x: p.x0 + p.k * px, y: p.y0 - p.k * py, z: Z};
  }

  /* the other way: where is this pixel?  The inverse of the above, in
     the same order d3 does it: un-scale, invert the raw projection,
     then come back from the centred frame to the geographic
     coordinates. */
  function invertPoint(x, y, p) {
    var px = (x - p.x0) / p.k;
    var py = (p.y0 - y) / p.k;
    if (p.view === "flat") {
      return {lon: px / DEG, lat: py / DEG};
    }
    var z = Math.sqrt(px * px + py * py);
    /* off the globe there is no point to invert: the far side of the
       world is not behind the limb, it is nowhere */
    if (p.view === "globe" && z > 1) { return {lon: NaN, lat: NaN}; }
    if (p.view === "polar" && z > Math.PI) { return {lon: NaN, lat: NaN}; }
    var c = (p.view === "globe") ? Math.asin(Math.max(-1, Math.min(1, z))) : z;
    var sc = Math.sin(c), cc = Math.cos(c);
    var lam1 = Math.atan2(px * sc, z * cc);
    var phi1 = (z > 0) ? Math.asin(Math.max(-1, Math.min(1, py * sc / z))) : 0;
    /* the centred frame back to the geographic coordinates */
    var cl = Math.cos(lam1), sl = Math.sin(lam1);
    var cp = Math.cos(phi1), sp = Math.sin(phi1);
    var sl0 = Math.sin(p.lam0), cl0 = Math.cos(p.lam0);
    var sp0 = Math.sin(p.phi0), cp0 = Math.cos(p.phi0);
    var Px = -sl0 * (cp * sl) + (-sp0 * cl0) * sp + (cp0 * cl0) * (cp * cl);
    var Py = cl0 * (cp * sl) + (-sp0 * sl0) * sp + (cp0 * sl0) * (cp * cl);
    var Pz = cp0 * sp + sp0 * (cp * cl);
    return {lon: Math.atan2(Py, Px) / DEG,
            lat: Math.asin(Math.max(-1, Math.min(1, Pz))) / DEG};
  }

  /* ---------------------------------------------------------------- */
  /* the shaders                                                       */

  var VERT_QUAD = `#version 300 es
precision highp float;
layout(location=0) in vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }`;

  /* the earth and the field: one pass over every pixel */
  var FRAG_EARTH = `#version 300 es
precision highp float;
precision highp sampler2D;

uniform vec2  u_res;
uniform int   u_view;        /* 0 flat, 1 globe, 2 polar */
uniform vec2  u_centre;      /* lam0, phi0, radians */
uniform float u_k;           /* the scale, px per projected unit */
uniform vec2  u_trans;       /* x0, y0, px */
uniform sampler2D u_mask;    /* R = land, G = lakes */
uniform sampler2D u_field;   /* the model's own grid, one byte a cell */
uniform sampler2D u_lut;     /* 256 x 2: row 0 the totals' ladder,
                                  row 1 the anomalies' table */
uniform float u_hasAnomLut;  /* 1 when the anomalies' table is there */
uniform vec3  u_anom[16];    /* the house palette for the anomaly */
uniform int   u_anomN;
uniform int   u_mode;        /* 0 = the totals, 1 = the anomaly */
uniform vec4  u_grid;        /* lat0, dlat, lon0, dlon, degrees */
uniform vec4  u_grid2;       /* nlat, nlon, isGlobal, span */
uniform vec3  u_ocean;
uniform vec3  u_land;
uniform float u_atmos;       /* the atmosphere's radius in px, 0 = none */

out vec4 frag;

const float PI = 3.141592653589793;
const float DEGR = 0.017453292519943;

/* the centred frame back to the geographic coordinates */
vec2 frameToGeo(float lam1, float phi1) {
  float cl = cos(lam1), sl = sin(lam1);
  float cp = cos(phi1), sp = sin(phi1);
  float sl0 = sin(u_centre.x), cl0 = cos(u_centre.x);
  float sp0 = sin(u_centre.y), cp0 = cos(u_centre.y);
  vec3 east  = vec3(-sl0, cl0, 0.0);
  vec3 north = vec3(-sp0 * cl0, -sp0 * sl0, cp0);
  vec3 up    = vec3(cp0 * cl0, cp0 * sl0, sp0);
  vec3 P = east * (cp * sl) + north * sp + up * (cp * cl);
  return vec2(atan(P.y, P.x), asin(clamp(P.z, -1.0, 1.0)));
}

/* where is this pixel? */
vec2 invert(vec2 sp) {
  vec2 p = vec2((sp.x - u_trans.x) / u_k, (u_trans.y - sp.y) / u_k);
  if (u_view == 0) { return p; }
  float z = length(p);
  float c = (u_view == 1) ? asin(clamp(z, -1.0, 1.0)) : z;
  float sc = sin(c), cc = cos(c);
  float lam1 = atan(p.x * sc, z * cc);
  float phi1 = (z > 0.0) ? asin(clamp(p.y * sc / z, -1.0, 1.0)) : 0.0;
  return frameToGeo(lam1, phi1);
}

void main() {
  vec2 sp = vec2(gl_FragCoord.x, u_res.y - gl_FragCoord.y);
  float r = length(sp - u_trans);
  vec4 outc = vec4(0.0);
  /* the sea: the sphere on the globe, the whole disc on the polar
     projection, and the whole rectangle on the flat map */
  float oceanR = 1e9;
  if (u_view == 1) { oceanR = u_k; }
  else if (u_view == 2) { oceanR = u_k * PI; }
  if (r <= oceanR) {
    vec2 ll = invert(sp);
    vec3 e = u_ocean;
    if (!isnan(ll.x) && !isinf(ll.x)) {
      float lon = ll.x / DEGR;
      float lat = ll.y / DEGR;
      /* the earth: the mask is the sea and the land, baked once */
      vec2 muv = vec2((lon + 180.0) / 360.0, (90.0 - lat) / 180.0);
      vec4 mk = texture(u_mask, muv);
      e = mix(e, u_land, mk.r);
      e = mix(e, u_ocean, mk.g);
      /* THE FIELD: the model's own grid, sampled with the same
         arithmetic the CPU version used - the same four cells, the
         same weights, the same published table - so the map IS the
         static map and not merely a map of the same data. */
      bool fieldOK = !(u_view == 2 && r > u_k * PI * 0.5);
      if (fieldOK) {
        float glat0 = u_grid.x;
        float gdlat = u_grid.y;
        float glon0 = u_grid.z;
        float gdlon = u_grid.w;
        float gnlat = u_grid2.x;
        float gnlon = u_grid2.y;
        /* a field that does not cover the whole world must not be
           painted outside its own box */
        float glo = mod(lon + 360.0, 360.0);
        if (u_grid2.z < 0.5 && glon0 < 0.0 && glo > 180.0) { glo = glo - 360.0; }
        bool inBox = (u_grid2.z > 0.5) ||
                     (glo >= glon0 - 1e-9 &&
                      glo <= glon0 + gnlon * gdlon - 1e-9);
        if (lat <= glat0 && lat >= glat0 - (gnlat - 1.0) * gdlat && inBox) {
          float gfi = (glat0 - lat) / gdlat;
          float gfj = mod((lon - glon0) / gdlon, gnlon);
          if (gfj < 0.0) { gfj = gfj + gnlon; }
          float gi0 = floor(gfi);
          float gj0 = floor(gfj);
          if (gi0 < 0.0) { gi0 = 0.0; }
          if (gi0 > gnlat - 2.0) { gi0 = gnlat - 2.0; }
          if (gj0 < 0.0) { gj0 = 0.0; }
          if (gj0 > gnlon - 2.0) { gj0 = gnlon - 2.0; }
          float gfx = gfj - gj0;
          float gfy = gfi - gi0;
          int gI = int(gi0);
          int gJ = int(gj0);
          int gI1 = int(min(gi0 + 1.0, gnlat - 1.0));
          int gJ1 = int(min(gj0 + 1.0, gnlon - 1.0));
          /* the four cells, read as they are: the texture is sampled
             with NEAREST, so each one is the cell's own byte and the
             weighting below is ours */
          float ga = texelFetch(u_field, ivec2(gJ, gI), 0).r * 255.0;
          float gb = texelFetch(u_field, ivec2(gJ1, gI), 0).r * 255.0;
          float gc = texelFetch(u_field, ivec2(gJ, gI1), 0).r * 255.0;
          float gd = texelFetch(u_field, ivec2(gJ1, gI1), 0).r * 255.0;
          float gv = (1.0 - gfx) * ((1.0 - gfy) * ga + gfy * gc) +
                     gfx * ((1.0 - gfy) * gb + gfy * gd);
          vec4 fc = vec4(0.0);
          if (u_mode == 1) {
            /* the anomaly against the model's own climate: 255 is the
               mask, where the model's own climate expects no snow.  The
               colour comes out of the panels' own table, so the anomaly
               on the map is the anomaly on the panel. */
            if (gv < 255.0) {
              int gai = int(clamp(floor(gv + 0.5), 0.0, 254.0));
              if (u_hasAnomLut > 0.5) {
                vec4 acol = texture(u_lut, vec2((float(gai) + 0.5) / 256.0, 0.75));
                fc = vec4(acol.rgb, acol.a);
              } else {
                int gaj = int(clamp(floor(gv / 254.0 * float(u_anomN - 1) + 0.5),
                                    0.0, float(u_anomN - 1)));
                fc = vec4(u_anom[gaj], 0.82);
              }
            }
          } else {
            /* the totals: the ladder's own table, so the map and the
               static panels are the same map */
            if (gv >= 0.5) {
              int gbi = int(clamp(floor(gv + 0.5), 0.0, 255.0));
              vec4 gcol = texture(u_lut, vec2((float(gbi) + 0.5) / 256.0, 0.25));
              fc = vec4(gcol.rgb, gcol.a);
            }
          }
          if (fc.a > 0.0) { e = fc.rgb * fc.a + e * (1.0 - fc.a); }
        }
      }
    }
    outc = vec4(e, 1.0);
  }
  /* the atmosphere: a soft rim of light round the limb, so the globe
     never dissolves into the background */
  if (u_atmos > 0.0) {
    /* the rim of light round the limb: OUTSIDE the globe.  A veil over
       the disc itself would wash out the field's own colours, and the
       field is the map. */
    float tt = r / u_k;             /* 1.0 at the edge of the disc */
    if (tt >= 1.0 && tt <= 1.16) {
      float f = (tt - 1.0) / 0.16;
      vec3 c = mix(vec3(0.3098, 0.6157, 0.9412), vec3(0.6588, 0.8235, 1.0), f);
      float a = sin(f * PI) * 0.6;   /* nothing at either end */
      outc.rgb = c * a + outc.rgb * (1.0 - a);
      outc.a = a + outc.a * (1.0 - a);
    }
  }
  frag = outc;
}`;

  /* the vectors: a line is a quad on the screen, with the horizon cut
     where the segment crosses the limb of the globe */
  var VERT_LINE = `#version 300 es
precision highp float;
layout(location=0) in vec2 a_corner;   /* (side, end) */
layout(location=1) in vec4 a_seg;      /* lonA, latA, lonB, latB, degrees */
layout(location=2) in float a_dist;    /* the distance along the line at A */

uniform vec2  u_res;
uniform int   u_view;
uniform vec2  u_centre;
uniform float u_k;
uniform vec2  u_trans;
uniform float u_width;

out float v_cross;
out float v_dist;

const float PI = 3.141592653589793;
const float DEGR = 0.017453292519943;

vec3 forward(vec2 ll) {
  float lam = ll.x * DEGR, phi = ll.y * DEGR;
  float cp = cos(phi), sp = sin(phi);
  float dlam = lam - u_centre.x;
  float cd = cos(dlam), sd = sin(dlam);
  float cl0 = cos(u_centre.y), sl0 = sin(u_centre.y);
  float X = cp * sd;
  float Y = cl0 * sp - sl0 * cp * cd;
  float Z = sl0 * sp + cl0 * cp * cd;
  vec2 pr;
  if (u_view == 0) { pr = vec2(lam, phi); Z = 1.0; }
  else if (u_view == 1) { pr = vec2(X, Y); }
  else {
    float d = acos(clamp(Z, -1.0, 1.0));
    float ss = sin(d);
    float kk = (d < 1e-9) ? 0.0 : ((abs(ss) < 1e-9) ? 1e9 : d / ss);
    pr = vec2(kk * X, kk * Y);
  }
  return vec3(u_trans.x + u_k * pr.x, u_trans.y - u_k * pr.y, Z);
}

void main() {
  vec3 A = forward(a_seg.xy);
  vec3 B = forward(a_seg.zw);
  if (u_view == 1) {
    float za = A.z, zb = B.z;
    if (za < 0.0 && zb < 0.0) {
      /* the far side of the world: off the screen altogether */
      gl_Position = vec4(0.0, 0.0, 2.0, 1.0);
      v_cross = 0.0; v_dist = 0.0;
      return;
    }
    if (za < 0.0) {
      float t = za / (za - zb);
      A = mix(A, B, t);
    } else if (zb < 0.0) {
      float t = za / (za - zb);
      B = mix(A, B, t);
    }
  }
  vec2 p = (a_corner.y < 0.5) ? A.xy : B.xy;
  vec2 dv = B.xy - A.xy;
  float len = length(dv);
  vec2 dir = (len > 1e-6) ? dv / len : vec2(1.0, 0.0);
  vec2 nrm = vec2(-dir.y, dir.x);
  float hw = u_width * 0.5 + 0.75;
  vec2 q = p + nrm * a_corner.x * hw;
  v_cross = a_corner.x * hw;
  v_dist = a_dist + a_corner.y * len;
  gl_Position = vec4(q.x / u_res.x * 2.0 - 1.0, 1.0 - q.y / u_res.y * 2.0,
                     0.0, 1.0);
}`;

  var FRAG_LINE = `#version 300 es
precision highp float;
in float v_cross;
in float v_dist;
uniform vec3  u_colour;
uniform float u_width;
uniform float u_dashOn;
uniform float u_dashPeriod;
out vec4 frag;
void main() {
  float d = abs(v_cross);
  float cov = clamp(u_width * 0.5 + 0.5 - d, 0.0, 1.0);
  if (u_dashPeriod > 0.0) {
    float m = mod(v_dist, u_dashPeriod);
    if (m > u_dashOn) { cov = 0.0; }
  }
  if (cov <= 0.0) { discard; }
  frag = vec4(u_colour * cov, cov);
}`;

  /* ---------------------------------------------------------------- */
  /* small helpers                                                    */

  function compile(gl, type, src) {
    var sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      var log = gl.getShaderInfoLog(sh);
      gl.deleteShader(sh);
      throw new Error("shader: " + log);
    }
    return sh;
  }

  function program(gl, vs, fs) {
    var p = gl.createProgram();
    var v = compile(gl, gl.VERTEX_SHADER, vs);
    var f = compile(gl, gl.FRAGMENT_SHADER, fs);
    gl.attachShader(p, v);
    gl.attachShader(p, f);
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      throw new Error("link: " + gl.getProgramInfoLog(p));
    }
    gl.deleteShader(v);
    gl.deleteShader(f);
    /* the uniform locations, once */
    var u = {};
    var n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (var i = 0; i < n; i++) {
      var info = gl.getActiveUniform(p, i);
      var name = info.name.replace(/\[0\]$/, "");
      u[name] = gl.getUniformLocation(p, name);
    }
    return {prog: p, u: u};
  }

  function hexToRgb(h) {
    return [parseInt(h.substr(1, 2), 16),
            parseInt(h.substr(3, 2), 16),
            parseInt(h.substr(5, 2), 16)];
  }

  /* ---------------------------------------------------------------- */
  /* the outlines: every ring of every polygon, as a list of segments */

  /* The flat map is an equirectangular one, so a coastline that crosses
     the antimeridian has to be cut there - otherwise it is drawn
     straight across the map. */
  function buildSegments(features, split) {
    var segs = [];
    var ranges = [];
    for (var f = 0; f < features.length; f++) {
      var start = segs.length / 4;
      var g = features[f].geometry;
      if (!g) { ranges.push({start: start, count: 0}); continue; }
      var polys = (g.type === "MultiPolygon") ? g.coordinates : [g.coordinates];
      for (var p = 0; p < polys.length; p++) {
        for (var r = 0; r < polys[p].length; r++) {
          var ring = polys[p][r];
          for (var i = 0; i + 1 < ring.length; i++) {
            var a = ring[i], b = ring[i + 1];
            if (split && Math.abs(b[0] - a[0]) > 180) {
              var east = a[0] < b[0];
              var lo = east ? -180 : 180;
              var hi = east ? 180 : -180;
              var t = (lo - a[0]) / (b[0] - a[0]);
              var lat = a[1] + t * (b[1] - a[1]);
              segs.push(a[0], a[1], lo, lat);
              segs.push(hi, lat, b[0], b[1]);
            } else {
              segs.push(a[0], a[1], b[0], b[1]);
            }
          }
        }
      }
      ranges.push({start: start, count: segs.length / 4 - start});
    }
    return {data: new Float32Array(segs), ranges: ranges, count: segs.length / 4};
  }

  /* the graticule: the lines of longitude and latitude */
  function graticule10() {
    var lines = [];
    var i, j;
    for (i = -80; i <= 80; i += 10) {
      var par = [];
      for (j = -180; j <= 180; j += 10) { par.push([j, i]); }
      lines.push(par);
    }
    for (i = -180; i < 180; i += 10) {
      var mer = [];
      for (j = -90; j <= 90; j += 10) { mer.push([i, j]); }
      lines.push(mer);
    }
    return lines;
  }

  function graticulePolar() {
    var lines = [];
    [60, 30].forEach(function (lat) {
      var c = [];
      for (var i = 0; i <= 360; i += 2) { c.push([i % 360, lat]); }
      lines.push(c);
    });
    for (var lon = 0; lon < 360; lon += 30) {
      lines.push([[lon, 60], [lon, 90]]);
    }
    return lines;
  }

  /* the graticule's instances: the distance along each line is needed
     for the dashes, and it is a distance on the screen, so it is worked
     out again for every frame (the graticule is a thousand points, so
     that costs nothing). */
  /* The graticule's segments: four numbers each, lonA latA lonB latB.
     The distance along the line is a separate array - the segment
     attribute reads four numbers a segment, so anything else in the
     buffer shifts every segment after the first. */
  function buildGraticule(lines, p) {
    var seg = [];
    var dist = [];
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var d = 0;
      for (var j = 0; j + 1 < line.length; j++) {
        var A = projectPoint(line[j][0] * DEG, line[j][1] * DEG, p);
        var B = projectPoint(line[j + 1][0] * DEG, line[j + 1][1] * DEG, p);
        var len = Math.sqrt((B.x - A.x) * (B.x - A.x) +
                             (B.y - A.y) * (B.y - A.y));
        seg.push(line[j][0], line[j][1], line[j + 1][0], line[j + 1][1]);
        dist.push(d);
        d += len;
      }
    }
    return {seg: new Float32Array(seg), dist: new Float32Array(dist)};
  }

  /* which country is under the pointer? */
  function inRing(ring, lon, lat) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var yi = ring[i][1], yj = ring[j][1];
      if ((yi > lat) !== (yj > lat)) {
        var x = (ring[j][0] - ring[i][0]) * (lat - yi) / (yj - yi) + ring[i][0];
        if (lon < x) { inside = !inside; }
      }
    }
    return inside;
  }

  function hitCountry(features, lon, lat) {
    for (var f = 0; f < features.length; f++) {
      var g = features[f].geometry;
      if (!g) { continue; }
      var polys = (g.type === "MultiPolygon") ? g.coordinates : [g.coordinates];
      for (var p = 0; p < polys.length; p++) {
        for (var r = 0; r < polys[p].length; r++) {
          if (inRing(polys[p][r], lon, lat)) { return f; }
        }
      }
    }
    return -1;
  }

  /* ---------------------------------------------------------------- */
  /* the renderer                                                      */

  function Renderer(canvas) {
    this.canvas = canvas;
    var gl = canvas.getContext("webgl2", {
      alpha: true, antialias: false, depth: false, stencil: false,
      premultipliedAlpha: true,
      /* the map is drawn when it changes, not every frame, so the buffer
         has to be kept: without this the browser throws the picture
         away as soon as it has been shown, and the map goes blank */
      preserveDrawingBuffer: true,
      powerPreference: "high-performance"
    });
    if (!gl) { throw new Error("WebGL2 is not available"); }
    this.gl = gl;
    this.earth = program(gl, VERT_QUAD, FRAG_EARTH);
    this.line = program(gl, VERT_LINE, FRAG_LINE);

    /* the full-screen quad */
    this.vaoQuad = gl.createVertexArray();
    gl.bindVertexArray(this.vaoQuad);
    var qb = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, qb);
    gl.bufferData(gl.ARRAY_BUFFER,
                  new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
                  gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);

    /* the line program: the corners of the quad, the segments, the
       distance along the line */
    this.corners = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.corners);
    gl.bufferData(gl.ARRAY_BUFFER,
                  new Float32Array([-1, 0, 1, 0, -1, 1, 1, 1]),
                  gl.STATIC_DRAW);

    /* the outlines: one set for the globe and the polar view, one for
       the flat map, which is cut at the antimeridian */
    this.geoSeg = gl.createBuffer();
    this.geoDist = gl.createBuffer();
    this.vaoGeo = this.makeVAO(this.geoSeg, this.geoDist);
    this.splitSeg = gl.createBuffer();
    this.splitDist = gl.createBuffer();
    this.vaoGeoSplit = this.makeVAO(this.splitSeg, this.splitDist);

    this.vaoGrat = gl.createVertexArray();
    gl.bindVertexArray(this.vaoGrat);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.corners);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    this.gratSeg = gl.createBuffer();
    this.gratDist = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.gratSeg);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(1, 1);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.gratDist);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(4096), gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(2);
    gl.vertexAttribPointer(2, 1, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(2, 1);
    gl.bindVertexArray(null);

    /* the textures */
    this.texField = this.makeTex(gl.LINEAR);
    this.texLut = this.makeTex(gl.NEAREST);
    this.texMask = this.makeTex(gl.LINEAR);

    this.p = {view: "globe", lam0: 0, phi0: 0, k: 1, x0: 0, y0: 0};
    this.mode = 0;
    this.hover = -1;
    this.geo = {countries: null, lakes: null, split: null};
    this.gratLines = null;
    this.anom = new Float32Array(16 * 3);
    this.anomN = 0;
    this.colours = {
      ocean: hexToRgb("#12395c"), land: hexToRgb("#33445a"),
      country: hexToRgb("#9cc0d8"), lake: hexToRgb("#1b4d78"),
      grat: hexToRgb("#4d7ea6"), hover: hexToRgb("#c8860d"),
      pole: hexToRgb("#12263f")
    };
  }

  /* a vertex array for the line program: the corners of the quad, the
     segments, and the distance along the line */
  Renderer.prototype.makeVAO = function (segBuf, distBuf) {
    var gl = this.gl;
    var vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.corners);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, segBuf);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(1, 1);
    gl.bindBuffer(gl.ARRAY_BUFFER, distBuf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(4096), gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(2);
    gl.vertexAttribPointer(2, 1, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(2, 1);
    gl.bindVertexArray(null);
    return vao;
  };

  Renderer.prototype.makeTex = function (filter) {
    var gl = this.gl;
    var t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return t;
  };

  /* the earth's mask: the sea and the land, baked once into an
     equirectangular texture */
  Renderer.prototype.setMask = function (canvas) {
    var gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.texMask);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE,
                  canvas);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  };

  /* the field: the model's own grid, one byte a cell, exactly as it
     came out of the PNG */
  Renderer.prototype.setField = function (bytes, grid) {
    var gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.texField);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
    /* the field goes in as RGBA: one byte a cell in the red channel.
       A single-channel texture is the obvious thing to use, but a
       runtime-indexed fetch out of one comes back wrong on some
       drivers, and the cell is the one thing the map must not get
       wrong. */
    var n = grid.nlon * grid.nlat;
    /* one row of the texture is one row of the grid: the stride has to
       be the grid's own width, or the field is read a row out of step */
    var rgba = new Uint8Array(n * 4);
    for (var i = 0; i < n; i++) {
      var b = bytes[i];
      rgba[i * 4] = b;
      rgba[i * 4 + 1] = b;
      rgba[i * 4 + 2] = b;
      rgba[i * 4 + 3] = 255;
    }
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, grid.nlon, grid.nlat, 0,
                  gl.RGBA, gl.UNSIGNED_BYTE, rgba);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this.grid = grid;
  };

  /* the published tables: byte -> the colour the static panels give it.
     Row 0 is the totals' ladder, row 1 the anomalies' table - both are
     the panels' own decision, bucket for bucket, so the map IS the
     static map and not merely a map of the same data.

     The alpha says whether there is anything to paint: the bottom of the
     ladder is "no snow", and on the map that is the earth showing
     through and not a bright white fringe; 255 on the anomaly row is
     the mask, where the model's own climate expects no snow. */
  Renderer.prototype.setLut = function (lut, anomLut, bottom) {
    var gl = this.gl;
    var data = new Uint8Array(256 * 2 * 4);
    for (var b = 0; b < 256; b++) {
      var c = hexToRgb(lut[b]);
      data[b * 4] = c[0]; data[b * 4 + 1] = c[1]; data[b * 4 + 2] = c[2];
      data[b * 4 + 3] = (c[0] === bottom[0] && c[1] === bottom[1] &&
                        c[2] === bottom[2]) ? 0 : 255;
    }
    this.hasAnomLut = 0;
    for (var b2 = 0; b2 < 256; b2++) {
      var c2 = hexToRgb(anomLut && anomLut[b2] ? anomLut[b2] : lut[b2]);
      var o = (256 + b2) * 4;
      data[o] = c2[0]; data[o + 1] = c2[1]; data[o + 2] = c2[2];
      data[o + 3] = (b2 >= 255) ? 0 : 255;
    }
    if (anomLut && anomLut.length === 256) { this.hasAnomLut = 1; }
    gl.bindTexture(gl.TEXTURE_2D, this.texLut);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 2, 0, gl.RGBA,
                  gl.UNSIGNED_BYTE, data);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  };

  Renderer.prototype.setAnom = function (colors) {
    var n = Math.min(16, colors.length);
    for (var i = 0; i < n; i++) {
      var c = hexToRgb(colors[i]);
      this.anom[i * 3] = c[0] / 255;
      this.anom[i * 3 + 1] = c[1] / 255;
      this.anom[i * 3 + 2] = c[2] / 255;
    }
    this.anomN = n;
  };

  /* the outlines: the countries first, then the lakes, in one buffer */
  Renderer.prototype.setGeometry = function (countries, lakes) {
    var gl = this.gl;
    this.geo.countries = buildSegments(countries, false);
    this.geo.lakes = buildSegments(lakes, false);
    var both = new Float32Array(this.geo.countries.data.length +
                                 this.geo.lakes.data.length);
    both.set(this.geo.countries.data, 0);
    both.set(this.geo.lakes.data, this.geo.countries.data.length);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.geoSeg);
    gl.bufferData(gl.ARRAY_BUFFER, both, gl.STATIC_DRAW);
    this.lakeOffset = this.geo.countries.count * 16;
    this.geoDistData = new Float32Array(this.geo.countries.count +
                                         this.geo.lakes.count);
  };

  /* the flat map has to cut the coastlines at the antimeridian, or a
     coastline is drawn straight across the map */
  Renderer.prototype.setSplitGeometry = function (countries, lakes) {
    var gl = this.gl;
    this.geo.splitCountries = buildSegments(countries, true);
    this.geo.splitLakes = buildSegments(lakes, true);
    var c = this.geo.splitCountries, l = this.geo.splitLakes;
    var both = new Float32Array(c.data.length + l.data.length);
    both.set(c.data, 0);
    both.set(l.data, c.data.length);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.splitSeg);
    gl.bufferData(gl.ARRAY_BUFFER, both, gl.STATIC_DRAW);
    this.splitLakeOffset = c.count * 16;
    this.splitDistData = new Float32Array(c.count + l.count);
    this.split = true;
  };

  Renderer.prototype.setGraticule = function (lines) {
    this.gratLines = lines;
    this.gratData = new Float32Array(lines.length * 64 * 5);
  };

  Renderer.prototype.setProjection = function (p) {
    this.p = p;
  };

  Renderer.prototype.setMode = function (m) { this.mode = m; };

  Renderer.prototype.setHover = function (h) { this.hover = h; };

  /* ---------------------------------------------------------------- */
  /* the frame                                                        */

  Renderer.prototype.render = function () {
    /* the outlines are drawn over the field, so a check of the field's
       own colour turns them off */
    if (this.showVectors === undefined) { this.showVectors = true; }
    var gl = this.gl;
    var p = this.p;
    var W = this.canvas.width, H = this.canvas.height;
    if (!W || !H) { return; }
    gl.viewport(0, 0, W, H);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.disable(gl.BLEND);
    gl.disable(gl.DEPTH_TEST);

    /* --- the earth and the field --- */
    var E = this.earth;
    gl.useProgram(E.prog);
    gl.uniform2f(E.u.u_res, W, H);
    gl.uniform1i(E.u.u_view, p.view === "flat" ? 0 :
                                  (p.view === "globe" ? 1 : 2));
    gl.uniform2f(E.u.u_centre, p.lam0, p.phi0);
    gl.uniform1f(E.u.u_k, p.k);
    gl.uniform2f(E.u.u_trans, p.x0, p.y0);
    gl.uniform1i(E.u.u_mode, this.mode);
    gl.uniform3fv(E.u.u_ocean, this.colours.ocean.map(function (v) {
      return v / 255;
    }));
    gl.uniform3fv(E.u.u_land, this.colours.land.map(function (v) {
      return v / 255;
    }));
    if (this.anomN > 0) {
      gl.uniform3fv(E.u.u_anom, this.anom);
      gl.uniform1i(E.u.u_anomN, this.anomN);
    }
    /* the atmosphere: the rim of light round the globe */
    var atmos = 0;
    if (p.view === "globe") { atmos = p.k * 1.16; }
    gl.uniform1f(E.u.u_atmos, atmos);
    var g = this.grid;
    if (g) {
      gl.uniform4f(E.u.u_grid, g.lat0, g.dlat, g.lon0, g.dlon);
      gl.uniform4f(E.u.u_grid2, g.nlat, g.nlon, g.isGlobal ? 1 : 0,
                   g.nlon * g.dlon);
    }
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.texMask);
    gl.uniform1i(E.u.u_mask, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.texField);
    gl.uniform1i(E.u.u_field, 1);
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, this.texLut);
    gl.uniform1i(E.u.u_lut, 2);
    gl.uniform1f(E.u.u_hasAnomLut, this.hasAnomLut ? 1.0 : 0.0);
    gl.bindVertexArray(this.vaoQuad);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.bindVertexArray(null);

    /* --- the vectors --- */
    if (!this.showVectors) { gl.disable(gl.BLEND); return; }
    var L = this.line;
    gl.useProgram(L.prog);
    gl.uniform2f(L.u.u_res, W, H);
    gl.uniform1i(L.u.u_view, p.view === "flat" ? 0 :
                                  (p.view === "globe" ? 1 : 2));
    gl.uniform2f(L.u.u_centre, p.lam0, p.phi0);
    gl.uniform1f(L.u.u_k, p.k);
    gl.uniform2f(L.u.u_trans, p.x0, p.y0);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    /* the graticule: dashed, and the dash is a distance on the screen,
       so its instances are worked out again for this frame */
    if (this.gratLines) {
      var gd = buildGraticule(this.gratLines, p);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.gratSeg);
      gl.bufferData(gl.ARRAY_BUFFER, gd.seg, gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.gratDist);
      gl.bufferData(gl.ARRAY_BUFFER, gd.dist, gl.DYNAMIC_DRAW);
      gl.bindVertexArray(this.vaoGrat);
      gl.uniform1f(L.u.u_width, 0.5);
      gl.uniform1f(L.u.u_dashOn, 2.0);
      gl.uniform1f(L.u.u_dashPeriod, 5.0);
      gl.uniform3f(L.u.u_colour, this.colours.grat[0] / 255,
                   this.colours.grat[1] / 255, this.colours.grat[2] / 255);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, gd.seg.length / 4);
      gl.bindVertexArray(null);
    }

    /* the coastlines */
    var geo = this.geo;
    if (geo && geo.countries) {
      var split = (p.view === "flat" && this.split && geo.splitCountries);
      var cnt = split ? geo.splitCountries : geo.countries;
      var lks = split ? geo.splitLakes : geo.lakes;
      var segBuf = split ? this.splitSeg : this.geoSeg;
      var distBuf = split ? this.splitDist : this.geoDist;
      var lakeOff = split ? this.splitLakeOffset : this.lakeOffset;
      var vao = split ? this.vaoGeoSplit : this.vaoGeo;
      var zeros = split ? this.splitDistData : this.geoDistData;
      var need = cnt.count + lks.count;
      if (!zeros || zeros.length < need) {
        zeros = new Float32Array(need);
        if (split) { this.splitDistData = zeros; } else { this.geoDistData = zeros; }
      }
      /* the distances along the line: nothing but the graticule is
         dashed, so they are all zero */
      gl.bindBuffer(gl.ARRAY_BUFFER, distBuf);
      gl.bufferData(gl.ARRAY_BUFFER, zeros, gl.DYNAMIC_DRAW);
      gl.bindVertexArray(vao);
      gl.uniform1f(L.u.u_dashOn, 0.0);
      gl.uniform1f(L.u.u_dashPeriod, 0.0);

      /* the countries */
      gl.uniform1f(L.u.u_width, 0.45);
      gl.uniform3f(L.u.u_colour, this.colours.country[0] / 255,
                   this.colours.country[1] / 255, this.colours.country[2] / 255);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, cnt.count);

      /* the country under the pointer, in the house's amber */
      if (this.hover >= 0 && this.hover < cnt.ranges.length) {
        var rg = cnt.ranges[this.hover];
        if (rg.count > 0) {
          gl.uniform1f(L.u.u_width, 1.1);
          gl.uniform3f(L.u.u_colour, this.colours.hover[0] / 255,
                       this.colours.hover[1] / 255, this.colours.hover[2] / 255);
          gl.bindBuffer(gl.ARRAY_BUFFER, segBuf);
          gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 0, rg.start * 16);
          gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, rg.count);
        }
      }

      /* the lakes */
      gl.bindBuffer(gl.ARRAY_BUFFER, segBuf);
      gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 0, lakeOff);
      gl.uniform1f(L.u.u_width, 0.35);
      gl.uniform3f(L.u.u_colour, this.colours.lake[0] / 255,
                   this.colours.lake[1] / 255, this.colours.lake[2] / 255);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, lks.count);
      gl.bindVertexArray(null);
    }
    gl.disable(gl.BLEND);
  };

  /* ---------------------------------------------------------------- */
  /* picking: where is this pixel, and what does the field say there? */

  Renderer.prototype.pick = function (x, y) {
    var p = this.p;
    var dx = x - p.x0, dy = y - p.y0;
    var rr = Math.sqrt(dx * dx + dy * dy);
    if (p.view === "globe" && rr > p.k) { return {lon: 0, lat: 0, byte: null}; }
    if (p.view === "polar" && rr > p.k * Math.PI / 2) {
      return {lon: 0, lat: 0, byte: null};
    }
    var ll = invertPoint(x, y, p);
    var out = {lon: ll.lon, lat: ll.lat, byte: null};
    var g = this.grid;
    if (!g) { return out; }
    var lat0 = g.lat0, dlat = g.dlat, lon0 = g.lon0, dlon = g.dlon;
    var nlat = g.nlat, nlon = g.nlon;
    if (ll.lat > lat0 || ll.lat < lat0 - (nlat - 1) * dlat) { return out; }
    var fi = (lat0 - ll.lat) / dlat;
    var fj;
    if (g.isGlobal) {
      fj = ((ll.lon - lon0) / dlon) % nlon;
      if (fj < 0) { fj += nlon; }
    } else {
      var la = ll.lon;
      if (lon0 >= 0) {
        while (la < 0) { la += 360; }
        while (la >= 360) { la -= 360; }
      } else {
        while (la > 180) { la -= 360; }
        while (la < -180) { la += 360; }
      }
      var span = nlon * dlon;
      if (la < lon0 - 1e-9 || la > lon0 + span - 1e-9) { return out; }
      fj = (la - lon0) / dlon;
      if (fj < 0) { fj += nlon; }
      if (fj >= nlon) { fj -= nlon; }
    }
    var i0 = Math.floor(fi), j0 = Math.floor(fj);
    if (i0 < 0) { i0 = 0; }
    if (i0 > nlat - 2) { i0 = nlat - 2; }
    if (j0 < 0) { j0 = 0; }
    if (j0 > nlon - 2) { j0 = nlon - 2; }
    out.i0 = i0;
    out.j0 = j0;
    out.byte = this.bytes ? this.bytes[i0 * nlon + j0] : null;
    return out;
  };

  Renderer.prototype.setBytes = function (bytes) { this.bytes = bytes; };

  global.MapGL = {
    Renderer: Renderer,
    projectPoint: projectPoint,
    invertPoint: invertPoint,
    buildSegments: buildSegments,
    graticule10: graticule10,
    graticulePolar: graticulePolar,
    hitCountry: hitCountry,
    hexToRgb: hexToRgb
  };
})(window);
