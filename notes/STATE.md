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
* The **keepalive** (task `464432350077090`, every 20 minutes) restores
  them after a rebuild.  It now runs in **its own conversation**, not the
  owner's, and its prompt is rewritten: the publisher stays off, the
  operational site is never touched, the recovery is `--no-request` for
  the eight C3S centres.
* The daily pull is `tools/daily_refresh.sh` (OISST, NOAA ENSO, CFSv2 in
  the foreground; SFS, CORe and the GEFS detached, because the GEFS takes
  about an hour for a new cycle).

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

## The narrow path to the operational site (new, 20 Nov 2026)

The owner's request: *"Stop the scheduled updates.. we need to extend the
daily GEFSv12 SUBS update to the live site as well"*.

**`tools/publish_polar_subseasonal.py`** is that narrow path.  It carries
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
* **Nothing is published when the update is missing** (exit 2) and the
  live site is never put back to an older cycle.
* **The push fails loudly** (exit 3) if the repository cannot be reached:
  the commit stays local and the site keeps the old cycle.
* The operational destination needs `--prod --approved`; without them the
  script refuses to push, whatever the remote says.
* It is **not** wired into the daily run yet.  The owner's word is the
  only thing missing: one line in `tools/daily_refresh.sh` turns it on.

## Still open

1. **The globe's tilt only** (the owner's answer `o3`, 20 Nov).  The flat
   map's turn has to go: the ↻ button becomes globe-only, `state.turn`
   and the `u_turn` branch in `assets/js/mapgl.js` come out, and the
   drag returns to panning on the flat map.  Then rebuild, test the round
   trip (d3 cannot express a tilt) and publish to the **development**
   copy.
2. **The operational push of the daily GEFSv12 update** - ready, proven on
   a local clone, waiting for the owner's word.
3. **`notes/EXPANSION.md`** - six questions for the owner; the expansion
   must not be rebuilt before they are answered.
4. The **`thinking_content` masks** (a platform defect, not ours): see
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
