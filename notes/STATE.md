# The state of the project - 24 Nov 2026, 06:20 UTC

Short and factual.  The long history of how it got here is in
`notes/STATE_LOG.md`; the rules that are not negotiable are in
`notes/PROTECTION.md` (the data) and `notes/PUBLISHING.md` (the two
sites).  This file is the handoff: a new session reads this and does not
need the conversation.

## The two sites

| | repository | address | state |
|---|---|---|---|
| **operational** | `massachusettswx-weather/seasonal-graphics` | `https://massachusettswx-weather.github.io/seasonal-graphics/` | the GEFSv12 sub-seasonal panel is published **nightly**; the rest of the site is curated |
| **development** | `massachusettswx-weather/seasonal-graphics-dev` | `https://massachusettswx-weather.github.io/seasonal-graphics-dev/` | everything: the panels, the pages, the polar cap section, the interactive world map (`maps.html`) - open, no password |

* The development copy is the working copy: everything new is built and
  shown there first.  **The owner works on the development copy** - the
  operational site has no map page at all.
* The operational site is **curated**.  Nothing reaches it without the
  owner's word; the one exception is the daily GEFSv12 sub-seasonal
  update, which was approved for it.
* The general publisher is **OFF**: `SITE_NO_PUBLISH=1` in the encrypted
  secret store.  `tools/auto_run.sh` honours the switch.  **Stopping the
  posts must never stop the workers** - the cron is what puts the workers
  back after each sandbox rebuild.

## What is published where

* **The development copy carries everything**: the seasonal panels, the
  ENSO and SPV pages, the polar cap section, and the interactive world
  map (`maps.html`) - one big map, flat and globe, on every model's own
  grid, with the anomalies against each model's own hindcast climate, the
  three-month windows (NDJ, DJF, JFM, FMA) and the `@Massachusettswx`
  watermark.
* **The polar-cap section opens on the NOAA GEFSv12** (the owner's choice,
  22 Nov 2026) on both sites - it is the sub-seasonal panel, the one that
  changes every day.  The 10 hPa wind picker on the same page is a
  different product and still opens on the ECMWF SEAS5 (the GEFSv12 has no
  wind panel).
* The GEFSv12 sub-seasonal series is at the **20261123 00Z** cycle (35
  days, 31 members, 12 levels) on **both** sites (24 Nov 2026).
* **The EC46 polar-cap section is on BOTH sites** (the owner's approval,
  22 Nov 2026): the **20261120 00Z** run, 45 days, 101 members, published
  with `tools/publish_polar_ec46.py`.
* **The dark mode is on the operational site** (the owner's approval,
  22 Nov 2026): every page carries the button, the theme is read back
  before anything is drawn, and the browser remembers it.  Published with
  `tools/publish_dark_mode.py`.

## The workers

* They run in `/workspace/devrepo`: the CDS request pool and the polar
  puller.  The sandbox is rebuilt every hour, which kills them.
* **There is ONE scheduled task** (22 Nov 2026), `seasonal-gefs-subs`
  (`465527736623226`), at **03:00 UTC** every night.  It is a WATCHER: it
  keeps checking until the newest COMPLETE 00Z cycle has been fetched and
  published, and then it **stops** - the next night is the next run.  The
  00Z cycle is only COMPLETE about 24 hours after its init - NCEP uploads
  the members in four batches, the last one at ~00:40 UTC the next day -
  so the cycle for a given day appears at an uncertain hour, and the
  watcher's test is the cycle's own date, never the clock.  It
  runs in its own throwaway conversation, and it does ONE thing:
  `tools/gefs_subs_disseminate.sh`.
* **The 20-minute keepalive is GONE** (deleted 22 Nov 2026 at the owner's
  instruction).  It was the thing that flooded the chat and it published
  nothing; the daily task replaces it.
* **The general publisher stays OFF** (`SITE_NO_PUBLISH=1`).  The only
  thing that goes out is the GEFSv12 sub-seasonal panel, and only through
  the narrow path.
* The daily pull for the other products is `tools/daily_refresh.sh` (OISST,
  NOAA ENSO, CFSv2 in the foreground; SFS and CORe detached).

## The December rollover

* The C3S centres publish on the **10th**; the ECMWF publishes on the
  **6th**.  For four days the site would show two months at once.
