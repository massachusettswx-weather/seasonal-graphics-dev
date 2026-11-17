"""Build the static site for the seasonal forecast graphics.

Pages
    index.html      home: pick a seasonal model
    model.html      that model's variables: snowfall / 10 hPa zonal wind
    snow.html       snowfall: end-of-run total, monthly totals, monthly
                    anomalies with a drag bar
    spv.html        10 hPa zonal-mean zonal wind, one panel per model

Data
    docs/data/models.json        the model registry
    docs/data/models_public.json the browser's copy

Run after any re-render:  python3 build_site.py
"""
import os, json, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "docs")
ASSETS = os.path.join(SITE, "assets")
DATA = os.path.join(SITE, "data")

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --------------------------------------------------------------------------
# model registry
# --------------------------------------------------------------------------
def load_registry():
    """The registry is maintained by build_registry.py; this reads it and
    validates that every referenced asset exists."""
    p = os.path.join(DATA, "models.json")
    if not os.path.exists(p):
        return {"models": []}
    reg = json.load(open(p))
    for m in reg.get("models", []):
        m["snow_ok"] = False
        m["spv_ok"] = False
        m["polar_ok"] = False
        for fr in m.get("frames", []):
            if os.path.exists(os.path.join(SITE, fr["file"].split("?")[0])):
                fr["ok"] = True
                m["snow_ok"] = True
        tot = m.get("total")
        if tot and os.path.exists(os.path.join(SITE, tot["file"].split("?")[0])):
            m["snow_ok"] = True
        for dom, info in m.get("spv", {}).items():
            if os.path.exists(os.path.join(SITE, info["file"].split("?")[0])):
                info["ok"] = True
                m["spv_ok"] = True
        pol = m.get("polar")
        if pol and os.path.exists(os.path.join(SITE, pol["file"].split("?")[0])):
            pol["ok"] = True
            m["polar_ok"] = True
    return reg


def public_map(reg=None):
    """{model_id: model} for the browser, including the availability flags."""
    if reg is None:
        reg = load_registry()
    out = {}
    for m in reg.get("models", []):
        p = dict(m)
        p["snow_ok"] = m.get("snow_ok", False)
        p["spv_ok"] = m.get("spv_ok", False)
        p["polar_ok"] = m.get("polar_ok", False)
        out[m["id"]] = p
    return out


