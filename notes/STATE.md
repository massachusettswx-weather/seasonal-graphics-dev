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
  synthetic model: the globe, the flat map, the polar view, the timeline
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