* The gate that refuses it lives in `audit_inits.c3s_centres()` and
  watches **`init_info.MULTI_MODEL`** - a constant (six systems, the ECCC
  counted once as the pooled canSIPS).  It must never read a file written
  from "whatever was on disk": that file listed ONE centre after a rebuild
  and the gate went blind.
* `tools/recover_jobs.py --no-request` downloads what is already
  requested and never re-submits; re-submission belongs to
  `run_nov_queue.py`.
* Still in the queue: `ext:jma-jra3` and `ext:bom-access-s2`.

## The narrow path to the operational site (20-22 Nov 2026)

The owner's request: *"Stop the scheduled updates.. we need to extend the
daily GEFSv12 SUBS update to the live site as well"*, and on 22 Nov: *"fix
the dissemination of 00z GEFSv12 SUBS to update daily after the latest
model run finishes"*.

**`tools/publish_polar_subseasonal.py`** is the narrow path.  It carries
**one product, two pictures, one registry entry** and never rebuilds the
site:

```
python3 tools/publish_polar_subseasonal.py --repo /workspace/repo
    plan only: what would change, nothing is written
python3 tools/publish_polar_subseasonal.py --repo /workspace/repo --apply
    the seven files are written into the target's working tree
python3 tools/publish_polar_subseasonal.py --repo /workspace/repo \
    --apply --push --prod --approved
    ... and it is committed and pushed to the operational repository
```

* It touches **seven files** and nothing else: the two GEFSv12 charts,
  `docs/data/models.json`, `docs/data/models_public.json`, and the
  registry inlined in `docs/model.html`, `docs/snow.html`, `docs/spv.html`.
* It selects them by a **constant** (`MODEL_ID = "gefsv12"`), never from
  a file a previous run wrote.
* **THE PAGES ARE PATCHED IN THEIR OWN INLINED REGISTRY** (22 Nov 2026).
  The blob in a page was written when the page was built, and a fresh
  clone does not hold the build artifacts that were there then (the
  April-2027 anomaly maps of five centres are never committed), so the
  tree's own registry can never match it.  The script reads the blob out
  of the page and writes back the ONE entry this product owns.
* **THERE ARE THREE BLOBS, NOT ONE** (22 Nov 2026): `MODELS`, and - on
  the stratosphere page - `POLARMODELS` (the cap chart) and
  `POLARSECTORS` (the by-sector chart).  The chart URL's `?v=` is the
  cache-buster, and it lives in all three: patch only the first and the
  browser keeps serving the OLD picture, which is exactly what the owner
  reported as "I don't see the latest runs".