# --------------------------------------------------------------------------
# css
# --------------------------------------------------------------------------
CSS = """
:root{
  --ink:#12151a; --muted:#5b6472; --line:#e3e7ee; --bg:#f6f7f9;
  --card:#ffffff; --accent:#12263f; --accent2:#c2410c;
}
/* DARK MODE (asked for on 17 Nov 2026).  The theme is a data-theme on the
   html element: the button in the header sets it, the browser remembers
   it, and the first thing the page does is read it back, so there is no
   white flash on a dark screen. */
:root[data-theme="dark"]{
  --ink:#e7eef6; --muted:#96a6b8; --line:#25313f; --bg:#0a1017;
  --card:#121b25; --accent:#12263f; --accent2:#e2600f;
}
:root[data-theme="dark"] nav.tabs{background:#0e1620}
:root[data-theme="dark"] .tag{background:#1a2431; color:#b8c6d5; border-color:#2a3644}
:root[data-theme="dark"] .tag.ok{background:#15311f; color:#82d3a3; border-color:#255033}
:root[data-theme="dark"] .tag.no{background:#2d1a16; color:#e79c87; border-color:#4c2b23}
:root[data-theme="dark"] a.btn{background:#1a2431; color:#dbe7f3; border-color:#2a3644}
:root[data-theme="dark"] a.btn:hover{background:#243244}
:root[data-theme="dark"] a.btn.primary{background:#1d4f7a; border-color:#1d4f7a}
:root[data-theme="dark"] button.ctrl.ghost{background:#1a2431; color:#cfe0f5}
:root[data-theme="dark"] .seg .segbtn.ghost{background:#1a2431; color:#cfe0f5}
:root[data-theme="dark"] .seg .segbtn.on{background:#1d4f7a; border-color:#1d4f7a}
:root[data-theme="dark"] select.ctrl{background:#1a2431; color:#e7eef6; border-color:#2a3644}
:root[data-theme="dark"] table th{background:#1a2431; color:#c3d0dd}
:root[data-theme="dark"] .var .thumb{background:#1a2431}
:root[data-theme="dark"] .maptimeline .tlbtn{background:#1a2431; color:#dbe6f2; border-color:#2a3644}
:root[data-theme="dark"] .maptimeline .tlbtn.on{background:#1d4f7a; color:#fff; border-color:#1d4f7a}
:root[data-theme="dark"] .mapviews button{background:#1a2431; color:#dbe7f3}
:root[data-theme="dark"] .mapviews button.active{background:#1d4f7a; border-color:#1d4f7a}
:root[data-theme="dark"] .maplegend .bar{border-color:#2a3644}
.themebtn{font:inherit; font-size:12.5px; padding:5px 13px; cursor:pointer;
  border:1px solid rgba(207,224,245,.4); background:transparent; color:#cfe0f5;
  border-radius:999px; margin-right:2px}
.themebtn:hover{background:rgba(207,224,245,.14)}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:var(--ink); background:var(--bg); line-height:1.45;
}
header.top{
  background:var(--accent); color:#fff; padding:18px 26px;
  display:flex; align-items:baseline; gap:16px; flex-wrap:wrap;
}
header.top h1{font-size:20px; margin:0; font-weight:700; letter-spacing:.2px}
header.top h1 a{color:#fff; text-decoration:none}
header.top h1 a:hover{text-decoration:underline}
header.top .sub{font-size:12.5px; color:#9fb0c6}
header.top .spacer{flex:1}
header.top a{color:#cfe0f5; text-decoration:none; font-size:13px}
header.top a:hover{text-decoration:underline}
nav.tabs{background:#fff; border-bottom:1px solid var(--line); padding:0 26px;
  display:flex; gap:4px}
nav.tabs a{
  display:inline-block; padding:11px 16px; font-size:13.5px; text-decoration:none;
  color:var(--muted); border-bottom:2px solid transparent; font-weight:600;
}
nav.tabs a:hover{color:var(--ink)}
nav.tabs a.active{color:var(--accent); border-bottom-color:var(--accent)}
.wrap{max-width:1280px; margin:0 auto; padding:22px 26px 60px}
.card{background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:18px 20px; margin-bottom:18px}
h2.sec{font-size:16.5px; margin:0 0 4px; letter-spacing:.2px}
p.lead{color:var(--muted); font-size:13.5px; margin:0 0 16px}
.grid{display:grid; gap:16px}
.grid.c1{grid-template-columns:1fr}
.grid.c2{grid-template-columns:repeat(auto-fit,minmax(380px,1fr))}
.grid.c3{grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
.grid.c4{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.model{
  background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:16px 18px; display:flex; flex-direction:column; gap:8px;
  transition:border-color .12s, box-shadow .12s;
}
.model:hover{border-color:#c3ccdb; box-shadow:0 2px 10px rgba(18,38,63,.07)}
.model h3{margin:0; font-size:15.5px}
.model .meta{font-size:12.5px; color:var(--muted)}
.model .tags{display:flex; gap:6px; flex-wrap:wrap; margin-top:2px}
.tag{font-size:11px; padding:2px 8px; border-radius:20px; background:#eef1f6;
  color:#3b4656; border:1px solid #dde3ec}
.tag.ok{background:#e8f3ec; color:#1d6b3c; border-color:#c9e4d3}
.tag.no{background:#f6ecea; color:#8c3b28; border-color:#eccfc7}
.model .acts{display:flex; gap:8px; margin-top:6px; flex-wrap:wrap}
a.btn{display:inline-block; padding:7px 13px; border-radius:7px; font-size:13px;
  font-weight:600; text-decoration:none; background:#eef1f6; color:#22314a;
  border:1px solid #dbe1ea}
a.btn:hover{background:#e4e9f1}
a.btn.primary{background:var(--accent); color:#fff; border-color:var(--accent)}
a.btn.primary:hover{background:#0d1c30}
a.btn[aria-disabled="true"]{opacity:.42; pointer-events:none}
a.btn.wide{display:block; text-align:center; padding:9px 14px}
.picker{display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:14px}
.picker label{font-size:13px; color:var(--muted); font-weight:600}
select,button.ctrl{
  font-family:inherit; font-size:13.5px; padding:7px 10px; border-radius:7px;
  border:1px solid #d5dbe5; background:#fff; color:var(--ink)
}
button.ctrl{cursor:pointer; background:var(--accent); color:#fff; border-color:var(--accent);
  font-weight:600}
button.ctrl.ghost{background:#fff; color:var(--accent)}
.seg{display:inline-flex; gap:6px}
.seg .segbtn{border-radius:16px; padding:7px 14px; font-size:13px}
.seg .segbtn.ghost{background:#fff; color:var(--accent)}
.seg .segbtn.on{background:var(--accent); color:#fff}
.stage{background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:14px}
.stage img{width:100%; height:auto; display:block; border-radius:4px}
.panel{margin:0 0 6px}
.panel img{width:100%; height:auto; display:block; border-radius:4px}
.panel figcaption{font-size:12px; color:var(--muted); margin:6px 0 16px}
.cap{font-size:12.5px; color:var(--muted); margin-top:10px}
.slider{display:flex; align-items:center; gap:14px; margin-top:14px; flex-wrap:wrap}
input[type=range]{flex:1; min-width:220px; accent-color:var(--accent); height:22px}
.frameLabel{font-size:13.5px; font-weight:700; min-width:150px}
table{width:100%; border-collapse:collapse; font-size:13px; background:var(--card)}
th,td{padding:7px 10px; border-bottom:1px solid var(--line); text-align:right}
th:first-child,td:first-child{text-align:left}
th{background:#eef1f6; font-size:12px; text-transform:uppercase; letter-spacing:.4px;
  color:#48546a}
tr:last-child td{border-bottom:none}
.note{font-size:12.5px; color:var(--muted); border-left:3px solid var(--line);
  padding-left:11px; margin-top:12px}
.crumb{font-size:13px; color:var(--muted); margin-bottom:14px}
.crumb a{text-decoration:none}
.crumb a:hover{text-decoration:underline}
.varlist{display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.var{background:var(--card); border:1px solid var(--line); border-radius:10px;
  overflow:hidden; display:flex; flex-direction:column}
.var .thumb{background:#eef1f6; border-bottom:1px solid var(--line);
  display:flex; align-items:center; justify-content:center; height:170px; overflow:hidden}
.var .thumb img{max-width:100%; max-height:100%; object-fit:contain}
.var .body{padding:14px 16px; display:flex; flex-direction:column; gap:6px; flex:1}
.var h3{margin:0; font-size:15px}
.var p{margin:0; font-size:12.5px; color:var(--muted)}
.var .acts{margin-top:auto; padding-top:10px}
.var.off{opacity:.55}
footer{border-top:1px solid var(--line); margin-top:26px; padding:16px 0 0;
  color:var(--muted); font-size:12.5px; display:flex; justify-content:space-between}
a{color:#1c4b8a}

/* the interactive maps page: the three world configurations */
.mapviews{display:flex; gap:8px; flex-wrap:wrap; margin:0 0 14px}
.mapviews button{font:inherit; font-size:13px; padding:7px 14px; cursor:pointer;
  border:1px solid var(--line); background:var(--card); color:var(--text);
  border-radius:999px}
.mapviews button.active{background:#12263f; color:#fff; border-color:#12263f}
.mapbox{position:relative; width:100%; overflow:hidden; border-radius:10px;
  border:1px solid #16344b; background-color:#02060d;
  background-image:
    radial-gradient(1px 1px at 12% 22%, rgba(190,220,245,.75), transparent),
    radial-gradient(1px 1px at 34% 68%, rgba(190,220,245,.5), transparent),
    radial-gradient(1.4px 1.4px at 58% 14%, rgba(210,232,250,.7), transparent),
    radial-gradient(1px 1px at 76% 44%, rgba(190,220,245,.45), transparent),
    radial-gradient(1.3px 1.3px at 88% 78%, rgba(210,232,250,.6), transparent),
    radial-gradient(1px 1px at 22% 86%, rgba(190,220,245,.4), transparent),
    radial-gradient(1.2px 1.2px at 46% 38%, rgba(210,232,250,.55), transparent),
    radial-gradient(1px 1px at 66% 92%, rgba(190,220,245,.45), transparent),
    radial-gradient(1px 1px at 92% 12%, rgba(210,232,250,.55), transparent),
    radial-gradient(140% 120% at 50% 50%, rgba(22,61,92,.45), transparent 70%);
}
.mapbox svg{display:block; width:100%; height:auto; touch-action:none}
.mapnote{font-size:12.5px; color:var(--muted); margin:12px 0 0; max-width:60rem}
.mapload{font-size:12.5px; color:var(--muted); margin:8px 0 0}
#maptip{position:absolute; display:none; pointer-events:none; z-index:5;
  background:rgba(8,12,20,.9); color:#fff; font-size:12px; padding:3px 7px;
  border-radius:4px; white-space:nowrap}
/* the map's own colours: OUR earth, not the pale blue-and-beige of every
   other weather site - a deep navy sea, a slate land, cool steel coasts.
   The field's own colours are the only bright thing on the map. */
.ocean{fill:#12395c; stroke:#1b4d78; stroke-width:.6}
.grat{fill:none; stroke:#4d7ea6; stroke-width:.5; stroke-dasharray:2 3; opacity:.8}
.country{fill:#33445a; stroke:#9cc0d8; stroke-width:.45}
.country:hover{fill:#4a5f79}
.lake{fill:#12395c; stroke:#1b4d78; stroke-width:.35}
.land{fill:#33445a; stroke:#9cc0d8; stroke-width:.4}
.snowband{stroke:none}
.maplegend{display:flex; align-items:center; gap:8px; flex-wrap:wrap;
  margin:0 0 10px; font-size:12px; color:var(--muted)}
.maplegend .bar{display:flex; width:100%; height:12px; border:1px solid #1c2430;
  border-radius:2px; overflow:hidden}
.maplegend .bar i{display:block; flex:1 1 0; height:100%}
/* the colour bar's keys: the ladder's own levels, every other one, on the
   same boundaries the static panels' colour bar uses */
.maplegend .keys{position:relative; width:100%; height:13px; margin-top:1px}
.maplegend .keys span{position:absolute; transform:translateX(-50%);
  font-size:10.5px; color:var(--muted); white-space:nowrap; line-height:1}
.maplegend .keys span.first{transform:translateX(0)}
.maplegend .ends{display:flex; justify-content:space-between; width:100%;
  margin-top:-2px; font-size:11px}
.outerring{fill:none; stroke:#8b97a3; stroke-width:.9}
.equator{fill:none; stroke:#8b9199; stroke-width:.8}
.pole{fill:#12263f; stroke:none}
/* the map's own controls: the zoom, on the map, where a map puts them */
.mapctl{position:absolute; right:12px; top:12px; z-index:6; display:flex;
  align-items:center; gap:4px; background:rgba(8,12,20,.82); padding:4px 6px;
  border-radius:8px; border:1px solid rgba(255,255,255,.18)}
.mapctl button{font:inherit; font-size:16px; line-height:1; width:28px; height:28px;
  cursor:pointer; color:#fff; background:rgba(255,255,255,.10); border:1px solid rgba(255,255,255,.22);
  border-radius:6px}
.mapctl button:hover{background:rgba(255,255,255,.22)}
.mapctl .zlabel{font-size:11.5px; color:#e8eef5; min-width:44px; text-align:center;
  font-variant-numeric:tabular-nums}
/* the maps page: the earth and the snowfall field are painted on a canvas
   UNDER the vectors, so the SVG's fills must not cover them */
.mapbox canvas{position:absolute; left:0; top:0; display:block; z-index:1}
.mapbox svg{position:relative; z-index:2}
.mapbox .ocean{fill:none}
.mapbox .lake{fill:none}
.mapbox .country{fill:none}
.mapbox .country:hover{fill:none; stroke:#c8860d; stroke-width:1.1}
/* the timeline: the run, one button per lead month */
.maptimeline{display:flex; gap:6px; flex-wrap:wrap; margin:0 0 10px;
  align-items:center}
.maptimeline .tlbtn{font:inherit; font-size:12.5px; padding:6px 12px;
  cursor:pointer; border:1px solid var(--line); background:var(--card);
  color:var(--text); border-radius:999px}
.maptimeline .tlbtn.on{background:#12263f; color:#fff; border-color:#12263f}
.maptimeline button.ctrl{padding:6px 11px}
"""


