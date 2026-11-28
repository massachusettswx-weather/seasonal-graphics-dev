/* The polar cap's archive: the earlier runs of the same model.
   The owner asked for this on the polar cap only - the seasonal snowfall
   maps do not carry an archive (25 November 2026).

   The charts here are the ones that were drawn and published at the time;
   nothing is redrawn, so an archived run is exactly what the reader saw
   that day.  The daily cycles of the GEFSv12 and the EC46 differ by a day
   of lead, so two of them really are close to each other.

   The index is fetched from the site's own path; the cache-buster is the
   stamp on this file, so a new archive is picked up without a rebuild of
   the page. */
(function () {
  var psel = document.getElementById('polarSel');
  var pview = document.getElementById('polarView');
  var img = document.getElementById('polarImg');
  var cap = document.getElementById('polarCap');
  var sel = document.getElementById('polarArchive');
  if (!sel || !img || !psel) { return; }

  var stamp = '';
  var s = document.currentScript;
  if (s && s.src) {
    var m = /[?&]v=([0-9]+)/.exec(s.src);
    if (m) { stamp = m[1]; }
  }

  var ARCHIVE = null;

  function modelName(id) {
    /* POLARMODELS is declared with const in the page's own script, so it
       is a script-scoped binding and not a property of window. */
    var reg = (typeof POLARMODELS !== 'undefined') ? POLARMODELS : null;
    var m = reg ? reg[id] : null;
    return m ? m.name : id;
  }

  function fill() {
    var id = psel.value;
    var runs = (ARCHIVE && ARCHIVE[id]) || [];
    sel.innerHTML = '';
    var cur = document.createElement('option');
    cur.value = '';
    cur.textContent = 'the current run';
    sel.appendChild(cur);
    runs.forEach(function (r) {
      var o = document.createElement('option');
      o.value = r.init;
      o.textContent = 'the ' + r.label + ' run';
      sel.appendChild(o);
    });
    sel.disabled = runs.length < 1;
    sel.value = '';
  }

  /* the chart the reader should be looking at: the archived one if one is
     chosen, otherwise the current run's - the same two files the page
     itself would show, so the view control still works. */
  function apply() {
    var id = psel.value;
    var init = sel.value;
    var wantSector = pview.value === 'sectors';
    if (!init) {
      /* back to the current run: let the page's own code put it back */
      if (typeof renderPolar === 'function') { renderPolar(); }
      return;
    }
    var runs = (ARCHIVE && ARCHIVE[id]) || [];
    var hit = null;
    runs.forEach(function (r) { if (r.init === init) { hit = r; } });
    if (!hit) {
      if (typeof renderPolar === 'function') { renderPolar(); }
      return;
    }
    var src = (wantSector && hit.sectors) ? hit.sectors : hit.cap;
    if (!src) {
      if (typeof renderPolar === 'function') { renderPolar(); }
      return;
    }
    img.src = src;
    img.alt = 'Polar cap geopotential height anomaly';
    cap.textContent = modelName(id) + ' - the ' + hit.label
      + ' run'
      + (wantSector ? ' (by sector)' : ' (whole polar cap)') + '.';
  }

  sel.addEventListener('change', apply);
  pview.addEventListener('change', apply);
  psel.addEventListener('change', function () {
    fill();
    if (typeof renderPolar === 'function') { renderPolar(); }
  });

  fetch('assets/polar/archive/index.json'
        + (stamp ? ('?v=' + stamp) : ''))
    .then(function (r) { return r.json(); })
    .then(function (j) {
      ARCHIVE = j || {};
      fill();
    })
    .catch(function () { sel.disabled = true; });
}());
