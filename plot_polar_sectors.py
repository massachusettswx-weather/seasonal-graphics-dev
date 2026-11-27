"""Draw the polar cap split into two sectors: the North Pacific and the
North Atlantic, 60-90N.

The same field as the polar-cap section - the geopotential height anomaly in
metres against the 1991-2020 climate - but over one longitude sector at a
time, because the Atlantic and the Pacific do not warm together and the
polar-cap mean hides the difference between them.

Inputs:
  data/polar_model_z.json     the model's daily polar-cap series, with the
                               sector means under "sectors"
  data/polar_cap_clim_monthly.npz
                               the monthly climate, with the sector climate
                               under "sector_data"

    python3 plot_polar_sectors.py <tag> <label>
"""

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

import polar_rebase  # noqa: E402
from polar_cap import (G0, SECTOR_LABELS, daily_climate,  # noqa: E402
                       fit_subtitle, load_clim_native, plot_sector_sections)
from ecmwf_credit import credit_for_polar  # noqa: E402

OUT = os.path.join(HERE, "output", "polar_cap")
MODEL_CACHE = os.path.join(DATA, "polar_model_z.json")
CLIM_MONTHLY = os.path.join(DATA, "polar_cap_clim_monthly.npz")
# the climatology built from the CDS DAILY reanalysis: the same product and
# grid as the reanalysis half, with the real ERA5's spread.  The ARCO native
# store mutes the stratospheric variability, so a sector measured against it
# comes out too large; see plot_polar_cap.py.
CLIM_CDSDAILY = os.path.join(DATA, "polar_cap_clim_cdsdaily.npz")
# the climate built from NOAA's CORe reanalysis - the same product the
# reanalysis half is measured with
CLIM_CORE = os.path.join(DATA, "polar_cap_clim_core.npz")
# the reanalysis the section is measured with, and its sector means
RECENT_CORE = os.path.join(DATA, "polar_core_recent.npz")
RECENT_ERA5 = os.path.join(DATA, "polar_era5_recent.npz")
# the EC46 keeps its own file
EC46_CACHE = os.path.join(DATA, "polar_ec46_z.json")
# so does the EPS - the medium-range ensemble, which is its own product
EPS_CACHE = os.path.join(DATA, "polar_eps_z.json")

# How many days of analysis to show before the forecast starts - the same
# fifteen the cap section shows, so the two charts line up.
ANA_DAYS = 15


def cache_for(tag):
    if tag == "ec46":
        return EC46_CACHE
    if tag == "eps":
        return EPS_CACHE
    return MODEL_CACHE


def load_sector_clim():
    """-> {sector: {month: (mean, sigma)}}, or None."""
    # the climate built from the CDS DAILY reanalysis comes first: the same
    # product as the reanalysis half, and the real ERA5's spread.  The ARCO
    # native store mutes the stratospheric variability; the CDS monthly
    # means come out about 11,000 m2/s2 colder in the stratosphere.
    for path in (CLIM_CDSDAILY, CLIM_CORE, CLIM_MONTHLY):
        if not os.path.exists(path):
            continue
        d = np.load(path, allow_pickle=True)
        if "sector_data" not in d or "levels" not in d:
            continue
        out = {}
        for entry in d["sector_data"]:
            for name, months in entry.items():
                out[name] = {int(m): (np.array(v["mean"], float),
                                      np.array(v["sigma"], float))
                             for m, v in months.items()}
        if out:
            return out, [int(x) for x in d["levels"]]
    nat = load_clim_native()
    if nat is not None and nat[1]:
        return nat[1], [int(x) for x in (nat[0][1] if nat[0] else [])]
    return None, []


def load_recent_sectors():
    """The reanalysis's own sector means -> (times, {sector: (n, nlev)}, name).

    The CORe reanalysis is the one the cap section is measured with, and it
    carries the sector means too, so the sector panels can open with the same
    fifteen days of analysis the cap section opens with.  That is what makes
    the two graphics line up: the same days, the same levels and the same
    split line, so a reader can read a sector off one chart and find it on
    the other.
    """
    for path, product in ((RECENT_CORE, "CORe"), (RECENT_ERA5, "ERA5")):
        if not os.path.exists(path):
            continue
        try:
            d = np.load(path, allow_pickle=True)
        except Exception:
            continue
        if "sector_data" not in d:
            continue
        names = [str(x) for x in d["sector_names"]]
        sd = d["sector_data"]
        times = [str(t) for t in d["times"]]
        out = {}
        for i, sec in enumerate(names):
            out[sec] = np.asarray(sd[i], float)
        rlevs = [int(x) for x in (d["levels"] if "levels" in d else [])]
        return times, out, product, rlevs
    return [], {}, "ERA5", []