def write_css():
    os.makedirs(os.path.join(ASSETS, "css"), exist_ok=True)
    with open(os.path.join(ASSETS, "css", "style.css"), "w") as f:
        f.write(CSS)


# --------------------------------------------------------------------------
# shared chrome
# --------------------------------------------------------------------------
# The init line in the header is written from the models that are actually
# published, so it cannot go stale - it used to say "Nov 2026 & Oct 2026
# inits" long after every model was on the November init.
INIT_SUB = "ECMWF SEAS5 &amp; C3S seasonal systems"
_MONTH_NAMES = {"01": "January", "02": "February", "03": "March", "04": "April",
                "05": "May", "06": "June", "07": "July", "08": "August",
                "09": "September", "10": "October", "11": "November",
                "12": "December"}


def set_init_sub(reg):
    """Write the header's init line from the published models."""
    global INIT_SUB
    inits = sorted({m.get("init") for m in reg.get("models", [])
                    if m.get("init") and m.get("init") != "?"}, reverse=True)
    if not inits:
        return
    words = []
    for ini in inits:
        # The GEFS is a daily run, so its init carries a day as well
        # ("2026-11-14"), and the seasonal systems carry only the month
        # ("2026-11").  Written out, both are "November 2026", and the
        # header used to say "November 2026 & November 2026 inits".
        w = "%s %s" % (_MONTH_NAMES.get(ini[5:7], ini[5:7]), ini[:4])
        if w not in words:
            words.append(w)
    if len(words) == 1:
        txt = "%s init" % words[0]
    else:
        txt = " &amp; ".join(words) + " inits"
    INIT_SUB = ("ECMWF SEAS5 &amp; C3S seasonal systems &middot; %s" % txt)


def header(active):
    # The tabs are ABSOLUTE links: a relative "index.html" made the browser
    # show ".../seasonal-graphics/index.html" when the reader hovered the Home
    # tab, and the home page is the default entry point.
    tabs = [("index.html", "Home"),
            ("model.html", "Model"),
            ("snow.html", "Snowfall"),
            ("spv.html", "Stratosphere"),
            ("enso.html", "ENSO"),
            ("maps.html", "Maps")]
    links = "".join(
        '<a href="%s"%s>%s</a>'
        % (SITE_URL if h == "index.html" else SITE_URL + h,
           ' class="active"' if h == active else "", t)
        for h, t in tabs)
    # The site's own name is a link to its HOME PAGE - the bare directory,
    # not the "/index.html" form - so every page carries a real link to the
    # default entry point.
    return """<header class="top">
  <h1><a href="%s">Seasonal Forecast Graphics</a></h1>
  <span class="sub">%s%s</span>
  <span class="spacer"></span>
  <button class="themebtn" id="themebtn" type="button">Dark</button>
  <a href="%s" target="_blank"
     rel="noopener">GitHub</a>
</header>
<nav class="tabs">%s</nav>""" % (SITE_URL, INIT_SUB, DEV_TAG_SUB, SITE_REPO_URL, links)


def footer():
    """The data line and the handle, at the foot of every page.

    The stamp is the date the figures were built, so a reader can see how
    fresh the pages are.  The init each model is on is on its own card.
    """
    stamp = ""
    if VER:
        try:
            import datetime
            d = datetime.datetime.strptime(VER[:14], "%Y%m%d%H%M%S")
            stamp = (" &middot; the figures are from the %d %s %d build"
                     % (d.day, MONTHS[d.month - 1], d.year))
        except Exception:
            pass
    return """<footer>
  <span>Data: Copernicus CDS (ECMWF SEAS5 and C3S seasonal systems) &middot;
        ERA5 reanalysis and climatology 1991&ndash;2020 &middot;
        NOAA CORe reanalysis (the polar cap section) &middot;
        ECMWF open data%s</span>
  <span><strong>@Massachusettswx</strong></span>
</footer>""" % stamp


VER = ""

# The site's own address.  The home page is the default entry point, so the
# canonical URL of the home page is the bare directory and never the
# "/index.html" form.
#
# There are TWO sites: the operational one and the development copy.  The
# build is told which one it is making through the environment, so the
# absolute links (the nav tabs, the crumbs, the canonical tag, the title
# link) and the "GitHub" link point at the right place in each build.
#   SITE_URL        the site's base URL
#   SITE_REPO_URL   the repository the "GitHub" link goes to
#   SITE_DEV=1      mark the build as the development copy
SITE_URL = os.environ.get(
    "SITE_URL", "https://massachusettswx-weather.github.io/seasonal-graphics/")
