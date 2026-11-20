# The state of the project

**This file is the handoff.** It is tracked in git on purpose: when the
sandbox is wiped, the working tree goes with it, but this file comes back
with the repository. Read it first, and update it before you end a session.

Last updated: **17 Nov 2026, 19:05 UTC** (after the sandbox wipe of 16-17 Nov,
after the global map rebuild, and after the auto-run was wired)

## The two sites

| | repository | address |
|---|---|---|
| **dev** | `massachusettswx-weather/seasonal-graphics-dev` | <https://massachusettswx-weather.github.io/seasonal-graphics-dev/> |
| **operational** | `massachusettswx-weather/seasonal-graphics` | <https://massachusettswx-weather.github.io/seasonal-graphics/> |

The old name `seasonal-snow` no longer exists - the repository was renamed
to `seasonal-graphics`, and the old address 404s.

**Nothing goes on the operational site without the owner's explicit
approval.** Everything is built and checked on the dev site first.

## What the site has

* `index.html` - pick a model
* `model.html` - that model's variables
* `snow.html` - snowfall: the total for the run, the per-lead-month totals,
  the monthly anomalies against the model's own hindcast climate
* `spv.html` - 10 hPa zonal-mean zonal wind (60N and NH)
* `enso.html` - the ENSO plumes
* `maps.html` - the interactive maps: the whole world in three
  configurations (flat equirectangular, a draggable orthographic globe, a
  north-polar disc)

### The interactive maps (17 Nov 2026) - REBUILT as one big world map

`export_snow_map.py` -> `docs/data/snowmap_<tag>.json` + one 8-bit
greyscale PNG per field -> `assets/js/maps.js`.

**The field is now the WHOLE WORLD on the model's own grid** - no
interpolation, no resampling - and it comes in two flavours: the
accumulated snowfall, and the **anomaly against that model's own hindcast
climate** (the only honest baseline; the ECCC is genuinely ~3x drier).

The map is one canvas with the vectors on top:
* the earth (ocean, land, lakes) is painted on the canvas, the field is
  painted over it, and the coastlines are drawn in the SVG above;
* the field is drawn **pixel by pixel**: d3's `projection.invert()` turns
  each screen pixel back into a longitude and a latitude, and the field is
  sampled there.  The inverse is the expensive part, so it is cached as a
  **sampling plan** per view and the timeline only re-reads the field;
* the controls: the model, the field (snowfall / anomaly), a **timeline**
  (the run total and one button per lead month, with a play button), and
  the three views (flat / globe / polar).  The globe can be dragged to
  spin, the flat map dragged to pan, the polar map dragged to spin around
  the pole, and **every view zooms** - the buttons on the map (out, the
  zoom, in, reset), the scroll wheel (about the pointer) or the keyboard
  (`+`, `-`, `0`).

**THE MAP CARRIES NO POLAR-SECTION FURNITURE.** The North Pacific and
North Atlantic sector wedges and their labels belonged to the stratosphere
page; they were painted over the Arctic on the snowfall map and had to go,
and so did the 60N cap edge.  The maps page is a snowfall map, not a second
copy of the polar charts.

**WHICH MODELS ARE ON THE MAP:** only the ones with a **global** field on
disk - the NOAA SFSv1 (its own 0.5 degree grid, the sharpest field on the
site) and the NOAA CFSv2 (1.5 degree).  The CFSv2 is global because
`fetch_era5_snow_arco.py --box global` builds the ERA5 1991-2020 snowfall
climatology over the whole world and checkpoints **every year**
(`data/era5_clim_ckpt/`), so a sandbox rebuild resumes the pull instead of
starting again.  The C3S centres (ECMWF SEAS5, UKMO, METFR, ECCC canSIPS,
CMCC, DWD) join the map by themselves the moment their global GRIBs are
fetched - the exporter and the model picker are data-driven - but **that
needs the CDS key**, which is not in the secret store yet.

**THE DOMAIN TRAP (fixed 17 Nov 2026):** the sampling plan used to wrap
the longitude (`% nlon`) instead of checking it against the model's own
grid, so a field that does **not** cover the whole world was smeared
around the entire globe - once round for every degree of longitude.  The
longitude is now checked against the model's own domain, in the model's
own convention (a field with `lon0 >= 0` is compared in 0..360, one with
`lon0 < 0` in -180..180); a global field still wraps, which is what it
must do.  `tools/test_maps_page.py` checks that no sector furniture is on
the map and that the zoom works.

The two traps that are already known and fixed:

* the exporter's flat array runs **lon-major** and the browser walks it
  **lat-major** - writing one and reading the other turns a smooth field
  into horizontal stripes while the JS still draws 48 colour bands and
  shows no error. The transpose happens on the way out.
* d3's `rotate([lambda, phi])` puts `(-lambda, -phi)` at the centre of an
  orthographic globe, so the globe opens over North America with
  `rot: [95, -35]`.

**Two more traps this time round:**
* `projection.invert()` does NOT clip: on the globe it answers for the far
  side of the world as well, so the field was painted on the dark sky
  outside the limb.  The plan now skips the pixels outside the disc (the
  globe's radius is the scale; the polar disc's radius is `k * pi / 2`).
* a sector ring that jumps across the antimeridian is drawn as a line
  straight across the map - the longitudes have to stay **unwrapped** and
  let d3 cut the antimeridian.

### The tests

* `tools/test_export_map.py` - the exporter against a synthetic model: the
  unit arithmetic, the anomaly against the model's own climate, the mask,
  the ladder quantisation and the raster sizes.  All the checks pass.
* `tools/test_maps_page.py` - the page in a headless browser with a
  synthetic model: the globe, the flat map, the timeline
  and the anomaly toggle, with the console watched for errors.

**Both tests need no key and no queue - they run in seconds.**  That is
the point: the code can be checked while the store is busy.

Two traps that are already known and fixed:

* the exporter's flat array runs **lon-major** and the browser walks it
  **lat-major** - writing one and reading the other turns a smooth field
  into horizontal stripes while the JS still draws 48 colour bands and
  shows no error. The transpose happens on the way out.
* d3's `rotate([lambda, phi])` puts `(-lambda, -phi)` at the centre of an
  orthographic globe, so the globe opens over North America with
  `rot: [95, -35]`.

