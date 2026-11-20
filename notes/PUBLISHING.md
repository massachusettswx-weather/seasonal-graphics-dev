# Publishing: the development copy and the operational site

There are TWO sites and they are two repositories:

| | repository | address |
|---|---|---|
| **dev** | `massachusettswx-weather/seasonal-graphics-dev` | `https://massachusettswx-weather.github.io/seasonal-graphics-dev/` |
| **operational** | `massachusettswx-weather/seasonal-graphics` | `https://massachusettswx-weather.github.io/seasonal-graphics/` |

```bash
./push_to_github.sh            # the DEVELOPMENT site (the default)
./push_to_github.sh --prod     # the OPERATIONAL site
```

**A change is never automatically put on the operational site.**  It goes to
the development copy, where it can be anything, and it reaches the
operational site only when `--prod` is asked for.

## Why the build has to be told which target it is making

The site's links are ABSOLUTE (the nav tabs, the crumbs, the canonical
tag, the title link), because a relative `href="index.html"` made the
browser resolve it to `.../index.html` and that is what popped up in the
reader's link preview.  An absolute link, though, is only right for the
site that is actually being published - a dev build that links to the
operational site sends the reader to the wrong place, and its canonical
tag would point at the operational copy.

So `build_site.py` takes the target from the environment:

| variable | meaning |
|---|---|
| `SITE_URL` | the site's base URL |
| `SITE_REPO_URL` | the repository the "GitHub" link goes to |
| `SITE_DEV=1` | mark the build as the development copy |

and `push_to_github.sh` sets all three before it builds.  The build runs
**before** the commit, so the commit carries the right copy.

The development copy is marked "DEVELOPMENT COPY" in the header line and
in the browser tab, so nobody mistakes it for the live site.  The title
carries plain text (a `<title>` may not hold markup); the header line
carries the bold version.

## The README follows the target too

The README's link is rewritten by PATTERN, not by a placeholder: the build
writes the README back, so a placeholder would be consumed by the first
build and the second one would have nothing to replace.

## The history is shared, and that is fine

Both repositories get the same commits; they differ only in the LAST
commit, which carries the build for that target.  The operational
repository therefore keeps the whole history (its old commits, the
development commits, and the promoting commit) and its Pages site always
serves the tip - the production build.  A promote is a fast-forward, so no
force is needed.

## What the token can and cannot do

**17 Nov 2026:** the token in the encrypted store belongs to
`massachusettswx-weather`, which owns the **operational** repository and
**cannot** write to `Matthew22-cmd/seasonal-graphics-dev` (GitHub reports
`permissions: {push: false}` - pull only).  So the development copy now
lives at `massachusettswx-weather/seasonal-graphics-dev` - a separate
repository, the same gate, and the only place the pipeline publishes.
The operational repository is still never touched without the owner's
explicit `--prod --approved`.

To put the development copy back under the personal account, add
`massachusettswx-weather` as a write collaborator on
`Matthew22-cmd/seasonal-graphics-dev` and point the script at it with
`GITHUB_DEV_OWNER=Matthew22-cmd` (the URL in `auto_publish.sh` follows
the owner).

The older token belonged to `Matthew22-cmd`, which could create the
development repository under its own account and was a write
collaborator on the operational one.

## The narrow path: ONE product on the operational site (20 Nov 2026)

The general publisher is stopped (`SITE_NO_PUBLISH=1`), and it must stay
stopped: it would carry the whole development site to the live one.  But
the **daily GEFSv12 sub-seasonal panel** has to keep moving there - it is
the only product on the live site that changes every day.

So the live site gets its own path, **`tools/publish_polar_subseasonal.py`**,
which carries **one product, two pictures, one registry entry** and never
rebuilds the site:

    python3 tools/publish_polar_subseasonal.py --repo /workspace/repo
        plan only: what would change, nothing is written
    python3 tools/publish_polar_subseasonal.py --repo /workspace/repo --apply
        the seven files are written into the operational clone
    python3 tools/publish_polar_subseasonal.py --repo /workspace/repo \
        --apply --push --prod --approved
        ... and it is committed and pushed

The seven files are the two GEFSv12 charts, `docs/data/models.json`,
`docs/data/models_public.json`, and the registry inlined in
`docs/model.html`, `docs/snow.html` and `docs/spv.html`.  **Nothing else
on the operational site changes** - its pages, CSS and every other model
stay byte for byte as they are.

* the product is selected by a **constant** (`MODEL_ID = "gefsv12"`), never
  from a file an earlier run wrote;
* **nothing is published when the update is missing** (exit 2), and the
  live site is never put back to an older cycle;
* **the push fails loudly** (exit 3) when the repository cannot be
  reached: the commit stays local and the site keeps the old cycle;
* the operational destination needs **`--prod --approved`**, like
  `push_to_github.sh`; without them the script refuses to push, whatever
  the remote says.

It is not wired into the daily run yet - the owner's word is the only
thing missing.

**WHEN THE 00Z CYCLE IS COMPLETE (measured 20 Nov 2026).**  NCEP uploads
the members of the 00Z cycle in FOUR BATCHES, and the cycle is only usable
when the last member is there at every lead:

| members | landed (UTC) |
|---|---|
| gep01 - gep08 | ~06:40 |
| gep09 - gep16 | ~12:40 |
| gep17 - gep24 | ~18:40 |
| gep25 - gep30 | ~00:40 **the next day** |

So the newest COMPLETE cycle is about **24 hours old** at any moment, and
the daily job at 10:00 UTC always finds the previous day's 00Z cycle as
the newest complete one.  The fetcher says so itself: *"the cycle
20261120 00Z is incomplete: the lead f396 carries 16 members"*.

**TWO TRAPS THIS PATH FOUND ON ITS FIRST RUN.**

* **A CHANGE THAT WAS WRITTEN BUT NEVER COMMITTED IS NOT "ALREADY
  THERE".**  The first run wrote the files and then failed at the commit,
  so the working tree carried the new cycle while the server still had
  the old one - and the next run called it "already published" and did
  nothing.  The check now looks at the FILES as well as at the registry:
  a change of ours that is not committed is finished and pushed.
* **A CLONE THAT HAS NEVER COMMITTED HAS NO `user.name`.**  The commit
  failed with *"Author identity unknown"*.  The identity is now given on
  the command line (`-c user.name -c user.email`), the way
  `push_to_github.sh` does it.
* **THE DEVELOPMENT COPY IS NAMED AFTER THE OPERATIONAL ONE.**  A test
  for the remote that looks for `seasonal-graphics` finds
  `seasonal-graphics-dev` as well, so the operational rules - the clean
  tree, the approval gate - were applied to the wrong repository.  The
  remote's path is now compared exactly: the operational repository is
  `massachusettswx-weather/seasonal-graphics` and nothing else.

## The daily job that runs it (22 Nov 2026)

`tools/gefs_subs_disseminate.sh` is that job, and one scheduled task
(`seasonal-gefs-subs`, 05:00 America/New_York = 10:00 UTC - NCEP's 00Z
cycle carries its full 35-day range by about 09:05 UTC, measured on the
20261120 cycle) runs it in its own conversation.

It does, in order:

1. **puts the pipeline back** - it clones the tree if a sandbox rebuild
   took it, and `tools/auto_run.sh` brings back the packages, the
   credentials and the other workers (the CDS request pool and the polar
   puller);
2. **pulls the day's data** - the observed SST, the NOAA models, CORe,
   and the C3S centres that are not on disk (**download only**: the
   recovery never re-submits a request);
3. **fetches the newest COMPLETE 00Z GEFS cycle** in the foreground, so
   "the run has finished" is an answer and not a hope - and it commits
   the fetch state, which is in git, so a rebuild does not download the
   same hour twice;
4. **publishes** the narrow path to the development copy and to the
   operational site.

**THE TRIGGER IS THE RUN, NOT A CLOCK.**  The panel goes out when the
newest 00Z cycle has finished downloading.

**The general publisher stays off** (`SITE_NO_PUBLISH=1`): the daily job
never runs `auto_publish.sh`, so nothing else about the site is rebuilt
or published.

## The approval gate (16 Nov 2026)

The user: *"DO NOT PUT ANYTHING NOT APPROVED ON THE SITE W/O MY APPROVAL."*

So the operational site is gated in the script itself, not only by
convention:

* `--prod` **refuses to run** without the extra `--approved` flag.  It exits
  with code 2 and touches nothing - no build, no commit, no push.
* the git remote is **always** left pointing at the development
  repository, even after an `--prod` publish, so a bare `git push` can
  never reach the live site.
* the publish flow **rebuilds the registry first**: the registry carries
  the version string that busts the browser's cache on every asset URL,
  so a re-rendered figure gets a new URL instead of being served from the
  cache.

Everything that is not the operational site is fair game on the
development copy - that is what it is for.

## The development copy is behind a password (16 Nov 2026)

The user asked for the development site to be private.  **GitHub Pages does
not exist for a private repository on a free plan** - making the repository
private removes the Pages site entirely (the site 404s and the `pages`
object disappears; `has_pages` goes false).  Re-enabling Pages on a public
repository restores it, so the development repository has to stay public and
the privacy is provided by a gate in front of the pages:

* `build_site.py` writes `login.html` for the development build and injects a
  blocking script into the `<head>` of every page.  Without the token the
  visitor is redirected to the login page before anything is drawn.
* the password is read from `data/.dev_gate_password` (gitignored) or from
  `$DEV_GATE_PASSWORD`; only its **SHA-256 hash** reaches the published
  files, so the password itself is never published.
* `push_to_github.sh` refuses to publish the development copy without a
  password.
* the operational site is **never** gated - the build only writes the login
  page when `SITE_DEV=1`, and it removes a stale one otherwise.

The gate is a client-side check, so it stops a reader, not a determined
scraper: the chart PNGs are still reachable by their direct URL and the
repository's contents are public.  For true repository-level privacy the
account needs GitHub Pro (private repositories get Pages), or the site has
to be served from the owner's own server behind basic auth.