SITE_REPO_URL = os.environ.get(
    "SITE_REPO_URL", "https://github.com/massachusettswx-weather/seasonal-graphics")
SITE_DEV = os.environ.get("SITE_DEV", "") not in ("", "0", "no", "false")
# the marker that says "this is not the operational site".  The browser tab
# can only carry plain text; the header line can be marked up.
DEV_TAG = " &middot; DEVELOPMENT COPY" if SITE_DEV else ""
DEV_TAG_SUB = " &middot; <strong>DEVELOPMENT COPY</strong>" if SITE_DEV else ""

# The development copy is PRIVATE: it sits behind a password.  GitHub Pages
# only serves public repositories on a free plan, so the repository has to
# stay public - the gate in front of the pages is what keeps the site to
# the people who have the password.  The password lives in
# data/.dev_gate_password (gitignored) or in $DEV_GATE_PASSWORD; only its
# SHA-256 hash is written into the pages, so the password itself is never
# in the published files.
def _gate_password():
    pw = os.environ.get("DEV_GATE_PASSWORD", "").strip()
    if not pw:
        pf = os.path.join(HERE, "data", ".dev_gate_password")
        if os.path.exists(pf):
            pw = open(pf).read().strip()
    return pw

GATE_PASSWORD = _gate_password() if SITE_DEV else ""
GATE_HASH = ""
# The hash of the development copy's password, as it was published.  It is
# kept here so that a wiped working tree cannot silently make the PRIVATE
# development copy public: without the password file the gate still
# refuses everyone who does not have the password, and the owner keeps the
# one they already have.  (The hash cannot be turned back into the
# password, but it does not have to - the password is what the visitor
# types, and this is what the page compares.)
GATE_HASH_FALLBACK = ("147df6f124b15703ddc1fdd2c74dde703d3333aa3382910"
                      "a411e6f5ee61b9f26")
# The hash the gate had before the password was set to a known one.  It is
# accepted as well, so a reader whose browser still carries the old login
# page is not locked out by the change - the password behind it is gone,
# so this costs nothing.
GATE_HASH_OLD = ("866da46e2e6cd6f6b5aa489cb6a738be078fe7bda1f638a3b8"
                 "bea8d1d55993c2")
if GATE_PASSWORD:
    import hashlib
    GATE_HASH = hashlib.sha256(GATE_PASSWORD.encode()).hexdigest()
elif SITE_DEV:
    GATE_HASH = GATE_HASH_FALLBACK
    sys.stderr.write(
        "no gate password file - keeping the published gate hash so the "
        "development copy stays private.\n")


def gate_script():
    """The small blocking script that guards every page.

    It runs in the <head>, before anything is drawn, so an unapproved
    visitor never sees the page - it is redirected to the login page.
    """
    if not GATE_HASH:
        return ""
    return (
        "<script>(function(){var H=%s;var O=%s;try{var g="
        "localStorage.getItem('devgate');"
        "if(g!==H&&g!==O){"
        "location.replace('login.html?_='+Date.now());return;}}catch(e){}})();</script>"
        % (json.dumps(GATE_HASH), json.dumps(GATE_HASH_OLD)))


def build_login_page():
    """The development copy's login page (login.html).

    The password is hashed in the browser with SHA-256 and compared with
    the hash in this page; on a match the hash is stored and the visitor
    is sent to the home page.
    """
    if not GATE_HASH:
        return
    stamp = ""
    if VER:
        import datetime
        try:
            d = datetime.datetime.strptime(VER[:14], "%Y%m%d%H%M%S")
            stamp = d.strftime("%d %b %Y, %H:%M UTC")
        except Exception:
            stamp = VER
    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Sign in &middot; Seasonal Forecast Graphics (development)</title>
