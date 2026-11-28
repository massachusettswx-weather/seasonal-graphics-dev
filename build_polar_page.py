"""The polar-cap section of the Stratosphere page.

The section is a time-height diagram of the polar cap (60-90N) normalised
geopotential height anomaly: the analysis on the left of the "forecast
starts" line, the model's own forecast on the right, running to the end of
that model's run.

It lives on the **Stratosphere** page, next to the 10 hPa zonal-mean zonal
wind, because it is the same part of the atmosphere seen from the other
side: the wind at 10 hPa is the vortex proxy, and this is the vortex
itself, from the stratosphere down to the surface.

Two kinds of chart live on the page:

  * the CORe reanalysis of the last 15 days, in front of the model's own
    forecast - what actually happened, and what might happen;
  * the seasonal sections, one per model, built from the C3S sub-daily
    archive, which run to the end of each model's own run.

**No medium-range guidance is used.**  The IFS 15-day chart that used to
sit here has been taken out: a sub-seasonal and a seasonal run are the
products this section is about.

The charts are rendered into output/polar_cap/ and copied into
docs/assets/polar/ by build_registry.py.
"""
import datetime
import html
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "docs")
OUT = os.path.join(HERE, "output")

# What ECMWF's archive holds, as opposed to what the site carries.  The
# fetch writes it; the page reads it.
STATUS = os.path.join(HERE, "data", "polar_ec46_status.json")

# The models the section is for, in the order they are shown.
#
# 13 Nov 2026: the user asked for exactly three - the seasonal run, the
# sub-seasonal GEFS and the ECMWF extended range.  The other centres are
# NOT to be given a section, so the list here is the whole of it.
MODELS = [
    ("ecmwf-seas5", "ECMWF SEAS5"),
    ("gefsv12", "NOAA GEFSv12"),
    ("ec46", "ECMWF EC46"),
]

# The section opens on the GEFSv12: it is the sub-seasonal panel, the one
# that changes every day, and the owner asked for it to be the default
# (22 Nov 2026).  A CONSTANT, not "the first one in the list" - the list
# follows the registry, and the registry's order is not a choice.
DEFAULT = "gefsv12"

def available(reg=None):
    """-> [(id, name)] for the models the registry says have a section."""
    if reg is None:
        p = os.path.join(SITE, "data", "models.json")
        reg = json.load(open(p)) if os.path.exists(p) else {"models": []}
    out = []
    for m in reg.get("models", []):
        if m.get("polar"):
            out.append((m["id"], m["name"]))
    return out


def items(reg=None):
    """Every polar-cap chart the page can show.

    Only the SEASONAL guidance is shown.  The ECMWF IFS 15-day chart is not:
    a medium-range forecast is a different product from a seasonal run, and
    the section is about the latter.
    """
    out = []
    for mid, name in available(reg):
        info = None
        for m in reg.get("models", []):
            if m["id"] == mid:
                info = m.get("polar")
        if not info:
            continue
        out.append({"id": mid, "name": name, "file": info["file"],
                    "caption": info.get("caption", "")})
    return out


def sector_items(reg=None):
    """The same section split into the two longitude sectors."""
    out = []
    for mid, name in available(reg):
        info = None
        for m in reg.get("models", []):
            if m["id"] == mid:
                info = m.get("polar_sectors")
        if not info:
            continue
        out.append({"id": mid, "name": name, "file": info["file"],
                    "caption": info.get("caption", "")})
    return out


def long_date(iso):
    """'2026-11-26' -> '26 November 2026'."""
    try:
        d = datetime.date.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return str(iso)
    return "%d %s %d" % (d.day, d.strftime("%B"), d.year)


def long_stamp(s):
    """'2026-11-28 04:43 UTC' -> '28 November 2026, 04:43 UTC'."""
    s = str(s or "").strip()
    try:
        d = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return s
    return "%s, %s UTC" % (long_date(d.date().isoformat()), d.strftime("%H:%M"))


