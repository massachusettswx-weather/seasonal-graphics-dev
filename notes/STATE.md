# The state of the project - 20 Nov 2026, 22:40 UTC

Short and factual.  The long history of how it got here is in
`notes/STATE_LOG.md`; the rules that are not negotiable are in
`notes/PROTECTION.md` (the data) and `notes/PUBLISHING.md` (the two
sites).  This file is the handoff: a new session reads this and does not
need the conversation.

## The two sites

| | repository | address | state |
|---|---|---|---|
| **operational** | `massachusettswx-weather/seasonal-graphics` | `https://massachusettswx-weather.github.io/seasonal-graphics/` | published at `0f33e70`, HTTP 200, untouched by the pipeline |
| **development** | `massachusettswx-weather/seasonal-graphics-dev` | `https://massachusettswx-weather.github.io/seasonal-graphics-dev/` | published at `e455654`, open (no password) |

* The development copy is the working copy: everything new is built and
  shown there first.
* The operational site is **curated**.  Nothing reaches it without the
  owner's word.
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
* **The operational site carries the older site**: the panels, the pages,
  the polar cap section with the **GEFSv12 panel still on the 2026-11-14
  cycle**.  It has no map page.
* The GEFSv12 sub-seasonal series is at the **20261119 00Z** cycle in the
  working tree (35 days, 31 members, 12 levels) and is on the development
  copy.

## The workers

* They run in `/workspace/devrepo`: the CDS request pool and the polar
  puller.  The sandbox is rebuilt every hour, which kills them.
* **There is ONE scheduled task** (22 Nov 2026), `seasonal-gefs-subs`
  (`465527736623226`), at **05:00 America/New_York** (= 10:00 UTC, about
  an hour after NCEP's 00Z cycle carries its full 35-day range - measured:
  the last lead of the 20261120 00Z cycle landed at **09:04 UTC**).  It
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
* It rebuilds the inlined registry with the **TARGET's own**
  `build_site.py` (the `ok` flags come from the files that are really
  there) and refuses if that blob is not in the pages.
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

**`tools/gefs_subs_disseminate.sh`** is the job that runs it once a day:
it puts the pipeline back (it clones the tree if a rebuild took it), pulls
the day's data, fetches the **newest complete 00Z cycle** in the
foreground - so "the run has finished" is an answer and not a hope -
commits the fetch state (it is in git, so a rebuild does not download an
hour again), and publishes to the development copy and to the operational
site.  **The trigger is the RUN, not a clock.**

## Still open

1. **The globe's tilt only** (the owner's answer `o3`, 20 Nov).  The flat
   map's turn has to go: the ↻ button becomes globe-only, `state.turn`
   and the `u_turn` branch in `assets/js/mapgl.js` come out, and the
   drag returns to panning on the flat map.  Then rebuild, test the round
   trip (d3 cannot express a tilt) and publish to the **development**
   copy.
2. **The operational push of the daily GEFSv12 update** - DONE: the narrow
   path is live, the daily job runs it, and the live site carries the
   2026-11-19 cycle (22 Nov 2026).
3. **The December cadence**: the CDS request pool is now started **once a
   day** by the daily job, not every twenty minutes.  A sandbox rebuild
   kills it every hour, so the queue is only alive for the first hour
   after the job runs - the requests it submits still go to the archive,
   but the results are picked up by the next run.  If the December
   rollover needs the queue to be alive continuously, the cadence has to
   come back: that is the owner's call, not a detail.
4. **`notes/EXPANSION.md`** - six questions for the owner; the expansion
   must not be rebuilt before they are answered.
5. The **`thinking_content` masks** (a platform defect, not ours): see
   `notes/THINKING_MASKS_BUG.md`, audit with `tools/transcript_doctor.py`.

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