## The models on the site

ECMWF SEAS5 (51), UKMO GloSeas6-GC5.1 (60), Meteo-France System 9 (51),
ECCC canSIPS (40, the pooled 40-member official ensemble of CanESM5.1p1bc
and GEM5.2-NEMO), CMCC SPS4 (50), DWD GCFS2.2 (50), JMA JRA3-25,
BOM ACCESS-S2, NOAA SFSv1 (31), NOAA CFSv2 (40), C3S Multi-Model Mean.

The JMA and the BoM carry no snowfall in the C3S seasonal product
(`MarsNoDataError` on param 172144) - the ENSO plume and the 10 hPa wind
only.

## The auto-run (17 Nov 2026, overnight)

The pipeline now keeps itself up, and the DEVELOPMENT site is the only
target it ever pushes to.

* **The publisher** (`auto_publish.sh`) watches the model data and, when
  anything changes, rebuilds the panels, **the map**, the registry and the
  pages, commits and pushes.  The map export is now in that chain
  (`export_snow_map.py`), so the world map can never be a month out of
  date with the panels.
* **It builds the DEVELOPMENT site.**  `SITE_DEV=1` and the dev addresses
  are exported in the publisher: without that, a build made while the
  token was missing would commit an operational copy into the development
  repository - a stale copy of the live site on the dev address.
* **`tools/auto_run.sh`** is the one command that puts everything back
  after a sandbox rebuild: the python packages, the credentials (from the
  encrypted secret store, as environment variables), and the workers.
* **`tools/bootstrap.sh`** does the whole rebuild from nothing: it clones
  the repository, restores the packages and the credentials, and recovers
  the model data from the tracked job ids.
* **A scheduled task keeps it alive.**  `seasonal-pipeline-keepalive`
  runs every 20 minutes: it puts the workers back after each rebuild and
  recovers the model data.  The scheduler lives in the daemon, so it
  survives the sandbox rebuilds that kill the workers.
* **The verifier works again**: it uses the full Chromium (the installed
  Playwright wants a headless shell that is not here), it checks the maps
  page on the dev copy, and it sets the gate hash so it sees the real
  pages instead of the login form.

### The world map's data, so far

* **NOAA SFSv1** - the WHOLE WORLD on the model's own **0.5 degree**
  grid (361 x 720), with the anomaly against the model's own 35-year
  reforecast climate.  `fetch_sfs.py` now writes
  `snowfall_monthly_global.npz` and `snowfall_hindcast_global.npz`
  beside the eastern-US files, and the exporter prefers them.  This is
  the highest resolution field on the site.
* **The C3S systems** (ECMWF, UKMO, METFR, ECCC, CMCC, DWD) are ready
  and waiting: the exporter and the renderer take their global fields as
  they land, but the fields themselves need the CDS key.
* **The JMA and the BoM** have no snowfall in the C3S product at all.
* The stale CONUS map files for the six C3S centres were removed - the
  new page cannot read the old format, and the exporter rewrites them
  when the data comes back.

## In flight

* **The C3S November init** is still rolling out centre by centre. ECMWF
  releases on the 6th of the month at 12 UTC, every other centre on the
  10th at 12 UTC, so a centre answering "no data" for the new init is
  normal until C3S has staged it.
* **The EC46** (the ECMWF sub-seasonal ensemble for the polar section) is
  outstanding; the ECDS processed nothing for the account after 02:58Z on
  15 Nov. The jobs are recorded in `data/polar_ec46_jobs.json`, so a
  restarted fetcher adopts them instead of re-requesting them.

## The wipe of 16-17 Nov 2026, and what it taught

The working tree came back **empty**: no repository, no `data/`, no
`docs/`. What survived was on GitHub (both repositories) and in the agent's
memory. The parts that were lost and the parts that were not:

| lost | survived |
|---|---|
| `data/models/**` - every model GRIB and hindcast climate | all the code |
| `.cdsapirc`, `data/.github_token` - the credentials | the published site |
| the python packages | `data/models_fetched.json`, the ERA5 and m7 climatologies |
| | `docs/data/*.json` - the map fields, the registry |

The lesson is now in `notes/PROTECTION.md` and in `tools/bootstrap.sh`:
**the job ids are tracked**, so the data can be downloaded again from the
store without queueing for it, and the credentials live in the encrypted
secret store, which survives the reset.

## The rules that are not negotiable

1. **Nothing on the operational site without the owner's explicit
   approval.** The dev site is where everything is built and checked.
2. **A plan before any new data pull, a new chart family, a new route or a
   new background worker** - with the cost of each option (queue time,
   requests, hours of work). Read-only checks do not need a plan.
3. **One submitter at a time.** The box has 2 CPUs and 3 GB of RAM.
4. Never commit a `*.part` file, never edit a running script, and never
   run the publisher by hand while the publisher is alive.
5. A chart ends with its own model's run, and the climatology layer is
   clipped with it.
6. A climatology comes from the **same product** as the data it
   normalises. The anomalies use **each model's own hindcast climate** -
   the ECCC is genuinely about 3x drier than the others, and that is a
   model property, not a bug.

## 17 Nov, evening: the credentials are in, and one blocker left

The **CDS key** and the **GitHub PAT** are in the encrypted secret store
(`CDS_API_KEY`, `GITHUB_TOKEN`).  `tools/restore_secrets.sh` writes them
into `.cdsapirc` and `data/.github_token` (both gitignored) and the
keepalive does it on every rebuild, so neither has to be pasted again.

**The C3S pull is running.**  The queue worker is back through the
centres - the ECCC's two systems landed first (23.3 MB of monthly
snowfall each) - and the map gets every centre on its own 1 degree
global grid as its GRIB arrives.

**The one blocker: the PAT cannot push the dev repo.**  The token
belongs to `massachusettswx-weather`, which has **pull-only** on
`massachusettswx-weather/seasonal-graphics-dev` (GitHub says `permissions: {push:
false}`) and owns the **operational** repo, which is not to be touched
without approval.  Two ways out, both the owner's call:
  - add `massachusettswx-weather` as a collaborator with write access on
    `massachusettswx-weather/seasonal-graphics-dev` (keeps the dev URL); or
  - let the dev copy live in a repo the token owns
    (`massachusettswx-weather/seasonal-graphics-dev`), which changes the
    dev URL but lets the pipeline run unattended from then on.