def ec46_note(reg=None):
    """The EC46's status line, or "" when there is nothing to say.

    THE ARCHIVE IS SLOWER THAN THE SITE.  ECMWF's S2T archive gets a run
    about 27 hours after its date, so for a day and a half there is always
    a run that is not there yet, and the reader is better served by being
    told WHICH one than by wondering why the chart is a day old.

    The run the page carries comes from the registry; the run the archive
    holds comes from the last probe, with the time it was made.  Both are
    said, so the two are never confused.
    """
    if not os.path.exists(STATUS):
        return ""
    try:
        st = json.load(open(STATUS))
        if reg is None:
            reg = json.load(open(os.path.join(SITE, "data", "models.json")))
    except (OSError, ValueError):
        return ""
    newest = str(st.get("newest_in_store") or "")
    checked = str(st.get("checked") or "")
    if not newest:
        return ""
    carried = ""
    for m in reg.get("models", []):
        if m.get("id") == "ec46":
            carried = str(m.get("init") or "")
    if not carried:
        carried = newest
    try:
        nd = datetime.date.fromisoformat(newest)
        pending = nd + datetime.timedelta(days=1)
    except (TypeError, ValueError):
        return ""
    today = datetime.date.today()
    s = []
    if carried and carried < newest:
        s.append("The chart carries the run of %s (00Z).  ECMWF's archive "
                 "already has the run of %s - it is pulled the moment it "
                 "lands." % (long_date(carried), long_date(newest)))
    else:
        s.append("The chart carries the run of %s (00Z), which is the newest "
                 "in ECMWF's archive." % long_date(carried))
    if pending <= today:
        s.append("The run of %s is not there yet - it is pulled the moment "
                 "it lands." % long_date(pending))
    if checked:
        s.append("(Checked %s.)" % long_stamp(checked))
    return html.escape(" ".join(s))


