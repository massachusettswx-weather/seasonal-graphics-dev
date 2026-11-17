# The state of the project

**This file is the handoff.** It is tracked in git on purpose: when the
sandbox is wiped, the working tree goes with it, but this file comes back
with the repository. Read it first, and update it before you end a session.

Last updated: **17 Nov 2026, 19:05 UTC** (after the sandbox wipe of 16-17 Nov,
after the global map rebuild, and after the auto-run was wired)

## The two sites

| | repository | address |
|---|---|---|
| **dev** | `Matthew22-cmd/seasonal-graphics-dev` | <https://matthew22-cmd.github.io/seasonal-graphics-dev/> |
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
  north-polar disc), with the polar cap section's two sectors marked

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
  the three views (flat / globe / polar).  The globe can be dragged and
  scrolled to zoom.

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