### Two things fixed while the credentials were going in

- `run_nov_queue.py:target_for()` now makes the model's own folder.  A
  wiped tree takes `data/models/*` with it, and every download was
  landing on a missing directory and being thrown away - the ECCC
  request came back three times and was lost each time.
- `push_to_github.sh` no longer refuses to publish a dev copy when the
  plaintext gate password is missing (it was lost with the tree too).
  The builder keeps the **published gate hash**, so the owner keeps the
  password they already have, and the publisher now **verifies the gate
  is in the built pages** before anything is pushed - a development copy
  without a gate is never published.

### The development copy has moved (17 Nov, 20:05)

The PAT in the secret store belongs to `massachusettswx-weather`, which
has **pull-only** on `Matthew22-cmd/seasonal-graphics-dev` - so the
pipeline could not publish anywhere.  The development copy now lives in
**`massachusettswx-weather/seasonal-graphics-dev`**, a repository of its
own that the token owns, and the site is live at
<https://massachusettswx-weather.github.io/seasonal-graphics-dev/> (the
same password gate, the same pages).  **The operational repository is
untouched** - it is still `massachusettswx-weather/seasonal-graphics`,
and `--prod` still needs the owner's explicit approval.

The old URL (`Matthew22-cmd/seasonal-graphics-dev`) still serves the
build from before the map corrections, and it cannot be updated from
here.  To put the development copy back under the personal account, add
`massachusettswx-weather` as a write collaborator on that repository and
point the script at it with `GITHUB_DEV_OWNER=Matthew22-cmd`.

Two things that had to be fixed to get the first push through:
- the local clone was **shallow** (depth 50 from the old repo), so
  pushing to an empty repository failed with "did not receive expected
  object".  The full history was fetched once; after that a depth-50
  clone pushes cleanly (tested), which is what the keepalive does after
  every rebuild.
- `push_to_github.sh` now derives the development URL from
  `GITHUB_DEV_OWNER` instead of hard-coding the old owner.

### The map now IS the static map (17 Nov, 20:30)

The owner: "these maps are terrible - they have to use the same maps as
the static one, but with this interactive configuration and worldwide
outputs."  Two things were wrong, and both are fixed:

- **The browser had a ramp of its own.**  The exporter wrote a 48-step
  interpolation of the ladder, so the map's greys were muddy, its blues
  soft and its magenta not the published one.  The exporter now writes
  the ladder's own table - a 256-entry byte -> colour list built with the
  same `BoundaryNorm(levels, cmap.N, clip=True)` the static panels use -
  and the browser reads that.  **Over the top of the ladder is now the
  top colour, not a white hole**, which is what the white streaks in the
  northern United States were.  Checked against the published panel:
  45N 100W is `#b1dbe7` in both, 33N 100W is `#882b9a` in both - the map
  is the same map, worldwide and interactive.
- **The global CFSv2 field was ten times too big.**  `fetch_cfsv2.py`'s
  global path resampled the CPC anomaly onto the climatology's 0..360
  grid while the CPC grid runs -179..180, so the interpolation ran off
  the end of the source array and extrapolated.  The longitudes are now
  put in the same convention first.  The global and the CONUS fields now
  agree (35.9 in vs 35.6 in at 45N 100W).

### The owner's 17 Nov late corrections: the keys, our colours, dark mode

- **The colour bar now carries its keys** - the ladder's own levels,
  every other one (0.01, 1, 3, 5, 7, 9, 13, 17, 21, 26, 36, 52, 72, 108,
  156, 216), on the same boundaries the static panels' colour bar uses.
  The map legend was a stripe with two numbers on it; the panels' bar
  has always had the keys, and the map is the same map.