def polar_block(reg=None):
    """The HTML for the polar-cap section, or "" when there is nothing."""
    its = items(reg)
    if not its:
        return ""
    secs = {i["id"]: i for i in sector_items(reg)}

    default = DEFAULT if any(i["id"] == DEFAULT for i in its) else its[0]["id"]
    sel = "".join('<option value="%s"%s>%s</option>'
                  % (i["id"], " selected" if i["id"] == default else "",
                     i["name"]) for i in its)
    block = """<div class="card" id="polar">
  <div class="crumb"><a href="__SITE__">&larr; All models</a> &middot;
    <a href="model.html">Choose a variable</a></div>
  <h2 class="sec">Polar Cap (60&ndash;90&deg;N) Geopotential Height Anomaly</h2>
  <p class="lead">A time-height section of the polar cap: the area-weighted
  mean geopotential height from 60&deg;N to the pole, on a set of pressure
  levels, as a <strong>normalized</strong> anomaly &mdash; in standard
  deviations of the CORe reanalysis&rsquo;s own 1991&ndash;2020 climate.
  Normalising puts every level on the same footing, so the stratosphere and
  the troposphere can be read on one scale. The pressure axis is logarithmic,
  so the stratosphere at the top has the room it needs, and the section runs
  down to the surface at the bottom.</p>
  <p class="lead">The left of the dashed line is <strong>CORe
  reanalysis</strong> &mdash; NOAA&rsquo;s Conventional Observation
  Reanalysis, which is built on the FV3-GFS model, and it is what actually
  happened, up to the model&rsquo;s own run. The right is the
  <strong>forecast</strong> &mdash; what might happen, running to the end of
  that model&rsquo;s own run. The reanalysis and the forecast are on the same
  scale and the same colour bar, so the two halves can be read against each
  other.</p>
  <p class="lead">A seasonal model&rsquo;s own mean state is not the observed
  climate: by the far end of a seven-month run the ECMWF SEAS5 sits several
  thousand m&sup2;/s&sup2; below it, and the small summer spread then draws
  that as several sigma of a cold stratosphere when it is nothing of the
  kind. The forecast half is therefore measured against <strong>the
  model&rsquo;s own hindcast climate</strong>, which removes that offset; the
  reanalysis half stays on the CORe climate, and both are in standard
  deviations of it. The GEFS&rsquo;s 35-day run drifts very little, so it is
  measured against the CORe climate directly.</p>
  <div class="picker">
    <label for="polarSel">Model</label>
    <select id="polarSel" class="ctrl">%s</select>
    <label for="polarView">View</label>
    <select id="polarView" class="ctrl">
      <option value="cap">Whole polar cap</option>
      <option value="sectors">By sector</option>
    </select>
    <label for="polarArchive">Archived run</label>
    <select id="polarArchive" class="ctrl" disabled></select>
  </div>
</div>

<div class="card">
  <div class="stage"><img id="polarImg" alt="Polar cap geopotential height anomaly"></div>
  <div class="cap" id="polarCap"></div>
  __NOTE__
</div>""" % sel

    js = """
<script>
const POLARMODELS=__POLARMODELS__;
const POLARSECTORS=__POLARSECTORS__;
const psel=document.getElementById('polarSel');
const pview=document.getElementById('polarView');
const pnote=document.getElementById('polarNote');
function pq(p){const m=new URLSearchParams(location.search);return m.get(p);}
// The status line belongs to one model, and it is shown only when that
// model is the one on the picker.
function syncNote(){
  if(!pnote) return;
  pnote.hidden = pnote.dataset.model!==psel.value;
}
if(pq('m') && POLARMODELS[pq('m')]) psel.value=pq('m');
// The sector option is only offered for a model that HAS a sector chart.
// A control that does nothing when it is chosen is worse than no control.
function syncView(){
  const has=!!POLARSECTORS[psel.value];
  const opt=pview.querySelector('option[value="sectors"]');
  opt.disabled=!has;
  opt.textContent=has?'By sector (Pacific and Atlantic)'
                     :'By sector (not for this model)';
  if(!has && pview.value==='sectors') pview.value='cap';
}
function renderPolar(){
  const id=psel.value;
  const m=POLARMODELS[id];
  const s=POLARSECTORS[id];
  const wantSector=pview.value==='sectors' && s;
  const img=document.getElementById('polarImg');
  const cap=document.getElementById('polarCap');
  syncNote();
  if(wantSector){
    img.src=s.file; img.alt=s.caption; cap.textContent=s.caption; return;
  }
  if(!m){img.removeAttribute('src');img.alt='';
    cap.textContent='No section for this model.';return;}
  img.src=m.file; img.alt=m.caption; cap.textContent=m.caption;
}
psel.addEventListener('change',()=>{syncView();renderPolar();});
pview.addEventListener('change',renderPolar);
syncView();
renderPolar();
</script>
<script src="assets/js/polar_archive.js?v=__VER__"></script>"""
    ver = (reg or {}).get("version", "")
    # THE EC46's STATUS LINE.  It is put in the page as a block that is
    # hidden until the EC46 is the model on the picker, so the reader sees
    # it exactly when it is about the chart in front of them.
    note = ec46_note(reg)
    if note:
        block = block.replace(
            "__NOTE__",
            '<p class="note" id="polarNote" data-model="ec46" hidden>%s</p>'
            % note)
    else:
        block = block.replace("__NOTE__", "")
    return (block
            + js.replace("__POLARMODELS__", json.dumps({i["id"]: i for i in its}))
                   .replace("__POLARSECTORS__",
                            json.dumps({i["id"]: i for i in sector_items(reg)}))
                   .replace("__VER__", ver))
    return (block
            + js.replace("__POLARMODELS__", json.dumps({i["id"]: i for i in its}))
                   .replace("__POLARSECTORS__",
                            json.dumps({i["id"]: i for i in sector_items(reg)})))


def remove_old_page():
    """The section used to have a page of its own; it does not any more."""
    p = os.path.join(SITE, "polar.html")
    if os.path.exists(p):
        os.remove(p)
        print("   the old polar-cap page removed")


if __name__ == "__main__":
    reg = json.load(open(os.path.join(SITE, "data", "models.json")))
    print(polar_block(reg)[:200])