<link rel="stylesheet" href="assets/css/style.css">
<style>
.gate{max-width:26rem;margin:4rem auto;padding:2rem;border:1px solid #d7d7d7;
 background:#fff;border-radius:8px;text-align:center}
.gate h1{font-size:1.15rem;margin:0 0 .4rem}
.gate p{font-size:.9rem;color:#555;margin:0 0 1.2rem}
.gate input{width:100%;padding:.6rem;font-size:1rem;border:1px solid #bbb;
 border-radius:4px;box-sizing:border-box}
.gate button{margin-top:.8rem;width:100%;padding:.6rem;font-size:1rem;
 border:0;border-radius:4px;background:#1f4c44;color:#fff;cursor:pointer}
.gate .err{color:#a11;min-height:1.2em;font-size:.85rem;margin:.6rem 0 0}
.gate .stamp{font-size:.72rem;color:#8a8a8a;margin:.9rem 0 0}
</style>
</head>
<body>
<div class="gate">
<h1>Seasonal Forecast Graphics</h1>
<p>Development copy &mdash; this site is private.<br>Enter the development password.</p>
<form id="f">
<input id="pw" type="password" placeholder="password" autofocus autocomplete="current-password">
<button type="submit">Sign in</button>
</form>
<p class="err" id="msg"></p>
<p class="stamp">the copy built __STAMP__</p>
</div>
<script>
var HASH=__HASH__;
var OLD=__OLD__;
/* The hash is FETCHED, not taken from this page's own copy: a browser
   that still holds an old login page would otherwise reject the current
   password forever, because the comparison happens in the browser.  The
   timestamp in the query defeats the cache, so the page always asks for
   the hash that is live now.  The inline copy is the fallback if the
   fetch fails. */
function freshHash(){
  return fetch('data/gate.json?_=' + Date.now(), {cache:'no-store'})
    .then(function(r){ return r.ok ? r.json() : null; })
    .then(function(j){ return (j && j.hash) ? j.hash : HASH; })
    .catch(function(){ return HASH; });
}
async function sha256(s){
  const b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s));
  return Array.from(new Uint8Array(b)).map(function(x){
    return x.toString(16).padStart(2,'0');}).join('');
}
document.getElementById('f').addEventListener('submit',async function(e){
  e.preventDefault();
  var live=await freshHash();
  var h=await sha256(document.getElementById('pw').value);
  if(h===live||h===HASH||h===OLD){
    try{localStorage.setItem('devgate',live);}catch(err){}
    location.replace('index.html');
  }else{
    document.getElementById('msg').textContent='That password does not match.';
  }
});
</script>
</body>
</html>""".replace("__HASH__", json.dumps(GATE_HASH))
    html = html.replace("__OLD__", json.dumps(GATE_HASH_OLD))
    html = html.replace("__STAMP__", stamp)
    with open(os.path.join(SITE, "login.html"), "w") as f:
        f.write(html)
    # the hash the login page fetches, so a cached login page still knows
    # the current password
    try:
        os.makedirs(os.path.join(SITE, "data"), exist_ok=True)
        with open(os.path.join(SITE, "data", "gate.json"), "w") as f:
            json.dump({"hash": GATE_HASH, "old": GATE_HASH_OLD}, f)
    except OSError:
        pass


def page(title, active, body, version=""):
    v = ("?v=%s" % version) if version else ""
    # the crumb back to the home page is an absolute link
    body = body.replace("__SITE__", SITE_URL)
    canonical = SITE_URL if active == "index.html" else SITE_URL + active
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s &middot; Seasonal Forecast Graphics%s</title>
<link rel="canonical" href="%s">
<link rel="stylesheet" href="assets/css/style.css%s">
%s
<script>
/* the theme is read back before anything is drawn, so a dark screen never
   flashes white */
(function(){
  try{var t=localStorage.getItem('theme');
    if(t){document.documentElement.setAttribute('data-theme',t);}}catch(e){}
})();
</script>
%s
</head>
<body>
%s
<div class="wrap">
%s
</div>
<script>
(function(){
  var b=document.getElementById('themebtn'); if(!b){return;}
  function label(){
    var t=document.documentElement.getAttribute('data-theme');
    b.textContent=(t==='dark')?'Light':'Dark';
  }
  label();
  b.addEventListener('click',function(){
    var t=document.documentElement.getAttribute('data-theme');
    t=(t==='dark')?'light':'dark';
    document.documentElement.setAttribute('data-theme',t);
    try{localStorage.setItem('theme',t);}catch(e){}
    label();
  });
})();
</script>
</body>
</html>""" % (title, DEV_TAG, canonical, v, gate_script(), header(active),
              body, footer())


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
def build_home(reg):
    """Step 1: choose a model."""
    cards = []
    for m in reg.get("models", []):
        tags = []
        tags.append('<span class="tag %s">Snowfall</span>' %
                    ("ok" if m["snow_ok"] else "no"))
        tags.append('<span class="tag %s">10 hPa wind</span>' %
                    ("ok" if m["spv_ok"] else "no"))
        tags.append('<span class="tag">%s members</span>' % m.get("members", "?"))
        tags.append('<span class="tag">init %s</span>' % m.get("init", "?"))
        cards.append("""<a class="model" href="model.html?m=%s">
  <h3>%s</h3>
  <div class="meta">%s</div>
  <div class="tags">%s</div>
</a>""" % (m["id"], m["name"], m.get("note", ""), "".join(tags)))

    # the init sentence is written from the models that are actually
    # published, so it cannot drift out of date
    by_init = {}
    for m in reg.get("models", []):
        by_init.setdefault(m.get("init") or "?", []).append(m["name"])
    # the centres whose snowfall has not arrived yet are named separately,
    # so the page says plainly that they are only half on the site
    no_snow = [(m["name"], m.get("init")) for m in reg.get("models", [])
               if not m.get("snow_ok") and (m.get("init") or "?") != "?"]
    for n, _ in no_snow:
        for k in by_init:
            if n in by_init[k]:
                by_init[k].remove(n)
        by_init = {k: v for k, v in by_init.items() if v}
    MONTHS = {"01": "January", "02": "February", "03": "March", "04": "April",
              "05": "May", "06": "June", "07": "July", "08": "August",
              "09": "September", "10": "October", "11": "November",
              "12": "December"}

    parts = []
    waiting = []
    for ini in sorted(by_init, reverse=True):
        names = by_init[ini]
        if ini in ("?", "", None):
            waiting.extend(names)
            continue
        # the init is written as YYYY-MM
        mm = "%s %s" % (MONTHS[ini[5:7]], ini[:4])
        if len(names) == 1:
            parts.append("%s from %s" % (names[0], mm))
        else:
            parts.append("%s and %s from %s" % (", ".join(names[:-1]),
                                                names[-1], mm))
    init_sentence = "; ".join(parts)
    if waiting or no_snow:
        names = waiting + [n for n, _ in no_snow]
        one = len(names) == 1
        listed = names[0] if one else ", ".join(names[:-1]) + " and " + names[-1]
        # the init these centres are on is written from the registry, so the
        # sentence follows the models instead of a month written in the code
        their_init = ""
        for n, ini in no_snow:
            if ini and ini != "?":
                their_init = "%s %s" % (_MONTH_NAMES.get(ini[5:7], ini[5:7]),
                                        ini[:4])
                break
        init_sentence += ("; %s %s on the %s init with the ENSO plume, "
                          "and publish no snowfall field"
                          % (listed, "is" if one else "are",
                             their_init or "published"))

    body = """<div class="card">
  <h2 class="sec">Step 1 &mdash; choose a seasonal model</h2>
  <p class="lead">Each model is shown from its own most recent init:
  %s.
  Pick a model and you will be taken to its list of variables &mdash;
  accumulated snowfall over the continental United States, ONI and RONI sea
  surface temperature plumes for the four ENSO regions, and the 10 hPa
  zonal-mean zonal
  wind (the stratospheric polar vortex proxy) against the ERA5
  1991&ndash;2020 climatology.
  The <a href="__SITE__spv.html#polar">polar cap section</a> is the same stratosphere
  from the other side: the 60&ndash;90&deg;N geopotential height anomaly as a
  time-height picture, in front of NOAA&rsquo;s CORe reanalysis, for the ECMWF
  SEAS5 and for NOAA&rsquo;s GEFSv12.</p>
</div>
<div class="grid c3">%s</div>
<div class="card">
  <p class="note">Snowfall is accumulated snow in inches.
  Anomalies are computed against each model's own hindcast climate.
  The 10&nbsp;hPa charts show every ensemble member, the ensemble mean, the
  ERA5 daily climatology with 10&ndash;90th and 30&ndash;70th percentile bands,
  the 1959&ndash;2020 record bounds and the model's own climate mean where
  one could be built.</p>
</div>""" % (init_sentence, "".join(cards) or "<p>No models registered yet.</p>")
    open(os.path.join(SITE, "index.html"), "w").write(page("Home", "index.html", body, VER))


def build_model_page(reg):
    """Step 2: choose a variable for the chosen model."""
    body = """<div class="card">
  <div class="crumb"><a href="__SITE__">&larr; All models</a></div>
  <div class="picker">
    <label for="modelSel">Model</label>
    <select id="modelSel" class="ctrl">%s</select>
  </div>
  <h2 class="sec" id="mName"></h2>
  <p class="lead" id="mMeta"></p>
</div>

<div class="varlist" id="varlist"></div>

<div class="card">
  <p class="note">Snowfall is accumulated snow in inches.
  Anomalies are measured against the model's own hindcast climate.
  The 10&nbsp;hPa chart shows every ensemble member, the ensemble mean, the
  ERA5 1991&ndash;2020 daily climatology with 10&ndash;90th and 30&ndash;70th
  percentile bands, the 1959&ndash;2020 record bounds and the model's own
  climate mean where one could be built.</p>
</div>"""

    sel = "".join('<option value="%s">%s</option>' % (m["id"], m["name"])
                  for m in reg.get("models", []))
    body = body % sel

    js = """
<script>
const MODELS=__MODELS__;
function q(p){const m=new URLSearchParams(location.search);return m.get(p);}
const sel=document.getElementById('modelSel');
if(q('m') && MODELS[q('m')]) sel.value=q('m');

function render(){
  const m=MODELS[sel.value];
  document.getElementById('mName').textContent=m.name;
  const init=m.init||'';
  document.getElementById('mMeta').innerHTML=(m.note||'')+
    (init?(' &middot; <strong>init '+init+'</strong>'):'');
  const vars=[];
  vars.push({
    title:'Snowfall',
    // a centre that publishes no snowfall field says so, rather than
    // showing an empty panel
    desc:(m.snow_ok)
      ? 'Accumulated snowfall over the continental United States &mdash; total for the run, each lead month, and monthly anomalies with a drag bar.'
      : 'This centre publishes no snowfall field in the seasonal archive, so there are no snowfall panels for it.',
    href:'snow.html?m='+m.id,
    img:(m.total&&m.total.file)||((m.frames||[]).length&&m.frames[0].file)||'',
    on:!!m.snow_ok,
    // the description already says why there is nothing to open
    explained:!m.snow_ok
  });
  vars.push({
    title:'10 hPa zonal-mean zonal wind',
    desc:'The stratospheric polar vortex proxy in m/s, all members and the ensemble mean against the ERA5 1991&ndash;2020 climatology.',
    href:'spv.html?m='+m.id,
    img:(m.spv&&m.spv['60']&&m.spv['60'].file)||'',
    on:!!m.spv_ok
  });
  vars.push({
    title:'Polar cap geopotential height',
    desc:'A time-height section of the polar cap (60-90N): the normalized geopotential height anomaly in standard deviations of the CORe reanalysis&rsquo;s own 1991-2020 climate, from 10 hPa down to the surface. A seasonal model&rsquo;s forecast is measured against its own hindcast climate.',
    href:'spv.html?m='+m.id+'#polar',
    img:(m.polar&&m.polar.file)||'',
    on:!!m.polar_ok
  });
  vars.push({
    title:'ENSO plumes',
    desc:'The sea surface temperature plume for the four ENSO regions, with the observed analysis in front of it.',
    href:'enso.html?m='+m.id,
    img:(m.enso&&m.enso.length)?m.enso[0].file:'',
    on:!!m.enso_ok
  });
  document.getElementById('varlist').innerHTML=vars.map(v=>
    `<div class="var ${v.on?'':'off'}">
       <div class="thumb">${v.img?'<img src="'+v.img+'" alt="">':''}</div>
       <div class="body">
         <h3>${v.title}</h3>
         <p>${v.desc}</p>
         <div class="acts">${v.on
            ?'<a class="btn primary wide" href="'+v.href+'">Open</a>'
            :(v.explained?'':'<span class="tag no">not available for this model</span>')}</div>
       </div>
     </div>`).join('');
}
sel.addEventListener('change',render);
render();
</script>"""
    body += js.replace("__MODELS__", json.dumps(public_map(reg)))
    open(os.path.join(SITE, "model.html"), "w").write(page("Model", "model.html", body, VER))


def build_snow(reg):
    """Step 3a: the snowfall page."""
    models = [m for m in reg.get("models", []) if m["snow_ok"]]
    sel = "".join('<option value="%s"%s>%s</option>'
                  % (m["id"], " selected" if m["id"] == "ecmwf-seas5" else "",
                     m["name"]) for m in models)
    body = """<div class="card">
  <div class="crumb"><a href="__SITE__">&larr; All models</a> &middot;
    <a href="model.html">Choose a variable</a></div>
  <h2 class="sec">Snowfall</h2>
  <p class="lead">Accumulated snowfall over the continental United States, in
  inches, on a 0&ndash;300&nbsp;in colour scale. Each model is shown over the
  lead months its own forecast covers, with the season cut at 01 July 2027.
  Anomalies are measured against the model's own hindcast climate.</p>
  <div class="picker">
    <label for="modelSel">Model</label>
    <select id="modelSel" class="ctrl">%s</select>
  </div>
</div>

<div class="card" id="tab-total">
  <h2 class="sec" id="totalHead">Total accumulation</h2>
  <p class="lead" id="totalCap"></p>
  <div class="stage"><img id="totalImg" alt="Total accumulated snowfall"></div>
  <p class="lead" id="totalNote" style="display:none"></p>
</div>

<div class="card" id="tab-monthly">
  <h2 class="sec">Accumulation by lead month</h2>
  <p class="lead">One panel per lead month of the run. Every month uses the same
  0&ndash;300&nbsp;in scale as the totals, so the months add up to the total in
  the same colours. No snowfall is white.</p>
  <div class="grid c2" id="monthlyGrid"></div>
</div>

<div class="card" id="tab-anom">
  <h2 class="sec">Monthly anomaly</h2>
  <p class="lead">Drag the bar to step through the lead months. Values are
  the anomaly against the model's own hindcast climate, in the units selected
  above.</p>
  <div class="stage"><img id="anomImg" alt="Monthly snowfall anomaly"></div>
  <div class="slider">
    <span class="frameLabel" id="anomLabel">&mdash;</span>
    <input type="range" id="anomRange" min="0" max="0" value="0" step="1">
    <button class="ctrl ghost" id="anomPrev">&#8592;</button>
    <button class="ctrl ghost" id="anomNext">&#8594;</button>
  </div>
  <div class="cap" id="anomCap"></div>
</div>""" % sel

    js = """
<script>
const MODELS = __MODELS__;

function q(p){const m=new URLSearchParams(location.search);return m.get(p);}
const sel=document.getElementById('modelSel');
// A model with no snowfall panel cannot be shown on this page.  Setting the
// select to a model that is not one of its options empties the select, and
// every panel below then breaks on an undefined model.
if(q('m') && MODELS[q('m')] && MODELS[q('m')].total) sel.value=q('m');

function model(){return MODELS[sel.value];}

function pick(o){return o.file||'';}

function renderTotal(){
  const m=model();
  const t=m.total;
  const img=document.getElementById('totalImg');
  const note=document.getElementById('totalNote');
  if(!t||!t.file){
    // a centre that publishes no snowfall field
    img.removeAttribute('src');
    img.style.display='none';
    document.getElementById('totalCap').textContent='';
    document.getElementById('totalHead').textContent='No snowfall';
    note.textContent=(m.note||'');
    note.style.display='block';
    return;
  }
  img.style.display='';
  note.style.display='none';
  img.src=pick(t);
  img.alt=t.caption;
  document.getElementById('totalCap').textContent=(t.caption||'');
  // the heading carries the run's own dates, the way the figure titles do
  const d=((t.caption||'').match(/(\d{2}\/\d{2}\/\d{4})\s*(?:to|-)\s*(\d{2}\/\d{2}\/\d{4})/)||[]);
  document.getElementById('totalHead').textContent=
    d.length?('Total accumulation \u2014 '+d[1]+' to '+d[2]):'Total accumulation';
}

function renderMonthly(){
  const m=model();
  const g=document.getElementById('monthlyGrid');
  const months=m.months||[];
  if(!months.length){
    g.innerHTML='<p class="lead">This centre publishes no snowfall field in '
      +'the seasonal archive, so there are no snowfall panels for it. Its '
      +'ENSO plume is on the ENSO page.</p>';
    return;
  }
  g.innerHTML=months.map(x=>
    `<div class="stage"><img src="${pick(x)}" alt="${x.label}"><div class="cap">${x.label} &mdash; ${x.caption}</div></div>`
  ).join('');
}

function renderAnom(i){
  const m=model();
  const card=document.getElementById('tab-anom');
  if(!((m.frames||[]).length)){
    if(card) card.style.display='none';
    const im=document.getElementById('anomImg');
    if(im) im.src='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
    return;
  }
  if(card) card.style.display='';
  const fr=(m.frames||[])[i];
  if(!fr) return;
  document.getElementById('anomImg').src=pick(fr);
  document.getElementById('anomImg').alt=fr.label;
  document.getElementById('anomLabel').textContent=fr.label;
  document.getElementById('anomCap').textContent=fr.caption||'';
}

function setFrame(i){
  const m=model();
  const r=document.getElementById('anomRange');
  const nf=(m.frames||[]).length;
  i=Math.max(0,Math.min(nf-1,i));
  r.value=i; renderAnom(i);
}

function renderAll(){
  renderTotal(); renderMonthly();
  const m=model();
  const r=document.getElementById('anomRange');
  const nf=(m.frames||[]).length;
  r.max=String(Math.max(0,nf-1));
  setFrame(0);
}

sel.addEventListener('change',renderAll);
document.getElementById('anomRange').addEventListener('input',e=>setFrame(+e.target.value));
document.getElementById('anomPrev').addEventListener('click',()=>setFrame(+document.getElementById('anomRange').value-1));
document.getElementById('anomNext').addEventListener('click',()=>setFrame(+document.getElementById('anomRange').value+1));
document.addEventListener('keydown',e=>{
  if(e.key==='ArrowLeft') setFrame(+document.getElementById('anomRange').value-1);
  if(e.key==='ArrowRight') setFrame(+document.getElementById('anomRange').value+1);
});
renderAll();
</script>"""
    body += js.replace("__MODELS__", json.dumps(public_map(reg)))
    open(os.path.join(SITE, "snow.html"), "w").write(page("Snowfall", "snow.html", body, VER))


def build_enso(reg):
    """The ENSO page: one plume chart, with the model, index and region picked
    from the menus."""
    models = [m for m in reg.get("models", []) if m.get("enso_ok")]
    sel = "".join('<option value="%s"%s>%s</option>'
                  % (m["id"], " selected" if m["id"] == "ecmwf-seas5" else "",
                     m["name"]) for m in models)
    basins = ["Nino 3.4", "Nino 3", "Nino 4", "Nino 1+2"]
    bsel = "".join('<option value="%s">%s</option>' % (b, b) for b in basins)
    body = """<div class="card">
  <div class="crumb"><a href="__SITE__">&larr; All models</a></div>
  <h2 class="sec">ENSO</h2>
  <p class="lead">Sea surface temperature anomaly in each of the four ENSO
  regions, against the 1991&ndash;2020 climatology of the same basin and month.
  The thick red line is the ensemble mean, the light red lines are the
  members, the shaded envelope is the member spread, and the black line in
  front is the observed analysis &mdash; NOAA&rsquo;s ERSST v6, the dataset
  NOAA/CPC builds the ONI and the RONI from, carried into the current,
  still-running month by NOAA&rsquo;s OI SST v2.1, which is produced daily
  with a one-day latency. <b>ONI</b> is the plain anomaly;
  <b>RONI</b> has the tropical-mean (20&deg;S&ndash;20&deg;N) SST anomaly
  subtracted and is rescaled to the ONI&rsquo;s own spread, so it says whether
  the Pacific is warm or cold <i>relative to the rest of the ocean</i>. The
  forecast is re-levelled onto the analysis, so the plume continues from the
  observation instead of starting a degree above it.</p>
  <div class="picker">
    <label for="modelSel">Model</label>
    <select id="modelSel" class="ctrl">%s</select>
    <label for="indexSel">Index</label>
    <select id="indexSel" class="ctrl">
      <option value="oni">ONI &mdash; absolute anomaly</option>
      <option value="roni" selected>RONI &mdash; relative anomaly</option>
    </select>
    <label for="basinSel">Region</label>
    <select id="basinSel" class="ctrl">%s</select>
  </div>
</div>

<div class="card">
  <h2 class="sec">Plume chart</h2>
  <div class="grid c1" id="ensoGrid"></div>
</div>""" % (sel, bsel)

    js = """
<script>
const MODELS = __MODELS__;
const sel=document.getElementById('modelSel');
const isel=document.getElementById('indexSel');
const bsel=document.getElementById('basinSel');
function render(){
  const m=MODELS[sel.value];
  const kind=isel.value, basin=bsel.value;
  const g=document.getElementById('ensoGrid');
  if(!m||!m.enso){g.innerHTML='<p class="lead">No ENSO plumes for this model.</p>';return;}
  const row=m.enso.find(e=>e.index===kind && e.basin===basin);
  if(!row){g.innerHTML='<p class="lead">No ENSO plume for this model.</p>';return;}
  g.innerHTML='<figure class="panel"><img loading="lazy" src="'+row.file+'" alt="'+row.caption+'">'+
    '<figcaption>'+row.caption+'</figcaption></figure>';
}
if((new URLSearchParams(location.search).get('m'))&&
   MODELS[new URLSearchParams(location.search).get('m')]){
  sel.value=new URLSearchParams(location.search).get('m');
}
sel.addEventListener('change',render);
isel.addEventListener('change',render);
bsel.addEventListener('change',render);
render();
</script>"""

    body = body + js
    body = body.replace("__MODELS__", json.dumps(
        {m["id"]: {"name": m["name"], "enso": m.get("enso", [])} for m in models}))
    open(os.path.join(SITE, "enso.html"), "w").write(page("ENSO", "enso.html", body, VER))


def build_spv(reg):
    """Step 3b: the zonal wind page."""
    models = [m for m in reg.get("models", []) if m["spv_ok"]]
    sel = "".join('<option value="%s"%s>%s</option>'
                  % (m["id"], " selected" if m["id"] == "ecmwf-seas5" else "",
                     m["name"]) for m in models)
    body = """<div class="card">
  <div class="crumb"><a href="__SITE__">&larr; All models</a> &middot;
    <a href="model.html">Choose a variable</a></div>
  <h2 class="sec">Stratosphere &mdash; 10 hPa zonal-mean zonal wind</h2>
  <p class="lead">The stratospheric polar vortex proxy at 10&nbsp;hPa, in m/s.
  Each model is shown over its own total lead days, against the
  ERA5 1991&ndash;2020 climatology. Below it is the polar-cap
  geopotential height section, the same atmosphere seen from the other
  side.</p>
  <div class="picker">
    <label for="modelSel">Model</label>
    <select id="modelSel" class="ctrl">%s</select>
    <label for="domSel">Domain</label>
    <select id="domSel" class="ctrl">
      <option value="60">60&deg;N</option>
    </select>
  </div>
</div>

<div class="card">
  <div class="stage"><img id="spvImg" alt="10 hPa zonal-mean zonal wind"></div>
  <div class="cap" id="spvCap"></div>
</div>

<div class="card">
  <h2 class="sec">Lead-month means</h2>
  <div id="tblWrap"></div>
</div>""" % sel

    js = """
<script>
const MODELS=__MODELS__;
function q(p){const m=new URLSearchParams(location.search);return m.get(p);}
const sel=document.getElementById('modelSel');
const dom=document.getElementById('domSel');
// This page is the 10 hPa wind page: a model with no wind panel (a
// sub-seasonal run, say) is not one of the options, and selecting it would
// empty the select and break every panel below.
if(q('m') && MODELS[q('m')] && MODELS[q('m')].spv) sel.value=q('m');
if(q('d') && MODELS[sel.value] && MODELS[sel.value].spv
   && MODELS[sel.value].spv[q('d')]) dom.value=q('d');
function model(){return MODELS[sel.value];}
function render(){
  const m=model();
  const d=dom.value;
  const p=(m.spv||{})[d];
  const img=document.getElementById('spvImg');
  if(!p){
    img.removeAttribute('src'); img.alt='';
    document.getElementById('spvCap').textContent='No 10 hPa panel for this model.';
    return;
  }
  img.src=p.file; img.alt=p.caption;
  document.getElementById('spvCap').textContent=p.caption;
  const t=p.table;
  document.getElementById('tblWrap').innerHTML = t ?
    `<table><thead><tr><th>Lead month</th>${t.head.map(h=>`<th>${h}</th>`).join('')}</tr></thead>
     <tbody>${t.rows.map(r=>`<tr><td>${r[0]}</td>${r.slice(1).map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table>`
    : '<p class="note">No table for this model and domain.</p>';
}
sel.addEventListener('change',render); dom.addEventListener('change',render);
render();
</script>"""
    body += js.replace("__MODELS__", json.dumps(public_map(reg)))

    # the polar-cap height section lives on the same page: it is the
    # stratosphere seen from the other side
    try:
        import build_polar_page
        body += build_polar_page.polar_block(reg)
        build_polar_page.remove_old_page()
    except Exception as e:
        print("   the polar-cap section was skipped: %s" % str(e)[:120])

    open(os.path.join(SITE, "spv.html"), "w").write(page("Stratosphere", "spv.html", body, VER))


def build_maps_page(reg):
    """The interactive Natural Earth maps page.

    One map and one timeline: the whole world with the seasonal snowfall
    painted on it.  The field is the model's own output - every grid cell
    the model came on, nothing resampled - and it can be read as the
    accumulated snowfall or as the anomaly against that model's own
    hindcast climate.  Three views of the same geography - the flat world,
    the globe and the polar region - drawn in the
    browser from the Natural Earth 1:50m files that are committed to the
    repository.  The script and the map data are copied into the site by
    copy_map_assets().
    """
    body = """<div class="card">
  <div class="crumb"><a href="__SITE__">&larr; All models</a> &middot;
    <a href="maps.html">Maps</a></div>
  <h2 class="sec">Maps</h2>
  <p class="lead">One map and one timeline: the whole world with the
  seasonal snowfall painted on it, drawn from Natural Earth 1:50m data.
  The field is the model's own output - every grid cell the model came on,
  nothing resampled - and it can be read as the accumulated snowfall or as
  the anomaly against that model's own hindcast climate. The map can be
  the flat world on an equirectangular grid, the globe you can spin, or
  the polar projection with the pole at the centre. Zoom in and out with
  the buttons on the map, with the scroll wheel or with the keyboard, and
  drag the flat map to pan it.</p>
  <div class="mapviews" id="mapviews">
    <button data-view="flat">2D Map</button>
    <button data-view="globe" class="active">3D Globe</button>
    <button data-view="polar">Polar</button>
  </div>
  <div class="picker">
    <label for="snowModel">Model</label>
    <select id="snowModel" class="ctrl"></select>
    <div class="seg" id="snowfield">
      <button class="segbtn ghost on" data-field="total">Snowfall</button>
      <button class="segbtn ghost" data-field="anom">Anomaly vs the model's own climate</button>
    </div>
  </div>
  <div class="maplegend" id="maplegend"></div>
  <div class="maptimeline" id="maptimeline"></div>
  <div class="mapbox" id="mapbox">
    <canvas id="mapcanvas"></canvas>
    <svg id="mapsvg"></svg>
    <div id="maptip"></div>
  </div>
  <p class="mapload" id="mapload" style="display:none">Loading the map data&hellip;</p>
  <p class="mapnote" id="mapnote"></p>
</div>

<script src="assets/js/d3.v7.min.js?v=%s"></script>
<script src="assets/js/maps.js?v=%s"></script>""" % (VER, VER)
    open(os.path.join(SITE, "maps.html"), "w").write(
        page("Maps", "maps.html", body, VER))


def copy_map_assets():
    """Copy the map script, the library and the Natural Earth files.

    The Natural Earth data is committed to the repository, so the site
    never depends on a download at build time.
    """
    import shutil
    jsdir = os.path.join(ASSETS, "js")
    os.makedirs(jsdir, exist_ok=True)
    shutil.copy(os.path.join(HERE, "assets", "js", "d3.v7.min.js"),
                os.path.join(jsdir, "d3.v7.min.js"))
    shutil.copy(os.path.join(HERE, "assets", "js", "maps.js"),
                os.path.join(jsdir, "maps.js"))
    nedir = os.path.join(ASSETS, "ne")
    os.makedirs(nedir, exist_ok=True)
    for fn in ("ne_50m_admin_0_countries.geojson",
               "ne_50m_lakes.geojson",
               "ne_50m_land.geojson"):
        src = os.path.join(HERE, "data", fn)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(nedir, fn))


def write_readme():
    """The README's link points at the site this build belongs to.

    The development copy and the operational site are two repositories, so
    each one's README has to lead to its own site.  The link is rewritten by
    pattern, not by a placeholder, because the build also WRITES the README
    back - a placeholder would be consumed by the first build and the second
    one would have nothing to replace.
    """
    import re
    p = os.path.join(HERE, "README.md")
    if not os.path.exists(p):
        return
    with open(p) as f:
        s = f.read()
    new = re.sub(r"(\*\*\[Seasonal Forecast Graphics\]\()[^)]*(\)\*\*)",
                 lambda m: m.group(1) + SITE_URL + m.group(2), s)
    if new != s:
        with open(p, "w") as f:
            f.write(new)


def main():
    os.makedirs(os.path.join(ASSETS, "css"), exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    write_css()
    reg = load_registry()
    global VER
    VER = reg.get("version", "")
    set_init_sub(reg)
    build_home(reg)
    build_model_page(reg)
    build_snow(reg)
    build_enso(reg)
    build_spv(reg)
    build_maps_page(reg)
    copy_map_assets()
    if SITE_DEV:
        build_login_page()
    else:
        # the operational site has no gate - make sure no login page is
        # left over from a development build
        lp = os.path.join(SITE, "login.html")
        if os.path.exists(lp):
            os.remove(lp)
    write_readme()
    print("site built:", SITE)
    if SITE_DEV:
        print("  THE DEVELOPMENT COPY -> %s" % SITE_URL)
    for m in reg.get("models", []):
        print("  %-16s snow=%s spv=%s" % (m["id"], m["snow_ok"], m["spv_ok"]))


if __name__ == "__main__":
    main()