- **The map has OUR earth, not the pale blue-and-beige** every other
  weather site uses: a deep navy sea (#0d2233), a slate land (#2a3642),
  cool steel coastlines.  The field's own colours are now the only
  bright thing on the map.  The bottom of the ladder ("no snow") is
  transparent on the map - on the static panels it is the white of the
  paper, and on a dark map a white fringe round every snow field is
  exactly the artefact the owner complained about.
- **The site has a dark mode**: a button in the header, the theme in
  `localStorage`, and the theme read back in the head before anything is
  drawn, so a dark screen never flashes white.
- **The gate password is known again**: `wx-seasonal-2026`.  It is in the
  encrypted secret store as `SITE_PASSWORD` and `tools/restore_secrets.sh`
  writes `data/.dev_gate_password` from it, and the published fallback
  hash in `build_site.py` is that password's hash, so a wiped tree still
  opens with the same password.

### The owner's second round (17 Nov, 20:50)

- **The password did not work in the owner's browser.**  The reason was a
  **cached login page**: the comparison happens in the browser, so a page
  that still carried the old hash rejected the new password for ever.
  The login page now **fetches the live hash** from `data/gate.json`
  with a timestamp in the query, so the page always asks which password
  is current; the inline hash is only the fallback if the fetch fails.
  The gate's redirect also carries a cache-buster, so a cached page
  cannot loop.  Tested with a deliberately stale login page: it signs in
  with the current password, and a wrong password is still refused.
- **The globe now floats in space**: a deterministic starfield and two
  faint nebula glows are painted under the globe, and the sea is a clear
  step lighter than the sky (`#12395c` against `#02060d`) with an
  atmosphere rim, so the globe never dissolves into the background in
  dark mode.
- **The colour bar is the static panels' bar**: the whole width, the
  ladder's intervals as the segments, and the keys on the same
  boundaries.  It used to be 32 fixed 16-pixel blocks in a full-width
  row, so it stopped half way across and the keys sat on nothing.
- **"Snow depth" is gone from the map's wording**: the caption reads
  "Accumulated snowfall, inches (... ) on the published 0-300 in scale",
  the right-hand end is "300 in", and the hover readout says "in".
- **Five models are on the map now**: NOAA CFSv2, NOAA SFSv1 and three
  C3S centres (ECCC canSIPS, METFR System 9, UKMO GloSeas6-GC5.1).
  The C3S anomaly needs each centre's hindcast climate, which is still
  in the queue.
- **The export test was the one publishing "SYNTHETIC TEST"**: it runs
  the exporter, which writes the model index, and its cleanup restored
  the wrong file.  Both tests now rebuild the index from the manifests
  that are actually there.

## The dev gate: the owner was locked out by their OWN bookmark (17 Nov 2026)
- The corrected copy lives at `massachusettswx-weather.github.io/seasonal-graphics-dev/`.
  The OLD address `matthew22-cmd.github.io/seasonal-graphics-dev/` is STILL LIVE and
  still serves the OLD build with the OLD gate hash (`866da46e...`) - so the new
  password can never work there.  The owner was typing the new password into the
  old page.  **Always ask which URL is on their screen before debugging a password.**
- The login page now: fetches the live hash (`data/gate.json`), ignores case, and
  strips spaces, quotes and backticks; it has a "show the password" tick box and a
  "clear the field" button, because a password manager can silently fill in an old
  password that the reader cannot see.
- To get the corrected build back on the OLD address: add `massachusettswx-weather`
  as a write collaborator on `Matthew22-cmd/seasonal-graphics-dev`, then set
  `GITHUB_DEV_OWNER=Matthew22-cmd` and re-publish.

## The gate is off on the development copy (17 Nov 2026, the owner's call)
- The owner asked to bypass the password.  The development copy is now published
  OPEN: `https://massachusettswx-weather.github.io/seasonal-graphics-dev/` - no
  login, no password, no gate script in the pages.
- The switch is `DEV_NO_GATE=1` (or a file `data/.no_gate`).  It is stored in the
  encrypted secret store as `SITE_NO_GATE=1`, and `tools/restore_secrets.sh` and
  `tools/auto_run.sh` both put it back after a wipe - otherwise the next rebuild
  would put the gate in front of the site again and lock the owner out.
- The publisher's "the build must carry a gate" check follows the switch: with
  the gate off it prints a NOTE instead of refusing to publish.
- The old address `matthew22-cmd.github.io/seasonal-graphics-dev/` is still
  serving the old gated build and cannot be updated from here (pull-only).
- The OPERATIONAL site is untouched: `https://massachusettswx-weather.github.io/
  seasonal-graphics/` (the repo was renamed, so the old `seasonal-snow` path 404s).

## The map is drawn on the GPU (18 Nov 2026)
The map was drawn on the CPU: every pixel asked d3 where it was, and the answer
was cached as a sampling plan.  A drag cost about three seconds, and the owner's
verdict was that the map has to move smoothly.

It is drawn on the GPU now.  `assets/js/mapgl.js` is the renderer (WebGL2);
`assets/js/maps.js` keeps the UI, the loading and the interaction.

- **The projection is a closed form**, checked against d3 before it was used:
  forward 8.9e-12 px, inverse 2.8e-14 deg, over three views x four rotations x
  three zooms.  It is d3's own arithmetic, written out (orthographic, azimuthal
  equidistant, equirectangular).
- **The field is sampled in the shader** with the same four cells, the same
  weights and the same tables the CPU used - the field is the model's own grid,
  never resampled.
- **A drag costs ~1.3 ms of CPU and ~1 ms with the GPU** in the software
  renderer; the real GPU is quicker.
- **The earth is a baked mask** (4096x2048, R = land, G = lakes) instead of a
  land path redrawn every frame; the outlines are GPU lines.
- `tools/test_map_gl.py` checks the projection against d3, the colour at the
  pixel against the CPU arithmetic (with the outlines turned off - they are
  drawn over the field on purpose), and the cost of a frame.

Six things were wrong on the way, and they are worth remembering:
- **A texture fetch comes back normalised (0..1).**  The field's bytes were read
  as if they were already 0..255, so every cell was one and the map showed the
  sea.  Multiply by 255.
- **Padding a texture to a power of two breaks the row stride.**  The data was
  written with the grid's own width and the texture had another, so the field
  was read a row out of step.
- **The vector attribute was bound to the distance buffer** (`makeVAO` took the
  segment buffer and never used it), so every line was drawn between two
  garbage points - one diagonal across the map.
- **The graticule's segments carried five numbers** where the attribute reads
  four, so every segment after the first was garbage.  That was the speckle of
  dots over North America, and it was not the lakes: the lakes were filtered
  and the speckle stayed.
- **The ladder's bottom bucket is "no snow"**, and on a dark map that has to be
  transparent or there is a white fringe round every snow field.  The table has
  to carry that colour EXACTLY, or the browser cannot see it.
- **The drawing buffer has to be kept** (`preserveDrawingBuffer: true`), or the
  browser throws the map away as soon as it has been shown and the map goes
  blank while it is idle.

And two more:
- **The anomalies have a table of their own now**, built with the panels' own
  `BoundaryNorm` over `ANOM_LEVELS`: the colour of a cell is decided by the
  value it stands for, not by where the byte sits in a ramp.  The old ramp was
  a different product from the static panels.
- **Only the big lakes are drawn** (a bounding box of a degree or more).  The
  1:50m file has four hundred of them and the small ones are a speckle of dots
  rather than lakes.  The mask and the outlines use the same set, or the map
  would show them twice.

The atmosphere is a rim OUTSIDE the globe now.  It used to be a veil over the
outer third of the disc, which washed out the field's own colours - and the
field is the map.

## The polar view paints the whole globe, and the states are on the map (18 Nov 2026)

**THE POLAR VIEW WAS NOT A PROJECTION PROBLEM - THE FIELD WAS CUT OFF.**
The polar view is an azimuthal equidistant projection centred on the north
pole, so the whole globe fits inside the disc: the equator is at r = k*pi/2
and the south pole is at r = k*pi.  The shader had

    bool fieldOK = !(u_view == 2 && r > u_k * PI * 0.5);

which painted the field only over the northern hemisphere, while the land
mask and the coastlines kept drawing the southern hemisphere.  That is the
owner's screenshot: a snow blob at the pole and a big empty navy ring
below.  The restriction is gone; the field follows the earth over the whole
disc, and the graticule reaches the far side of the world with it (the
meridians stop at 85 degrees south, because the pole itself is the
antipode of the centre and is the one point this projection cannot draw).