* `--default-only` sets the polar-cap section's default on its own,
  **without redrawing a chart** (the charts on the target are already the
  newest cycle's, and redrawing them here would replace them with a copy
  drawn from this machine's own reanalysis file).
* **Nothing is published when the update is missing** (exit 2) - and a
  series that is still being downloaded (fewer than 35 days) counts as
  missing: a half season is not a season.
* **The push fails loudly** (exit 3) if the repository cannot be reached:
  the commit stays local and the site keeps the old cycle.
* The operational destination needs `--prod --approved`; without them the
  script refuses to push, whatever the remote says.
* It stages **only its own seven files**, so the development copy's busy
  working tree is never carried into a commit, and the token never goes
  on a command line (it lives in a credential file for the push only).
* It finishes a change that was written but never committed (a run that
  was interrupted between the write and the commit leaves exactly that),
  and it gives the git identity on the command line, because a clone that
  has never committed has none.

**`tools/gefs_subs_disseminate.sh`** is the job that runs it, once a
night: it puts the pipeline back (it clones the tree if a rebuild took
it), pulls the day's data, and then **watches** - fetching the newest
complete 00Z cycle in the foreground (so "the run has finished" is an
answer and not a hope), committing the fetch state (it is in git, so a
rebuild does not download an hour again), and publishing to the
development copy and to the operational site.  **The trigger is the RUN,
not a clock**, and the watcher stops as soon as the cycle is on the site
(`WATCH_HOURS`, 12 by default, is the backstop for a night when NCEP is
late).  The narrow path's exit codes are what the watcher reads: 0
published, 4 already current, 2 nothing to publish, 3 the push failed.

### Two more narrow paths (22 Nov 2026, the owner's approval)

The owner: *"push this and dark mode to the ops site"* - and **ONLY** those
two things.  So there are two more narrow paths, each carrying one product
and nothing else:

**`tools/publish_polar_ec46.py`** carries the **EC46 polar-cap section**:
the picture, the registry entry (`docs/data/models.json`,
`docs/data/models_public.json`), the registry inlined in `docs/model.html`
and `docs/spv.html`, the polar block's own registry and the picker's new
option in `docs/spv.html`, and the model's card in `docs/index.html`.
* The entry is **taken from the source tree's own built registry**, so the
  wording is the builder's wording.
* The picture is **copied byte for byte** from the source tree's build, not
  redrawn: redrawing would replace it with a chart made from this machine's
  reanalysis file, which is a day older.
* **Only `model.html` and `spv.html` carry the inlined registry** - the
  operational site's snowfall page reads it out of `models.json`, and its
  home page carries the cards baked in.
* The EC46 has **no by-sector chart**, so `POLARSECTORS` is not touched.

**`tools/publish_dark_mode.py`** carries the **dark mode**: the theme's
rules in `docs/assets/css/style.css`, and on all five pages the script that
reads the theme back before anything is drawn, the button in the header, and
the script that runs it.  All three pieces are **taken from the source
tree's own build**, and the stylesheet's `?v=` is bumped on every page -
without that the browser would keep serving the old stylesheet and the dark
theme would never arrive.

**BOTH SHARE THE GEFSv12 SCRIPT'S MACHINERY BY IMPORTING IT**
(`git`, `push_to`, `commit_files`, `inline_registry`, ...).  The GEFSv12
script runs nightly and must never be edited; importing it is not editing
it.  Every new path is proved on a **copy** of the operational clone
before it is allowed near the live site.

* **THE TRAP THAT COST THE MOST**: a regex patch that replaced the group
  and then jumped to the end of the NEXT group dropped the `</select>` -
  which swallowed the rest of the page and left the picker dead.  The
  page's own JavaScript then failed on a null element.  **A page patch
  that is not opened in a browser is not a page patch.**

## The EC46 (the ECMWF's 46-day extended range) - 22 Nov 2026

* **The fetcher existed and nothing called it.**  `fetch_polar_ec46.py` is
  written and works, but no script ever ran it, so the section was never
  published ("no series for ec46 yet").  It is now wired into
  `tools/daily_refresh.sh`.
* **The request must NOT carry `system: 46`.**  The store answers 201 and
  then the job FAILS; the same request without the field succeeds.  The
  46-day system is picked by the RUN DATE.
* **The runs are DAILY, and the archive holds one about two days late.**
  The old note ("only the Monday and Thursday 00Z cycles carry the 46
  days") was **wrong** - it came from probes that carried the `system`
  field, so every probe failed and the failures were read as "this run has
  no 46 days".  Measured 22 Nov 2026: every run from 10 to 21 November
  served the 46-day window; the 20 November run served the whole window
  with the full member set while the 21 and 22 November runs did not.
* **The run probe must ask for what the chart needs**: a control-only,
  one-level probe was answered "successful" for a run whose full request
  (control AND perturbed) failed every time.
* **The owner's schedule: Monday, Thursday and Saturday** (`EC46_DAYS`),
  with a run that is already on disk left alone.  The reason is the queue,
  not the product.
* **The state must say which run a chunk came from** - it used to record
  the chunk and nothing else, so the next run found every chunk "already
  decoded" and fetched nothing while the chart kept a stale cycle.
* One chunk at a time.
* **A NEW RUN REPLACES THE SERIES; it does not join it.**  The record was
  appended to whatever was there, so the run after the run after this one
  left **90 days** in the file - the old run's days and the new one's,
  indistinguishable.  A run whose date differs starts a fresh record.
* **The card's INIT is the run's own date**, not the first valid time: the
  EC46's first plotted point is a day after its run and the card used to
  say the day after the run (`init_of_run()` in `build_registry.py`).
* **The seam between the reanalysis and the forecast.**  At 10 hPa over the
  polar cap, 20 Nov 2026: the CORe reanalysis (the day's mean, ending at
  21 Nov 00Z) **292,646.1** = **+1.28 sigma**; the EC46's first point
  (21 Nov 00Z, a 24-hour forecast) **292,692.2** = **+1.31 sigma**; the
  difference **46.2 m2/s2 = 0.03 sigma** - the same colour band, so they
  look identical.  They agree because at the seam they are **the same
  instant** (the reanalysis's last daily mean ends where the forecast's
  first point begins), one observed and one forecast.  They diverge after
  that: the reanalysis fell ~550-690 m2/s2 a day, the forecast only
  ~120-260, so the pulse fades towards the climatology.
* The 20261120 00Z run (45 days, 101 members) is published on **both
  sites** - the card reads init 2026-11-20 and the chart's caption reads
  "2026-11-20 00Z run".  The 21 November run is not in the archive yet.

## Still open

1. **The December cadence**: the CDS request pool is now started **once a
   day** by the daily job, not every twenty minutes.  A sandbox rebuild
   kills it every hour, so the queue is only alive for the first hour
   after the job runs - the requests it submits still go to the archive,
   but the results are picked up by the next run.  If the December
   rollover needs the queue to be alive continuously, the cadence has to
   come back: that is the owner's call, not a detail.
2. **`notes/EXPANSION.md`** - six questions for the owner; the expansion
   must not be rebuilt before they are answered.
3. The **`thinking_content` masks** (a platform defect, not ours): see
   `notes/THINKING_MASKS_BUG.md`, audit with `tools/transcript_doctor.py`.
4. The operational site has **no favicon** (a 404 on every page).  The
   development copy has one (`assets/favicon.ico`, copied by
   `copy_favicon()`).  Putting one on the operational site needs the
   owner's word.

## Done on 22 Nov 2026

* **The globe's tilt alone** (the owner's answer `o3`): the flat map
  pans and no longer turns on the screen, the ↻ button is the globe's
  alone, `state.turn` and the `u_turn` branch in `assets/js/mapgl.js`
  are out, and the projection still agrees with d3 to 1.1e-12 px (the
  flat view included - the suite checks both views).
* **The polar-cap section opens on the NOAA GEFSv12** on both sites
  (`build_polar_page.py`'s `DEFAULT`, plus the narrow path's
  `--default-only`).
* **The 20261121 00Z cycle is on both sites** (35 days, 31 members).

## The traps of this morning

* **THE CHART BUILDER MUST RUN BEFORE THE REGISTRY BUILD.**  The build
  copies the drawn charts out of `output/polar_cap/` - so if the charts
  are not redrawn first, the build publishes the OLD ones again, and the
  site carries a new cycle's date over an old cycle's picture.
* **THE CORe FILE MUST BE FRESH.**  The chart's reanalysis half is drawn
  from `data/polar_core_recent.npz`; a file that is a day old moves the
  reanalysis window, and the chart differs from the published one by
  ~8% of its pixels.  `python3 fetch_polar_core.py` first, then draw.
* **THE STATE FILE IS NOT THE SERIES.**  `data/polar_gefs_jobs.json`
  holds the decoded LEADS; the series is `data/polar_model_z.json`.  A
  rebuild from the state (`fetch_polar_gefs.py --from-state`) writes the
  cache - but only the leads the state holds, so a state that is still
  being filled gives a SHORT series (22 of 35 days) and the publisher
  refuses it (a half season is not a season).
* **THE WATCHER AND THE DEV COPY.**  The watcher's own tree is built by
  the general build, so its pages carry the blob its tree holds and the
  narrow path can patch it; a tree that was only partly rebuilt cannot.
* A local clone of the operational repository can be **behind the
  server** without noticing: `git pull` failed silently once - check
  `git ls-remote` before publishing into it.

## The owner's CORe question, answered with measurements (22 Nov 2026)

**"still don't think CORe Reanalysis is correct as it blends right into the
analysis of said model making it seem like there's no differences"**

* **The CORe data IS correct.**  Read straight out of NOAA's own GRIB
  (byte ranges from the `.idx`, the cap mean computed by hand): 292,646.1
  m2/s2 at 10 hPa for 20 Nov 2026 - the value the site stores, to the last
  decimal.  13 Nov reads 296,256.6, the number an earlier session measured
  independently.
* **WHY IT BLENDS IN ON THE GEFS CHART: the two halves are ONE MODEL.**
  CORe is NOAA CPC's Conventional Observational Reanalysis built on the
  **FV3-GFS**, and the GEFSv12 **IS** the FV3-GFS.  So the left half is
  the FV3-GFS's analysis and the right half is the FV3-GFS's forecast,
  joined at their own init.  A model joined to itself is smooth by
  construction - the GEFS chart is INCAPABLE of showing a discrepancy, so
  its smoothness is a tautology, not a validation.
* **They are not the same numbers** (measured on the chart's own path -
  the CORe climate, the same join, the same normalisation):
  CORe's last drawn day (20 Nov) 292,646.1 = +1.335 sigma, the GEFS's
  first day (21 Nov) 292,500.6 = +1.271 sigma; the seam step is
  **-145.4 m2/s2 = -0.028 sigma** (the chart's own daily sigma is
  1975.7 m2/s2).  The analysis was falling **-515.8 m2/s2 a day** over
  its last eight days; the forecast falls **-96.8** and the EC46
  **-197.8**.  The forecast flattens out where the analysis was plunging.
* **WHY IT LOOKS IDENTICAL ON SCREEN: the colour ladder.**  The chart's
  breaks are -0.2 / 0 / +0.2 sigma at the centre, so a step of 0.03 sigma
  cannot change a single pixel's colour.  It is a coarse ruler over a fine
  difference.
* **THE CROSS-MODEL TEST IS THE EC46 CHART** (ECMWF against NOAA): the
  seam there is **+46.2 m2/s2 = +0.069 sigma**, and the EC46's forecast
  then falls steadily away from the analysis.
* **THE REBASE GATE (a code fact).**  `polar_rebase.climate_matches()`
  only lets a chart be re-based when the chart's RUN is the climate's own
  init.  `polar_model_clim.json` carries `init = 2026-11-01` (the SEAS5's
  own), so: the SEAS5 **is** re-based (its run string is empty, the gate
  cannot refuse); the GEFS is not (20261121 != 20261101) and must not be;
  **the EC46 is not either** (2026-11-20 00Z != 2026-11-01) - by design,
  because that correction is the SEAS5's own bias and nobody else's.  The
  consequence is that the EC46's forecast half sits on the OBSERVED climate
  and carries the ECMWF mean-state offset (Nov -641 m2/s2, measured;
  about -0.3 sigma) - so the EC46's anomalies are NOT "vs its own
  hindcast climate" the way the SEAS5's are.  Its caption says so
  ("CORe 1991-2020 climatology").
* **The SEAS5 chart DOES show a seam** (+1.0 sigma at the dashed line,
  from the rebase) - so the machinery that makes a difference visible
  exists and works.
* **NOTHING WAS CHANGED.**  The remedies are the owner's call (see the
  chat): say in the chart's own descriptor that the GEFS's two halves are
  one model with itself; or draw the 31-member spread as a fan (the cache
  keeps only the mean - the fetchers must keep the members); or put a
  different reanalysis on the left (ERA5 is ~600 m2/s2 colder over the
  cap in ARCO's store and mutes the SSW - it would show a false step).

* **AND THE DIFFERENCES ARE THERE - the chart's seam is drawn at the WRONG
  INSTANT.**  The CORe's daily file is a day's MEAN (stepRange 0-21,
  centred near 10.5Z) and the site's file labels those points "12Z".  The
  chart's analysis half therefore ends with 20 Nov's day's mean while the
  forecast half starts at 21 Nov 12Z - **25.5 h apart**, while the
  stratosphere was falling **409 m2/s2 that day**.  Measured at the SAME
  instant on 21 Nov (the CORe for 21 Nov = 292,237.4, read from NOAA's own
  GRIB; the day's mean interpolated to 00Z and 12Z):

  | | the forecast | the analysis, same instant | difference |
  |---|---|---|---|
  | GEFSv12, 21 Nov 12Z (f012) | 292,500.6 | 292,211.9 | **+288.8 = +0.146 sigma** |
  | EC46, 21 Nov 00Z (f024) | 292,692.2 | 292,416.2 | **+276.0 = +0.140 sigma** |

  The chart draws **-145.4 m2/s2 (-0.028 sigma)** at that seam - an
  artefact of the timing, not the model's behaviour.  (The same-instant
  numbers carry about +-180 m2/s2 of interpolation uncertainty, because
  the daily product is a day's mean.)
* **THE TWO CENTRES AGREE WITH EACH OTHER, NOT WITH THE REANALYSIS.**
  At 21 Nov 00Z the GEFS (brought back 12 h on its OWN rate) and the EC46
  differ by **128.8 m2/s2 = 0.065 sigma** - and both sit about +280 above
  the CORe.  So the gap is between the reanalysis and the analysis the
  models start from, not between the two centres' forecasts.  The likely
  reason: **CORe assimilates no satellite radiances** (conventional
  observations only) while the GFS's own analysis uses them, and 10 hPa is
  exactly where that difference lives.
* **THE TWO CENTRES DIVERGE WITH LEAD TIME**: the GEFS minus the EC46,
  day by day against the same climate - 0.07 sigma on day 1, 0.13 on day 6,
  **0.40 on 1 December**, 0.26 on day 35.  **This is the picture that
  answers "there should be differences", and both series are already on
  disk - no reanalysis needed.**
* **THE TENDENCIES DIFFER**: the analysis fell 409 m2/s2 on 21 Nov; the
  GEFS's forecast falls ~126 a day and the EC46's ~198 - the forecasts
  decay the pulse more slowly than the analysis did, so the
  forecast-minus-analysis gap compounds with lead.
* **THE COLOUR LADDER CANNOT SHOW A 0.14 SIGMA STEP** (the first band is
  +-0.2 sigma), so even a corrected seam stays inside the white centre.
* The CORe's 22 November file is **not published yet** (the bucket's last
  file is 21 Nov), so the site's analysis half is a day behind what NOAA
  has, and the day-2 check lands when it appears.

## The owner's answer, and the 3-hourly CORe (23 Nov 2026)

**THE OWNER:** *"just need the past 6hr CORe analysis to differ from GEFSv12,
SEAS5, EC46 analyses if they do because it looks like one continuous forecast
from reanalysis to model forecasts"*.  So: the reanalysis's analysis against
each model's own analysis, at the SAME instant.

**THE NEW ROUTE - THE BUCKET'S 3-HOURLY TREE.**
`https://storage.googleapis.com/noaa-nws-ncep-core/grib/3hour/pgb/YYYY/MM/pgb.YYYYMMDDHH.grb`
(+ `.idx`), an analysis at every three hours, current to the present hour
(the 22 Nov 00Z file was there on the 23rd).  **IT IS THE SAME PRODUCT AS
THE DAILY FILE**: the daily file's day's mean is the MEAN OF THE DAY'S EIGHT
3-HOURLY ANALYSES, to **0.0 m2/s2** on 1, 2 and 20 November.  The tool is
`fetch_polar_core_3hourly.py`; it writes `data/polar_core_3hourly.json`.
(Not the CPC clone tree: `CORe/CDAS_clone_temporary/6hr/` holds only two
stamps of January 2026 - it is a temporary clone, not a live feed.)

**THE ANSWER: YES, THEY DIFFER - by about 350 m2/s2, or 0.18 sigma**, at
10 hPa over the polar cap, at the SAME instant:

| what | the day | the model | the CORe | difference | sigma |
|---|---|---|---|---|---|
| GEFSv12's OWN analysis (f000, 31 members) | 21 Nov 00Z | 292,685.0 | 292,335.2 | **+349.8** | **+0.177** |
| GEFSv12 day 1 (f012) | 21 Nov 12Z | 292,500.6 | 292,346.4 | +154.3 | +0.078 |
| EC46 day 1 (f024) | 21 Nov 00Z | 292,692.2 | 292,335.2 | +357.1 | +0.181 |
| SEAS5 day 1 | 2 Nov 12Z | 297,698.8 | 298,090.4 | **-391.7** | -0.317 |

* The GEFS's own analysis is the 31-member mean of lead **f000**, fetched
  by `tools/fetch_gefs_analysis.py` (it imports the running fetcher's
  machinery; the fetcher itself is not edited).  The spread across the 31
  members is **42.7 m2/s2**, so the analysis is tight.
* The ECMWF's 24-hour forecast for 21 Nov 00Z lands within **7 m2/s2** of
  NOAA's own analysis for that instant - the two centres agree with each
  other, and both sit ~350 above the CORe.  **So the gap is between the
  reanalysis and the models' analysis, not between the centres.**  The
  likely reason: **CORe assimilates no satellite radiances** (conventional
  observations only) while the GFS's own analysis uses them, and 10 hPa is
  exactly where that difference lives.
* The SEAS5's first point sits **392 BELOW** the CORe's analysis - which is
  the ECMWF's colder mean state (its own climate is -641 in November).
* **THE EC46's OWN ANALYSIS IS NOT SERVED**: a probe for leadtime_hour
  "0_24" (20 Nov, one level, control only) came back **rejected**.  The
  EC46's row therefore uses its first forecast point.
* `tools/compare_core_models.py` prints the table.

**WHY THE CHART STILL SHOWS NOTHING.**  Two things, and both are known:
the seam joins the CORe's 20 Nov day's MEAN with the forecast's 21 Nov 12Z
- **25.5 hours apart** on a day the stratosphere fell 409 - and the first
colour band is **+-0.2 sigma**, so a 0.18 sigma difference cannot change a
pixel.

## What the reference site does about the seam (23 Nov 2026, gathering only)

The owner pointed at **hebweather.net/stratosphere** ("how does this site
do it?? DO NOT COPY ANYTHING, JUST GATHERING MORE INFO").  The site's own
method is written out in its page - the "About these products" panel - so
the facts can be read off it rather than guessed:

* **Data:** ERA5 reanalysis (CDS, 2.5 deg, pressure levels 1000-1 hPa,
  daily 00 UTC) is the history **and** the climatology (1991-2020 ERA5).
  The models are sampled onto a common **1.0 deg** grid: GFS 1.0 (NOMADS,
  +24 to +384 h), GEFS 0.5 ensemble mean, IFS 0.25 (00Z/12Z, 15 d),
  AIFS single 0.25.  Their notice: "zonal means, anomalies relative to the
  1991-2020 ERA5 climatology, vertical interpolation, plotting".
* **The seam, in their words:** *"a dashed vertical line marks the boundary
  between ERA5 reanalysis (left, solid shading) and the model data (right,
  lighter shading)"*, and *"ERA5 ends a few days behind real time.  When
  the gap is more than one day, a second dashed line marks the current
  date.  Between the last ERA5 day and that line the chart shows the
  selected model's own 1-day forecasts from the previous days' runs (Past
  Days), which stand in for the analysis until ERA5 catches up.  The
  forecast itself (Forecast) is to the right of the line."*
* **So they do NOT join the reanalysis to the model's first forecast
  point either.**  Three segments: the reanalysis up to ITS last day, then
  the MODEL's own past days, then the forecast; the model's side is
  lighter, and every seam is a dashed line with a label.
* Their GPH anomaly product: the daily polar-cap mean (60-90N, all
  longitudes) in sigma against the 1991-2020 ERA5 climatology; the chart's
  own label reads "Zonal Mean (65-90N)"; the sector products are 65-90N
  over a 120 deg sector.
* "Same history: everything left of the dashed seam is identical in all
  sets, so the models can be compared directly."
* Their forecast is 16 days (GFS/GEFS) or 15 (IFS/AIFS); ours is the
  GEFSv12's 35.

**WHAT IT MEANS FOR US (nothing built, nothing copied):** the device that
shows a reader where the reanalysis ends and the model begins is the
**"Past Days" segment** - the model's own values standing in for the
analysis while the reanalysis catches up.  We have the same thing and
better: the GEFS's **f000 analysis** and the **3-hourly CORe** let us draw
the model's own analysis against the reanalysis's analysis at the same
instant, which is what the owner asked for on 23 Nov.

## The seam, rebuilt (24 Nov 2026)

**THE OWNER:** *"yes use the Past Days idea, 3 hrly CORe and the GEFS f000
analysis amongst EC46 and SEAS5"*.  What the three polar-cap charts now do:

* **The reanalysis half is drawn at an INSTANT**, not at a day's mean: the
  3-hourly CORe at the model's own clock hour (12Z for the GEFSv12 and the
  SEAS5, 00Z for the EC46).  The day's mean is up to 25 hours away from the
  forecast's first point, and on a falling day that gap is worth 400 m2/s2.
  The caption says which basis it used ("(12Z, 3-hourly)"), and the whole
  half falls back to the daily file if one stamp is missing.
* **The GEFSv12's OWN analysis (lead f000, 31 members) stands between the
  reanalysis and the forecast** - the reference site's "Past Days" segment,
  done with the model's own analysis instead of its past one-day forecasts.
  The chart now carries three labelled parts and TWO dashed seams:
  "CORe reanalysis" | "GEFSv12 analysis" | "GEFSv12 sub-seasonal forecast".
* **THE DIFFERENCE AT THE HANDOVER IS WRITTEN ON THE SEAM** - "model - CORe:
  +0.18 sigma", in bold, just inside the panel, with a white halo.  It is
  where the reader is looking, and the caption has no room for it.
* The numbers (10 hPa over the cap, at the same instant, 21 Nov 00Z):
  the GEFSv12's analysis **+0.18 sigma** above the CORe, the EC46's first
  point **+0.18 sigma** above it, the SEAS5's first point **-0.32 sigma**
  below it (the ECMWF's colder mean state).

**TWO FAULTS FOUND IN NOAA'S OWN TREE (both fixed):**

* **NOAA publishes some of the three-hourly files with a ZERO-BYTE `.idx`**
  (the 00Z stamp of 18 Nov 2026, and 17 others in the cache).  There are no
  byte ranges to read, so the fetch now decodes the WHOLE file when the
  inventory is empty (`cap_mean_all`).  **An empty record must count as
  MISSING** - an earlier version of the tool cached the failure as a good
  one, and the chart silently fell back to the daily file for a week.
* **EVERY LEVEL IN A CORe FILE HOLDS ELEVEN VARIABLES**, and the GRIB's
  `shortName` for the geopotential height is **`gh`**, not `HGT` (the `.idx`
  writes "HGT").  A decoder that filters on the level alone reads the
  STREAM FUNCTION and returns a number millions of times too large - it drew
  a dark blue stripe down the EC46 chart.  Both decoders now select the
  variable (`HEIGHT_NAMES`) and check the value's range (`SANITY`).
* **A SANITY BOUND MUST SPAN THE QUANTITY'S OWN RANGE**: the polar-cap mean
  of the geopotential is about 290,000 m2/s2 at 10 hPa and about 200 m2/s2
  at 1000 hPa, so a bound of 1e5 to 6e5 throws away every low level.

**AND ONE IN OUR OWN CODE:**

* **THE CAPTION'S FIT CHECK MEASURED THE WRONG PIXELS.**  The chart's figure
  is created at the default 100 dpi and SAVED at 150 dpi, so the text is
  rendered small and scaled up by 1.5 - `fit_subtitle` measured it at 150 dpi
  and let the caption run off the right edge.  It now measures in the pixels
  the file actually has.

**THE DEV SITE WAS ROLLED BACK AND FIXED.**  The narrow publisher's
`--force` bypasses its own "never put the site back to an older cycle"
guard, and this tree's series was a cycle behind the watcher's (the watcher
runs in its own clone), so a forced publish put the **2026-11-21** cycle
back on the development copy.  The operational clone was reset to the
server's HEAD and nothing was pushed there.  **Two rules from that:**
`--force` is for a redraw of the SAME cycle, never for an older one; and
the publisher's **default target is the OPERATIONAL clone** (`/workspace/repo`)
- always pass `--repo`.

**WHERE THE THREE CHARTS ARE NOW (24 Nov 2026, 04:00 UTC).**

* The **development copy** carries all three with the new device: the
  GEFSv12 at the **20261123 00Z** cycle (35 days, 31 members, the newest
  complete cycle), the EC46 at the 20261120 00Z run, the SEAS5 on its own
  monthly product.  The SEAS5 went out through **a new narrow path**,
  `tools/publish_polar_seas5.py` - it is one of the site's own models, so
  it used to go out with the general build, and the general build is off.
* The **operational site** carries the GEFSv12 at the 20261123 cycle, drawn
  by the **nightly watcher** at 03:43 UTC (its own clone, taken at 03:00
  UTC).  That chart has the model's own analysis but **not** the seam note
  and **not** the short names, so its two panel labels run into each
  other.  The fixes are committed; the next watcher run redraws the chart
  with them.  **Nothing was pushed there by hand** - the owner's word for
  this work was not to touch the operational site.

**AND TWO MORE THINGS THE NIGHT TAUGHT:**

* **THE SHORT NAME MUST BE A CONSTANT** (`plot_polar_cap.SHORT_NAME`).
  The narrow publisher draws the GEFSv12 with the long product name and no
  short one, so the panel labels ran into each other on the site.
* **A REDRAW OF THE SAME RUN HAS TO MOVE THE `?v=`.**  The EC46's path only
  ever ADDED its entry, so a redrawn chart could not reach the reader: the
  browser kept serving the old picture.  Both narrow paths now bring the
  chart URL forward, and both skip the copy when the source tree IS the
  target (the development copy is its own source).

## The rules that are not negotiable

* Our own graphics; a climatology from the same product as the data it
  normalises; a missing file never justifies removing a chart.
* **Approval before** a new data pull, a new chart family, a new route or
  a new worker; one submitter at a time.
* Nothing on the operational site without the owner's explicit approval.
* Never commit a `*.part` file; never edit a running script.
* **A membership is a constant, not a record** of the last run.
* The state lives here, in git, and in the agent's memory - never only in
  a conversation.
