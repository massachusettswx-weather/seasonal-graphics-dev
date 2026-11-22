# The state of the project - 22 Nov 2026, 04:20 UTC

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
* The GEFSv12 sub-seasonal series is at the **20261121 00Z** cycle (35
  days, 31 members, 12 levels) and is on **both** sites.

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