**THE PROOF.**  The renderer's own inverse (`pick()`) against the analytic
`lat = 90 - degrees(r/k)` agrees to **0.000000 degrees** at 14 radii from
the centre to the rim.  An A/B on the same page, counting pixels:

| view | before the fix | after |
|---|---|---|
| polar / totals | 193 land, 459 ocean | 62 land, 318 ocean |

131 ocean pixels became land pixels: the southern hemisphere's land now
shows.  The land count FALLS because the field now covers what used to be
bare earth.

**THE ANTARCTIC RING IS REAL.**  Antarctica's snowfall (30-50 in) is in the
model's own output; the far hemisphere is compressed into the outer annulus
of this projection, so it reads as a bright ring.  It is geographically
correct, not a rendering fault.

**`tools/test_maps_page.py` REPORTING "0 of them land" IS NOT A REGRESSION.**
The test builds a SYNTHETIC model whose field covers the whole world, so
after the fix there is no bare land left to count.  A real model still
shows 62 land pixels in the polar view.

**THE STATES ARE ON THE MAP.**  `tools/make_states_geojson.py` trims
`data/ne_50m_admin_1_states_provinces.geojson` to the site's own
geographic scope (the United States and Canada, the set the static panels
draw): 64 features, 25,288 points, 775 kB.  They are drawn as their own
layer in a thinner and dimmer steel than the national outline, so the
outline stays on top, and the antimeridian split is applied to them too.

**THE DRAG DOES LESS WORK.**
- the hover hit test is indexed by the bounding box of each ring: **2.76 ms
  -> 0.05 ms**, and it runs on every mousemove;
