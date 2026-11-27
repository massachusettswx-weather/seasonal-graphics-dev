# The chat that looped out - "Global Snowfall Anomaly Maps" (27 Nov 2026)

## WHAT HAPPENED

The chat **"Global Snowfall Anomaly Maps"** (session `464211911843922`) was
asked at **18:12 and again at 18:16 UTC on 27 Nov 2026** to

> "Again, do not copy, but lets work on getting ECMWF EPS to the 'by sector'
> area on dev page, but CANNOT copy Stormvista, don't include labels they have
> on their graphs, make it our style and make sure all data (EPS, GEFSv12 Ext
> and SEAS5) use actual data. We can enable the scheduler to watch for EPS
> data at the same time as EC46, but only include the main 00, 12z suite from
> EPS"

and **both replies died the same way**: the model's reasoning went into a
loop - its last 12,288 characters were the same few words ("hmm: hmm: hmm")
over and over - and the request failed.  **Nothing was answered, and nothing
was built.**

The reason is visible in the transcript: the turn spent itself on one
question - *what exactly is "ECMWF EPS", given that our EC46 is already the
ECDS's `s2s-forecasts`?* - and circled it instead of deciding.  **The answer
to that question is below.  Use it and do not re-derive it.**

## WHAT THE FAILED TURN HAD ALREADY ESTABLISHED (all of it still true)

* **The source is the ECDS's `s2s-forecasts` dataset**, and the catalogue has
  **no `system` parameter** - the product is picked by the **run date**.  On
  the runs that carry the extended range (Mondays and Thursdays, 00Z) the
  archive serves the **46-day** product, which is what our **EC46** already
  is; **on every other run it serves the 15-day ensemble**, which stops at
  lead 360 h.
* **The request's shape**: `origin: ecmwf`, `year/month/day/time`
  (**00:00 or 12:00**), `level_type: pressure`, `variable:
  geopotential_height`, `level_value` (ten levels: 10, 50, 100, 200, 300,
  500, 700, 850, 925, 1000 hPa - **no 30 hPa and no 400 hPa**),
  `forecast_type: [control_forecast, perturbed_forecast]`, `leadtime_hour`
  (24-hour windows), `area: [90, -180, 60, 180]`, `data_format: grib`.
* **The by-sector chart's plumbing** (`plot_polar_sectors.py`): the series
  must carry the **sector means** under `sectors` (`natl`, `npac`), and it
  reads them from `cache_for(tag)` - `data/polar_ec46_z.json` for the tag
  `ec46`, otherwise `data/polar_model_z.json`.  The reanalysis half (15 days,
  the same as the cap section) comes from `data/polar_core_recent.npz`, and
  the sector climatology from `polar_cap_clim_cdsdaily.npz` /
  `polar_cap_clim_core.npz` / `polar_cap_clim_monthly.npz`.
* **The three by-sector charts that are live** carry real data: the SEAS5
  (194 days, seven months), the GEFSv12 (the 20261126 00Z cycle, 35 days,
  31 members) and the EC46 (the 2026-11-25 00Z run, 45 days).  All three
  have the sector means.
* **The registry the page reads** is the `POLARSECTORS` object in
  `docs/spv.html`, and `tools/publish_polar_ec46.py` is the narrow publisher
  that draws the by-sector chart and patches that entry.

## THE DECISION THE LOOP WAS LOOKING FOR

**"ECMWF EPS" = the ECMWF's medium-range ensemble - the 15-day product the
ECDS's `s2s-forecasts` serves on every run that is not a Monday or a
Thursday 00Z - at both of its cycles, 00Z and 12Z.**  The owner's "the main
00, 12z suite" is that: **both cycles**, not the extended range (which is
already the EC46) and not a single cycle.

So the work is: a **sibling of `fetch_polar_ec46.py`** that pulls the
15-day ensemble (leads up to 360 h) at 00Z and 12Z, decodes it into a series
with the **sector means**, and hands it to the by-sector chart as a new
model - plus the scheduler step that watches for it **in the EC46's window**,
so the two never overlap and there is never a second submitter.

**The house style, not StormVista's**: the by-sector chart already draws the
house's own panels (both panels carry every date, the colour bar under the
panels, the watermark bottom right, the ECMWF credit).  **No StormVista
labels** - no "SSW" / "+WPO" / "-NAO" / "SSW Impacts Have Ended" annotations
and no StormVista branding - and the owner's point stands for the GEFSv12
Ext and the SEAS5 too: **every chart in the by-sector area must be drawn from
actual data.**

## THE REPO WAS DAMAGED, AND IS REPAIRED

The development copy's `main` was **force-pushed** (rewritten) during the
day, and the rewrite **dropped `tools/ec46_disseminate.sh`** - the very
script the scheduled **`seasonal-ec46`** job (467751157227592, `0 21 * * 1,4,6`
UTC) runs.  The script had been added by `76f6466` and deleted again by
`526f862` ("The GEFSv12 fetch state, so a rebuild does not download it
again"), whose tree was stale for `tools/` and `notes/STATE.md`.

**It has been restored** - byte for byte from `76f6466`, and checked against
the other chat's own `write` call (4,562 bytes, identical) - so the Monday
night job has its script again.  Nothing else was lost: `daily_refresh.sh`,
`gefs_subs_disseminate.sh` and `STATE.md` are all newer upstream than
`76f6466`.

## THE ENVIRONMENT

The sandbox had been rebuilt again (the tree, the packages, the credentials
and every worker gone).  On 27 Nov 2026: the tree was cloned and
fast-forwarded to the server's head, the credentials came back from the
encrypted secret store, and `tools/auto_run.sh` put the workers back - the
**CDS request pool** and the **polar-cap puller** are running and the
**general publisher is off** (`SITE_NO_PUBLISH=1`).

## WHERE THE RAW MATERIAL IS

* The transcript of the failed turn: `/workspace/logs/chat27_global_snowfall.json`
  (the last 100 messages of the session; the tool calls and their results are
  intact - only the reasoning is damaged).
* The audit tool: `python3 tools/transcript_doctor.py <transcript.json>`
  (`--salvage` prints the damaged messages so they can be read).
* The last turn's own salvage, from 23 Nov: `notes/chat_recovery_2026-11-23_salvage.txt`.