def main(tag="gefsv12", label="NOAA GEFSv12", short=None, rebase="forecast"):
    # `rebase` says how the forecast half is put on the reanalysis's scale;
    # see plot_polar_cap.py.
    # `short` is the name the DESCRIPTOR line uses, when the title's name is
    # too long for it (the GEFS's title carries "(35-day extended)")
    short = short or label
    p = cache_for(tag)
    if not os.path.exists(p):
        print("   no polar series for %s yet" % tag)
        return None
    rec = json.load(open(p)).get(tag)
    if not rec or not rec.get("sectors"):
        print("   the %s series carries no sector means" % tag)
        return None
    clim, clim_levels = load_sector_clim()
    if not clim:
        print("   no sector climate yet - the CDS monthly means are still "
              "being fetched")
        return None

    times = list(rec["times"])
    order = sorted(range(len(times)), key=lambda i: times[i])
    times = [times[i] for i in order]
    levels = [int(x) for x in (rec.get("levels") or [])]

    # The forecast, one value per calendar day: the seasonal and the GEFS
    # products are published at 12Z, but the ECMWF's sub-seasonal runs are
    # at 00Z, so the hour is not the rule - the day is.
    fc = {}
    for name, series in rec["sectors"].items():
        vals = np.array(series, float)[order]
        seen = {}
        for i, t in enumerate(times):
            seen.setdefault(t[:10], i)
        keep = sorted(seen.values())
        fc[name] = ([times[i][:10] for i in keep], vals[keep])

    # The analysis in front of it, from the same reanalysis the cap section
    # is measured with.
    rt, rv, _ana_name, rlevs = load_recent_sectors()
    rday = {}
    for i, t in enumerate(rt):
        rday.setdefault(t[:10], i)

    # THE LEVELS THE THREE SIDES SHARE.  The ECMWF's sub-seasonal EC46
    # serves ten levels and the reanalysis and the climate twelve, so the
    # chart is drawn on the ten they all have - the same rule the cap
    # section follows, so the two charts can be read against each other.
    own_levels = list(levels)
    common = [l for l in own_levels if (not rlevs or l in rlevs)
              and (not clim_levels or l in clim_levels)]
    if not common:
        print("   the %s section has no level the three sides share" % tag)
        return None
    if len(common) != len(own_levels):
        print("   the %s section is drawn on %d of the %d levels"
              % (tag, len(common), len(own_levels)))
    mkeep = [own_levels.index(l) for l in common]
    rkeep = [rlevs.index(l) for l in common] if rlevs else list(mkeep)
    levels = common
    for name in list(fc.keys()):
        fc[name] = (fc[name][0], fc[name][1][:, mkeep])
    for name in list(rv.keys()):
        rv[name] = rv[name][:, rkeep]

    first = min((v[0][0] for v in fc.values() if len(v[0])), default=None)
    ana_days = sorted(d for d in rday if first and d < first)[-ANA_DAYS:]

    # THE MODEL'S OWN ANALYSIS FILLS THE SEAM.  NOAA's CORe runs about two
    # days behind the day it is fetched for, so the reanalysis half of the
    # section stops short of the forecast; the run's own analysis - the
    # 0-hour step of the open data - closes the gap, and the chart says
    # which days are which.  See plot_polar_cap.py for the reasoning.
    ana_levels = [int(x) for x in (rec.get("levels") or [])]
    at = rec.get("analysis_times") or []
    asec = rec.get("analysis_sectors") or {}
    bridge_pairs = []
    for i, t in enumerate(at):
        d = t[:10]
        if not first or d >= first:
            continue
        if ana_days and d <= ana_days[-1]:
            continue
        if not asec or any(i >= len(as_) for as_ in asec.values()):
            continue
        bridge_pairs.append((d, i))
    bridge_pairs.sort()
    bridge = [d for d, _ in bridge_pairs]
    bridge_idx = [i for _, i in bridge_pairs]

    # the monthly climate, per sector, for each month of the series
    anom = {}
    days = None
    rebase_txt = ""
    for name in sorted(set(list(fc.keys()) + list(rv.keys()))):
        if name not in clim:
            print("   the %s sector has no climate yet" % name)
            continue
        if name not in fc or not fc[name][0]:
            continue
        fdays, fvals = fc[name]
        # the days of the whole chart: the analysis first, then the model's
        # own analysis (the seam), then the forecast
        if name in rv and ana_days:
            all_days = ana_days + bridge + fdays
            avals = rv[name][[rday[d] for d in ana_days]]
        else:
            all_days = fdays
            avals = np.zeros((0, len(levels)))
        if len(all_days) < 3:
            continue
        vals = np.vstack([avals, fvals]) if len(avals) else fvals
        if bridge and name in asec:
            # the model's own analysis, on the same levels
            bcols = [ana_levels.index(l) for l in levels]
            bvals = np.array([asec[name][i] for i in bridge_idx],
                             float)[:, bcols]
            vals = np.vstack([avals, bvals, fvals])
        # the monthly sector climate, as arrays, and then put on the days
        # of the series: a monthly climate applied to a daily series steps
        # at every month boundary and the step draws a seam across the
        # chart
        mlist = sorted(clim[name])
        ccols = ([clim_levels.index(l) for l in levels]
                 if clim_levels else list(range(len(levels))))
        mmean = np.array([np.asarray(clim[name][m][0], float)[ccols]
                          for m in mlist])
        msig = np.array([np.asarray(clim[name][m][1], float)[ccols]
                         for m in mlist])
        # A SEASONAL model's mean state is not the observed climate, and by
        # the far end of a seven-month run it is thousands of m2/s2 below it
        # - which the small summer sigma then drew as several sigma of a
        # cold stratosphere.  The forecast is therefore measured against
        # the model's OWN hindcast climate, exactly as the cap section
        # does it, so the two charts stay in step.
        corr, note = polar_rebase.correction(
            all_days, levels,
            {m: np.asarray(clim[name][m][0], float)[ccols] for m in mlist},
            mlist, sector=name, mode=rebase, run=rec.get("run") or "")
        if corr is not None:
            vals = vals.copy()
            if rebase == "both":
                vals[:] = vals - corr
            else:
                vals[len(ana_days):] = vals[len(ana_days):] - corr[len(ana_days):]
            rebase_txt = " · " + note
        daily, dsig = daily_climate(all_days, mlist, mmean, msig)
        # the anomaly is NORMALISED: the climate's own standard deviation
        # for the day, so the two sectors and every level are on one scale
        rows = [(vals[i] - daily[i]) / dsig[i] for i in range(len(all_days))]
        anom[name] = np.array(rows, float)
        days = all_days


    if not anom:
        print("   no sector series could be put against the climate")
        return None

    # the title and the descriptor
    label_txt = "%s · Polar Cap (60-90°N) by Sector" % label
    run = rec.get("run") or ""
    nmem = rec.get("members")
    # A MEDIUM-RANGE PRODUCT IS NOT A SUB-SEASONAL ONE (the owner, 27
    # November 2026): the EPS is the fifteen-day ensemble.
    product = str(rec.get("product") or "").strip().lower()
    kind_word = ("medium-range" if product == "medium-range"
                 else ("sub-seasonal" if len(times) <= 90 else "seasonal"))
    bits = []
    if run:
        # the RUN cannot be given up: the reader has to be able to say
        # which run the chart is showing
        bits.append(("%s run" % run, False))
    freq = rec.get("frequency")
    if freq:
        # the ECMWF's sub-seasonal set is a DAILY run with a 48-hour delay
        bits.append((str(freq), True))
    if nmem:
        bits.append(("%s members" % nmem, False))
    # the EPS asked for BOTH cycles of its run and pooled them day by day:
    # the chart says so, so a reader knows it is looking at two suites.
    # A single cycle - which is what the owner asked for on 27 November
    # 2026, one window for the 00Z cycle and one for the 12Z - names the
    # cycle in the run label instead.
    cycles = rec.get("cycles") or []
    if len(cycles) > 1:
        bits.append(("%s cycles pooled" % " and ".join(cycles), False))
    bits.append(("%d levels (%d-%d hPa)" % (len(levels), min(levels), max(levels)),
                 True))
    _c = ("CORe" if os.path.exists(CLIM_CORE) and not os.path.exists(CLIM_CDSDAILY)
          else "ERA5")
    bits.append(("%s 1991-2020 sector climatology" % _c, False))
    if rebase_txt:
        bits.append((rebase_txt.strip(" ·"), False))
    # the same opening the cap section has: the analysis first, then the
    # forecast, so the two charts can be read against each other
    # the forecast window, not the whole chart: the analysis days in front
    # are named separately, exactly as the cap section names them
    fc_first = fc[list(fc.keys())[0]][0][0][:10] if fc else days[0][:10]
    fc_last = fc[list(fc.keys())[0]][0][-1][:10] if fc else days[-1][:10]
    head = []
    if ana_days:
        head.append(("%d days of %s reanalysis" % (len(ana_days), _ana_name),
                     False))
    head.append(("the %s %s sector forecast from %s to %s"
                 % (short, kind_word, fc_first, fc_last), False))
    subtitle = fit_subtitle(head + bits, limit=2600.0, fig_w=17.6)

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "polar_sectors_%s.png" % tag)
    plot_sector_sections(days, anom, levels, path, label_txt, subtitle,
                         split=(len(ana_days) + len(bridge))
                         if (ana_days or bridge) else None,
                         credit=credit_for_polar(tag))
    print("   the figure: %s" % path)
    return path


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "gefsv12"
    label = sys.argv[2] if len(sys.argv) > 2 else "NOAA GEFSv12"
    short = sys.argv[3] if len(sys.argv) > 3 else None
    rebase = sys.argv[4] if len(sys.argv) > 4 else "forecast"
    main(tag, label, short, rebase)