- the coastlines, the lakes and the graticule are uploaded ONCE instead of
  every frame (the coastline's zero buffer was 442 kB a frame);
- the page is not laid out again for a box width that has not changed (a
  ResizeObserver watches the box instead), and the zoom label is only
  written when the zoom changes.
Measured after: **1.08 ms of CPU a frame, 0.85 ms with the GPU** (the test
had said 2.49 ms before this round of work).

**THE QUEUE WAS SPINNING.**  `decode_daily()` returned a bare `False` for
a short chunk, but the caller unpacked two values out of it, so every short
chunk raised "cannot unpack non-iterable bool object", the short chunk was
never counted, the give-up-after-three rule never fired, and the pool
re-submitted the same impossible UKMO request for hours.  A function that
returns a tuple on one path must return a tuple on every path.  The UKMO's
sub-daily 10 hPa wind is now correctly given up on (`shorts: 3,
given_up: True`) and its 60-member monthly wind serves the chart.

**THE WATERMARK** is on the map, bottom right, in the house style
(`@Massachusettswx`, bold), matching the static panels.

## The polar view is gone, and the map moves less (18 Nov 2026)

**THE OWNER'S DECISION: THE POLAR VIEW IS REMOVED.**  The investigation
below had shown the projection was exact (0.000000 degrees), the field was
right, and the bright Antarctic ring was real data squeezed into the outer
annulus - but the whole-globe polar projection was not useful enough to
keep.  Two views remain: **2D Map** and **3D Globe**.

What was taken out, in both the CPU path (`assets/js/maps.js`) and the GPU
path (`assets/js/mapgl.js`):
- the Polar button in `#mapviews` (built by `build_site.py`);
- `state.prot`, the azimuthal-equidistant branch of `baseProjection()`,
  the polar branch of `projParams()` and of `mapHeight()`;
- `graticulePolar()` and its export;
- the polar arm of the vector shader's `forward()` and the `u_view == 2`
  arms of the earth shader's `invert()` and of `Renderer.pick()`.
The GLSL now knows only `u_view 0 = flat` and `u_view 1 = globe`.

**THE DRAG SENSITIVITY IS NOW A NAMED CONSTANT.**

    var DRAG_GAIN = {flat: 0.75, globe: 0.30};

- the flat map pans at `dx * DRAG_GAIN.flat` (was 1:1);
- the globe spins at `DRAG_GAIN.globe / state.zoom`, so **the spin is
  divided by the zoom**: the map moves the same distance ON THE SCREEN at
  every magnification.  Before, the same drag threw the globe about nine
  times further at 600% than it did at 100%, which is what made dragging a
  zoomed-in globe feel wild.
- the zoom step came down from 1.15 to **1.12**, for the wheel and for the
  buttons both.

**MEASURED ON THE BUILT PAGE** (200 px of pointer travel):

| | before | after |
|---|---|---|
| flat map, the pan | 200 px (1.00 of the pointer) | **150 px (0.75)** |
| globe at 100%, the turn | 90 deg | **60 deg** |
| globe at 197%, the turn | 90 deg | **30.4 deg** |
| globe at 605%, the turn | 90 deg | **9.9 deg** |

The turn at 605% is 0.165 of the turn at 100% - exactly 1/zoom - so the
movement on the screen is the same at every size.

**THE RENDERER NOW RECORDS A LOST CONTEXT IN AN EVENT.**  `mapgl.js`
listens for `webglcontextlost` / `webglcontextrestored` and keeps the
flag on `renderer.contextLost`.  Nothing has to call into the GPU to ask
whether the context is alive - and that call was what used to hang the
test suite under SwiftShader (the test now reads the flag, and asks for
it BEFORE the drag, because the drag leaves the software renderer with a
lot of queued work).

**THE TESTS, ALL GREEN:** `tools/test_map_gl.py` (projection 1.14e-12 px
forward / 2.84e-14 deg inverse against d3; 272 colours checked, 2 off;
the anomaly's own palette; the context alive; the drag 1.02 ms of CPU and
0.87 ms with the GPU; no console errors - "all good"),
`tools/test_maps_page.py` (the two view buttons, the timeline, the zoom
and its reset, no polar-section furniture, no console errors) and
`tools/test_export_map.py` ("all the checks passed").

**PUBLISHED TO THE DEV SITE ONLY** (commit `3fc5b08`): the live page has
exactly two views, no gate, the watermark, and the drag numbers above.
The operational site was NOT touched.

## The queue could not fetch a centre it had already fetched once (18 Nov 2026)

**THE STEP LISTS HAD BEEN NARROWED TO WHAT WAS MISSING AT THE TIME.**
`run_nov_queue.py`'s `monthly_steps()` was cut down to the two ECCC
centres in November (they were the only ones missing then) and
`clim_steps()` was emptied.  **That is wrong for a disposable tree:** a
list of "what was missing" becomes a list of "what can never come
back".  A sandbox rebuild wipes `data/models` and the folders with it,
and a centre that is not on the list is never fetched again, however
the site is left.

The proof was in the state file: the ECMWF's own monthly snowfall was
gone from disk while `data/models_fetched.json` still said
`done: True`, so the map could not carry the ECMWF at all and no
request would ever have brought it back.

Both lists are now derived from **`SNOW_CENTRES`**, the centres that
publish a snowfall field:

    SNOW_CENTRES = ("ecmwf-seas5", "ukmo-gloseas6", "meteo-france-s9",
                    "cmcc-sps4", "dwd-gcfs2", "eccc-gem5", "eccc-canesm5")

JMA and BoM are not on it: they publish no snowfall at all, and MARS
answers `MarsNoDataError` for it, so a request for their snowfall can
never succeed.  **The list and the skip check are separate things:**
the list is the whole set of centres that can serve the request, and
the pool's "already on disk for the newest init" check is what makes a
full list cost nothing when the data is there.  Do not narrow the list
to work around a full queue.

**THE EXTENSION HAD NO SKIP CHECK AT ALL.**  The pool had one for the
monthly snowfall, the SST, the monthly wind and the hindcast climate,
but not for the extension past the sixth lead month - so once the
ECMWF's extension had been written, the next pass asked for it again.
It had been submitted **46 times**, each one a real 231 MB request that
the archive had to serve.  It now carries the same check.

**THE META IN AN NPZ IS A JSON STRING, NOT A DICT.**  `save_npz()`
stores it as `np.array(json.dumps(meta or {}))`, so `d["meta"].item()`
gives `"{...}"` and `.get("init")` raises.  The first version of the
reader answered `None` - which would have looked like the fix working
while the loop went on.  The reader does `json.loads(str(...))`.

**THE EXTENSION'S INIT IS IN THE DECODED FILE, NOT THE GRIB.**  The
extension's own dates are months past the init, so they do not say
which init it came from; `decode_ext()` writes the init into the npz's
meta, and that is what says.  A GRIB with no npz beside it answers
`None`, and `None` never matches - so a file that was downloaded but
not decoded is asked for again.

**THE POSTS-OFF SWITCH NOW SURVIVES A WIPE.**  The publisher was held
off by `NO_PUBLISH`, an environment variable - which a sandbox rebuild
takes with it, so the next rebuild would have started publishing again.
It is a file now, **`data/.no_publish`**, written by
`tools/restore_secrets.sh` from a new `SITE_NO_PUBLISH` secret, the
same way the gate switch works.  `tools/auto_run.sh` honours either.
Verified: `auto_publish.sh NOT RUNNING`, `run_nov_queue.py 1 process`,
`fetch_polar_models.py 1 process`.

## The map carries the models over instead of queueing them (18 Nov 2026)

**THE OWNER ASKED WHY THE MAP NEEDED MORE MODELS WHEN THE STATIC PAGES
ALREADY HAD THEM.**  The answer was two bugs and one piece of data that
was already in the repository.

**THE INDEX DROPPED THE MODELS.**  `write_index()` wrote the picker
from THIS run's summary alone, so every rebuild dropped every model
whose GRIB was not on disk - even though its rasters and manifest were
committed and sitting in `docs/data/`.  That is how the ECMWF's export
was lost (commit `c2751cf` deleted it) and why the map kept needing
the queue.  The index now keeps every model whose export is on disk
with its rasters beside it, and the "is it there?" check is separate
from the list - the same rule the queue learned the same day.

**THE ECMWF'S FIELD WAS ALREADY IN THE REPOSITORY.**  The SEAS5 fetch
wrote `data/seas5_<init>_snow_em.npz` (the ensemble mean, six lead
months, the model's own 1 degree grid) and `_snow_hc.npz` (the model's
own hindcast climate), and BOTH ARE COMMITTED TO GIT.  `tools/
carry_over_seas5.py` writes them into `data/models/ecmwf-seas5/` in the
convention the exporter and the panel renderer already read, so both
products are built from them - no queue, no request, no waiting.  It
runs in `auto_publish.sh` and in `tools/bootstrap.sh`, so it survives a
wipe.

**THE FIELD IS THE SAME FIELD.**  Compared cell by cell against the
committed source the largest difference anywhere is **0.000e+00 in**.
The static panel re-rendered from the carried-over data differs from
the published one in **187 of 2,167,620 pixels** - isolated single
pixels on a contour edge, where the two code paths pick a neighbouring
bin of the same contour.

**THE QUEUE NOW SKIPS A CARRIED-OVER CENTRE.**  Its skip check looked
only for the GRIB, so it would have asked the archive for the ECMWF's
monthly snowfall again.  The check now recognises the carried-over npz,
and only counts it when it belongs to the centre's OWN init (the init
is in the npz's meta).  So the queue's slots go where they are needed:
it moved on to the CMCC, which has nothing at all.

**THE EXTENSION WAS DECODED ON A CONUS CROP.**  The extension past the
sixth lead month is FETCHED globally but was decoded on the
20-56N / 134-56W box the panels use, so the map got a 36x78 fragment
it could not interpolate onto its own grid.  `read_snow()` takes
`crop=False` for the global case, and `interp_to()` now accepts a pair
of target AXES as well as a pair of points.

## The map's run total showed an empty field with a diagonal line (18 Nov 2026)

Found by looking at the ECMWF's anomaly on the live map.  Four bugs, all
in `export_snow_map.py`:

1. **THE RUN TOTAL'S ANOMALY WAS NaN EVERYWHERE.**  The run total is
   the sum of the monthly anomalies, and a month with no hindcast
   climate contributes NaN - and `np.sum()` of a NaN is NaN.  The whole
   run total came out masked and the map's "Total" button showed an
   empty field with a diagonal line.  The sum now skips the months that
   have no climate.
2. **THE RUN TOTAL'S MASK WAS NEVER APPLIED.**  The monthly rasters are
   masked where the model's own climate expects no snow; the run
   total's was not, so it showed an anomaly where there is no snow at
   all.
3. **THE MULTI-MODEL'S MEAN CLIMATE WAS DILUTED.**  The mean is taken
   over the members that HAVE a climate.  A member without one
   contributes zeros, and zeros say "the model expects no snow here",
   so including them washed the mean climate down and nothing was
   masked at all.
4. **THE MULTI-MODEL ASSUMED EVERY MEMBER REACHES AS FAR.**  The ECMWF
   carries on past the sixth lead month with its extension, so it has
   seven months where the others have six, and the mean ran off the end
   of the other members' lists.  The mean is now taken over the months
   EVERY member has.

And the manifest's per-lead `ym` was the LAST lead month's key in every
entry, because the loop used the outer loop's variable - so the
multi-model's month labels came out as null.  Both are fixed.

**THE MAP NOW CARRIES NINE MODELS**: the C3S Multi-Model Mean, the
CFSv2, the CMCC, the DWD, the ECCC canSIPS, the ECMWF SEAS5, the
Météo-France System 9, the SFSv1 and the UKMO GloSeas6.

## The map opens on the multi-model, and the globe stopped lying (18 Nov 2026)

**THE PAGE OPENS ON THE C3S MULTI-MODEL MEAN** (the owner's request).
The picker is ordered - the mean first, the rest by name - so the list
does not reshuffle itself between rebuilds, and the page asks for the
mean BY NAME (`"c3s-multi"`), not by position: a stale index on disk
cannot make it land on something else.  The first entry is only the
fallback.  The mean now has its own hindcast climate (the ECCC's arrived
and `build_cansips.py` was re-run), so its anomaly is real and 43.9 % of
the run total is masked where the climate expects no snow.

**THE GLOBE'S INVERSE WAS WRONG BY UP TO 0.53 PIXELS.**  The map's GPU
and its own CPU arithmetic disagreed on a few pixels of the globe - and
never on the flat map, which uses no transcendentals at all.  The cause
was measured, not guessed:

| function | worst error (SwiftShader) |
|---|---|
| `asin` | 1.6e-8 |
| `atan2` | 1.1e-7 |
| **`sin` / `cos`** | **1.9e-4** |

The shader's inverse went through `sin(asin(z))` and `cos(asin(z))` and
then took the sine and cosine of the two angles it had recovered.  The
error walked straight into the place the snow is sampled: up to 0.53 px,
enough to flip a pixel's byte across a colour boundary.

But `sin(asin(z))` IS `z`, and `cos(asin(z))` IS `sqrt(1 - z*z)`, and
the point on the sphere is the two screen axes and the depth:

    P = px * east + py * north + sqrt(1 - px^2 - py^2) * up

so the inverse now says that outright: three fewer transcendentals, two
left, and no dependence on how well `sin()` and `cos()` are implemented.
The two forms agree to **1.9e-13 rad**, and the shader still matches d3
to **3.7e-13 deg**.  The anomaly palette now reads back **334 pixels
with 0 of them wrong** (it was 4), and the totals 321 with 0 bad (it was
1).

**THE MEASUREMENT TRAP**: packing a float into four bytes with the
usual `fract(v * (1, 255, 65025, 16581375))` trick carries a noise
floor of about 2.4e-4 - the same size as the error being hunted.  The
probe now packs the float's **bits** (`floatBitsToUint`), which is
exact.  (`probes/glsl_test.html`, `probes/glsl_acc.py`.)

## The sea is left as sea (18 Nov 2026)

**THE WORLD MAP SHOWED 48 INCHES OF SNOW ON THE NORTH ATLANTIC.**  The
models' "snowfall" over the sea is the precipitation they classified as
snow over the water, and the house's 10:1 water-equivalent-to-depth
ratio turns it into nonsense: the SEAS5 puts 48 inches on the Atlantic
for the run and 144 for the six months, against 57 inches over northern
Canada.  Every model does it.  The anomaly over the sea came out at
-20 inches - the extreme of the palette - so the sea was a sheet of
saturated brown and the continents were washed out.

The static panels never showed it: they are cut to the eastern United
States, and their own mask (the model's climate expects no snow) covers
the water inside that box.  A map of the whole world does show it.

So the map paints the field **on the land** and leaves the sea as sea:

- the renderer asks its own land mask - the same Natural Earth 1:50m the
  earth is baked from - before it paints a cell, so the coastline is as
  fine as the map's coastline and not as coarse as the 1 degree grid;
- the exporter's anomaly scale is worked out over the land, so the sea's
  meaningless numbers cannot swallow the colour range;
- the test asks the same mask before it compares a colour.

`Renderer.landAt(lon, lat)` is the new question the renderer can answer.

**A NOTE FOR THE OWNER**: this is the one change on the dev site that
was not explicitly asked for.  It is on the dev copy, it is one flag in
the shader (`mk.r > 0.5 && mk.g < 0.5`), and it can be taken back in a
minute if the sea is wanted back.

## The monthly map was the same picture every month (18 Nov 2026)

**THE OWNER'S SCREENSHOT (543 %, anomaly on, December 2026) SHOWED A
PLAIN THAT WAS THE SAME IN EVERY MONTH.**  The cause was a variable
shadowed by an inner comprehension, in the multi-model block of
`export_snow_map.py`:

    monthly = [np.mean([exported[t]["monthly_in"][k]
                        for t, k in zip(MULTI_MEMBERS, idx[t])], axis=0)
               for k in range(len(common))]

The inner `for t, k in zip(...)` binds **its own `k`**, so every month
of the mean was the same blend - November's ECMWF, December's UKMO,
January's METFR and so on.  `idx[t]` also resolved the *enclosing* `t`,
which by then was the last model exported.  All six monthly totals and
all six monthly anomalies came out byte-identical, and the run total was
six times that one picture.  The member's own index for THIS month is
`idx[t][k]`, and nothing else.

The single models were never affected - their months were always
different - which is why only the mean was wrong.  After the fix every
month's raster has its own hash (checked live: four of four differ).

**THE LESSON**: a loop variable shadowed by an inner comprehension is a
silent data bug, and it hides in the ONE place that aggregates many
things.

## The earth turns (18 Nov 2026)

The owner asked to "turn/rotate earth".  The globe could already spin
and the flat map could only pan, so the turn button beside the zoom
buttons (`data-z="turn"`) switches the drag:

- **the flat map**: the map is turned on the screen and the data is not
  - the shader samples the field through `R(-theta)` about the view
  centre;
- **the globe**: the axis tips over - a rotation of the frame about the
  east axis, so the north pole leans toward the viewer - and the
  horizontal drag still spins it.

`u_turn` and `u_tilt` are uniforms on both shaders; the CPU's
`projectPoint`/`invertPoint` mirror them so the tooltip and the hit
test stay right.  A tilted globe cannot be checked against d3 (d3's
`geoOrthographic().rotate()` cannot express a tilt), so it is checked
by the round trip and by the sea/land split: the same point is sea
before and after the tilt.

Two bugs were found in that new code:

- `import warnings` INSIDE the multi-model block made `warnings`
  function-local for the WHOLE function, so the per-model block raised
  `UnboundLocalError`.  A module import inside a function shadows the
  module-level name for every path in it.
- the CPU's tilted `up` vector had its components swapped (`ux/uy/uz`),
  which showed as "inverse 179 deg".  Correct:
  `ux = (sp0*cl0)*stl + (cp0*cl0)*ctl`, `uy = (sp0*sl0)*stl +
  (cp0*sl0)*ctl`, `uz = -cp0*stl + sp0*ctl`.  After it: forward
  1.14e-12 px, inverse 3.69e-13 deg.

## The three-month window is the house's own (18 Nov 2026)

The house already publishes it.  `plot_snow_ref.py` is the authority:

    windows = [(0, 1, 2, "NDJ", "Nov 2026 - Jan 2027"),
               (1, 2, 3, "DJF", "Dec 2026 - Feb 2027"),
               (2, 3, 4, "JFM", "Jan 2027 - Mar 2027"),
               (3, 4, 5, "FMA", "Feb 2027 - Apr 2027")]
    items.append(dict(field=anom[[i0, i1, i2]].mean(axis=0), ...))

So a window **STARTS** at its month (November's is Nov-Dec-Jan), it is
named by the three months' own letters, and the anomaly in it is the
**MEAN of the three months' anomalies** - the panels say "in w.e.
3-month mean", because an anomaly summed over three months is
unreadable.  The map's windows had been CENTRED on their month, which
would have put different months under the label than the house's panel
of the same name.  They now start at their month, the label is the
house's code, a run carries the house's FOUR windows and no more, and
the months without one (and the run total) are dimmed on the timeline
with the reason on their tooltip.

The caption names the window ("NDJ, 3-month total") and now FOLLOWS the
month: picking a month redraws the legend, which it did not, so the
caption kept the last window's name.

**WHAT TO CONFIRM WITH THE OWNER**: totals = the window's accumulation
on the published ladder; anomaly = the window's mean per month.  That
is the house's own convention and it is what is on the dev site.

## The ECCC canSIPS pool carries the seventh month (18 Nov 2026)

The lead month past the sixth arrived for both of the ECCC's systems,
but the pool had not been rebuilt since, so the pooled model was still
six months while the ECMWF and the UKMO carried seven.  `build_cansips.py`
already knew how to merge the extensions; the pool simply had not been
re-run.  It has, and the map's ECCC entry now has seven months.

The extension's `ndays` (31 for May) is the number of days of
accumulation, not the number of members - the exporter's "at least 20
days" rule is a completeness test, not a member count.

## The polar cap page had no daily pull, and the December gate was blind (20 Nov 2026)

**THE OWNER'S NOTE: "GEFSv12 guidance hasn't updated on the polar cap page
which is concerning for future seasonal models coming in in December on
time/automatically."**  It was worse than a stale panel.  Two separate
faults, both of which would have hit the December rollover.

**1. THE GEFSv12 WAS NEVER WIRED TO ANYTHING.**  `fetch_polar_gefs.py`
exists and works - it finds the newest cycle that carries the whole
extended range, downloads the 35 daily leads for the members that carry
all of them, and writes the series into the shared cache.  But **no
script called it**.  The panel could only be refreshed by hand, which is
why it sat on the 14 Nov run while the 19 Nov run was there to be had.
The CORe reanalysis half (`fetch_polar_core.py`) was the same.

`tools/daily_refresh.sh` now pulls all of it - the observed SST, the NOAA
models, the GEFS and the CORe - and it is all from public sources, no key
and no queue.  Both the publisher and the keepalive call it, so the data
keeps moving even when the publisher is stopped.  The GEFS's decoded
series is tracked in git as well: an hour of downloading to rebuild, and
a sandbox rebuild takes `data/` with it.

**2. THE MIXED-INIT GATE WAS WATCHING ONE CENTRE.**  The December risk
is a split: the ECMWF publishes on the 6th and the other centres on the
10th, so for four days the site would show two months at once.  The
audit's gate exists to stop that - and it read its list of centres from
`data/multi_members.json`, which the multi-model's renderer writes from
**"the systems that happened to have data when this ran"**.  After a
rebuild, when only the ECCC was on disk, that file listed ONE member and
the model's card said "Mean of 1 seasonal systems (ECCC canSIPS)".

So the gate was watching the ECCC alone and would have let a mixed
December through.  The membership is now a constant
(`init_info.MULTI_MODEL` - the six systems, the ECCC counted once as the
pooled canSIPS); the audit reads it, the exporter reads it, and the
renderer still records what actually went into the graphic, which is the
honest count for the card and the title.

`test_december_transition.py` now passes completely, including the check
that the refusal says WHY it refused.

**3. THE ORDER OF THE BUILD MATTERS.**  `build_registry.py` copies the
drawn charts into `docs/assets/polar/`, so it has to run AFTER
`build_polar_charts.py`.  The publisher's chain does that; a manual run
that does it the other way round publishes the previous chart (which is
exactly what happened the first time here).

**WHAT IS STILL NOT AUTOMATIC, and what the owner has to decide**: the
December *fetch* is automatic (the queue follows the C3S release
calendar), but the *render* and the *publish* live inside the publisher,
which is stopped, and the keepalive cron - the thing that restarts the
workers after the sandbox rebuilds - is parked with it.  The workers were
found dead this morning for exactly that reason.
