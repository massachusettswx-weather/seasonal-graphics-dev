# Surviving a wipe

The sandbox resets from time to time. When it does, the working tree comes
back **empty** - no repository, no `data/`, no `docs/`, no credentials.
This is what makes a session stall: the previous session's work is not
"lost" exactly, it is *scattered* across three places, and it has to be
gathered again by hand.

This note says where each piece lives and what to do about it.

## The four places a piece of work can live

| place | survives a wipe? | holds |
|---|---|---|
| **the GitHub repositories** | yes | the code, the published site, the small derived data, the job ids |
| **the encrypted secret store** | yes | the CDS/ECDS key, the GitHub token |
| **the agent's memory** | yes | the hard-won knowledge: the traps, the house rules |
| **the sandbox working tree** | **no** | the model data, the credentials, the packages |

The rule that follows: **anything that must survive goes in the first
three, and the working tree only ever holds what can be rebuilt.**

## What is in the working tree, and what to do when it is gone

| thing | how to get it back |
|---|---|
| `data/models/<tag>/snowfall_monthly.grib` | the forecast field - `tools/recover_jobs.py` |
| `data/models/<tag>/snowfall_hindcast.grib` | the model's own climate - same |
| `data/models/<tag>/u10_daily.grib` | the daily 10 hPa wind - same |
| `docs/assets/**` | the rendered panels - re-render from the data |
| `.cdsapirc` | `tools/restore_secrets.sh` (from `CDS_API_KEY`) |
| `data/.github_token` | `tools/restore_secrets.sh` (from `GITHUB_TOKEN`) |
| the python packages | `tools/restore_env.sh` |

## The one command

```bash
export CDS_API_KEY=<the cds key>
export GITHUB_TOKEN=<the github pat>
git clone --depth 50 https://github.com/massachusettswx-weather/seasonal-graphics-dev.git
cd seasonal-graphics-dev
./tools/bootstrap.sh
```

It clones, restores the credentials, puts the packages back, recovers the
model data and prints what is still missing.

## Why the job ids are tracked

The model data is gitignored because it is bulky. The obvious cost of that
is a fresh queue on the Copernicus store for every model, and the store's
queue is slow and shared with every other user - hours per job.

But a job keeps its **result** on the store after the request is made, and
the job id is 36 characters. So `data/fetch_manifest.json` is tracked and
lists, for every fetch, the request body and the job id. After a wipe,
`tools/recover_jobs.py` walks that manifest:

* the file is already there -> skip;
* the job still has a result -> download it again, **no queue time**;
* the job is gone -> re-submit the request from the manifest, one at a
  time.

So the manifest turns a wipe from "hours of queueing" into "a few
downloads", and it is the cheapest insurance in the project: regenerate it
with `python3 tools/write_fetch_manifest.py` after any fetch.

## The credentials

They are deliberately **not** in git - `.cdsapirc` holds the CDS/ECDS key
and `data/.github_token` holds the GitHub token, both mode 600, both
gitignored, and `push_to_github.sh` scrubs the token from the remote after
the push.

So they live in the **encrypted secret store** instead, which survives the
reset. A session that finds no key should ask the owner for it once, store
it there, and write it back out with `tools/restore_secrets.sh`.

## The handoff

`notes/STATE.md` is the living state of the project: what is published,
what is in flight, what the next task is, and the rules that are not
negotiable. It is tracked in git, so it comes back with the repository
after a wipe. **Update it before you end a session.**
