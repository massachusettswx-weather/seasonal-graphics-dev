"""Draw the polar-cap time-height section for a seasonal model.

The figure is the same shape as the reference: a time-height section of the
polar cap (60-90N) normalised geopotential height anomaly, with the ERA5
analysis on the left of the "forecast starts" line and the model's own
forecast on the right, running to the end of the model's run.

Inputs:
  data/era5_polarcap_profiles.npz  the ERA5 polar-cap series from ARCO
                                   (the zonal mean at every cap latitude)
  data/polar_cap_recent.npz        the ERA5 analysis just before the init
  data/polar_model_z.json          the model's daily polar-cap series
  data/polar_cap_clim.npz          the climatology, if it has been built
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

import polar_rebase  # noqa: E402
from polar_cap import (CAP_N, CAP_S, G0, LEVELS, build_climatology,  # noqa: E402
                       daily_climate, fit_subtitle, load_clim_native,
                       load_climatology, normalise, plot_section)
from ecmwf_credit import credit_for_polar  # noqa: E402

OUT = os.path.join(HERE, "output", "polar_cap")
PROFILES = os.path.join(DATA, "era5_polarcap_profiles.npz")
RECENT = os.path.join(DATA, "polar_era5_recent.npz")
# NOAA's CORe reanalysis, which the section is measured with: the ERA5 in
# ARCO's own store is about 600 m too low at 10 hPa over the polar cap.
RECENT_CORE = os.path.join(DATA, "polar_core_recent.npz")
MODEL_CACHE = os.path.join(DATA, "polar_model_z.json")
# NOAA's CORe at 3-hourly resolution - the same product as the daily file
# (the daily file's day's mean IS the mean of the day's eight 3-hourly
# analyses), so the reanalysis half can be drawn at an INSTANT and not at
# a day's mean.  That makes the handover with the model's forecast a
# like-for-like comparison instead of a mix of two different times.
CORE3H = os.path.join(DATA, "polar_core_3hourly.json")
# a model's OWN analysis of its init, when the product serves one (the
# GEFS does: lead f000).  This is the segment that shows the reanalysis
# and the model at the same instant.
ANALYSIS_CACHE = os.path.join(DATA, "polar_analysis_%s_%s.json")
# the EC46 is a separate product and lives in its own file
EC46_CACHE = os.path.join(DATA, "polar_ec46_z.json")


def cache_for(tag):
    """The file that holds a system's own daily polar-cap series."""
    return EC46_CACHE if tag == "ec46" else MODEL_CACHE


def load_core_3h():
    """The CORe at 3-hourly resolution -> {stamp: {level: value}}."""
    if not os.path.exists(CORE3H):
        return {}
    try:
        return json.load(open(CORE3H))
    except Exception:                               # noqa: BLE001
        return {}


def load_model_analysis(tag, digits=None):
    """A model's own analysis of ITS OWN run, when the product serves one.

    The file carries the run it belongs to (the date and the hour), so a
    chart never borrows another cycle's analysis.

    -> {"date": "20261122", "hour": "00", "mean": {level: value}} or {}
    """
    paths = []
    if digits:
        paths.append(ANALYSIS_CACHE % (tag, digits[:10]))
    try:
        for name in sorted(os.listdir(DATA)):
            if name.startswith("polar_analysis_%s_" % tag):
                paths.append(os.path.join(DATA, name))
    except Exception:                               # noqa: BLE001
        pass
    for path in paths:
        if not os.path.exists(path):
            continue
        try:
            rec = json.load(open(path))
        except Exception:                           # noqa: BLE001
            continue
        if digits and not (str(rec.get("date")) == digits[:8]
                           and str(rec.get("hour")) == digits[8:10]):
            continue
        if rec.get("mean"):
            return rec
    return {}


def core_at(three, stamp, levels):
    """The CORe's values at one 3-hourly stamp, in the level order."""
    rec = three.get(stamp) or {}
    if not rec:
        return None
    out = []
    for l in levels:
        v = rec.get(str(l))
        if v is None:
            return None
        out.append(float(v))
    return out
CLIM = os.path.join(DATA, "polar_cap_clim.npz")
# the climatology in the ARCO NATIVE store's own convention.  It is NOT
# used: that store mutes the stratospheric variability (the January 2013
# sudden warming comes out at -0.2 sigma there against +2.1 sigma in the
# reduced store and in the seasonal models), so a climatology built from
# it would misstate every anomaly.  It is kept only for the record.
CLIM_NATIVE = os.path.join(DATA, "polar_cap_clim_native.npz")
# the climatology in the CDS's own native convention - the one that
# matches the reanalysis the chart draws.  It is preferred over the
# daily one whenever it is there; see fetch_polar_clim_monthly.py.
CLIM_MONTHLY = os.path.join(DATA, "polar_cap_clim_monthly.npz")
# the climatology built from the CDS DAILY reanalysis - the 15th of each
# month of 1991-2020, on the same product and the same grid as the
# reanalysis half.  This is the one the chart is measured against:
# the ARCO native store mutes the stratospheric variability (its October
# sigma at 10 hPa is 710 m2/s2 where the real ERA5's is about 930), and
# an anomaly divided by a sigma that is too small comes out too big - the
# deep blue on the left of the chart was the climate, not the atmosphere.
# The CDS MONTHLY means are not the answer either: they come out about
# 11,000 m2/s2 colder in the stratosphere than both ARCO stores and than
# the models, and their sigma is smaller still.
CLIM_CDSDAILY = os.path.join(DATA, "polar_cap_clim_cdsdaily.npz")
# the climate built from NOAA's CORe reanalysis: the same product as the
# reanalysis half, and CORe assimilates no satellite radiances, so its
# record has no jumps at the satellite transitions - which is what a
# 1991-2020 climatology must not have.
CLIM_CORE = os.path.join(DATA, "polar_cap_clim_core.npz")

# How many days of ERA5 analysis to show before the forecast starts.
#
# 15 Nov 2026: the user asked for the LAST 15 DAYS of ERA5 before the
# forecast and no more.  The 90-day window that was here before made the
# reanalysis half of the section look like a cold bias that ran on for
# months, and it buried the forecast - the chart is about the forecast.
ANA_DAYS = 15


def load_clim_monthly(path=None):
    """The monthly climatology -> (months, levels, mean, sigma), or None."""
    path = path or CLIM_MONTHLY
    if not os.path.exists(path):
        return None
    try:
        d = np.load(path, allow_pickle=True)
    except Exception:
        return None
    if "mean" not in d:
        return None
    return ([int(x) for x in d["months"]], [int(x) for x in d["levels"]],
            np.asarray(d["mean"], float), np.asarray(d["sigma"], float))


def normalise_monthly(times, values, levels, clim):
    """The anomaly against the monthly climatology, put on the day.

    The monthly climate is the scale a seasonal forecast is judged
    against, and it is also the scale that does not blow the summer up:
    the day to day spread of the polar cap in July is a few tens of
    metres, so a daily standard deviation there is meaningless.

    The monthly means are interpolated onto the days of the series, so the
    anomaly does not step at every month boundary.
    """
    months, clevels, cmean, csigma = clim
    cidx = {l: i for i, l in enumerate(clevels)}
    cols = [cidx[l] for l in levels if l in cidx]
    keep = [k for k, l in enumerate(levels) if l in cidx]
    if len(cols) != len(levels):
        print("   the climatology carries %d of the %d levels" % (len(cols),
                                                                 len(levels)))
        return values - values, values - values
    mmean, msig = daily_climate(times, months, cmean[:, cols], csigma[:, cols])
    anom = values - mmean
    with np.errstate(invalid="ignore", divide="ignore"):
        norm = np.where(msig > 0, anom / msig, np.nan)
    return anom, norm


def cap_mean(profiles, lat, levels):
    """The polar-cap zonal mean from the per-latitude profiles.

    profiles: (n, nlev, nlat) the zonal mean at each cap latitude
    -> (n, nlev)

    The band edge is compared with a tolerance: ARCO stores 60N as
    59.999999999999986, and an exact test drops the bottom row of the cap.
    """
    inside = (lat >= CAP_S - 1e-6) & (lat <= CAP_N + 1e-6)
    w = np.cos(np.deg2rad(lat[inside]))
    p = np.asarray(profiles, float)[:, :, inside]
    return (p * w[None, None, :]).sum(axis=2) / w.sum()


def build_clim():
    """The ERA5 profiles -> the per-calendar-day mean and sigma."""
    d = np.load(PROFILES, allow_pickle=True)
    times = [str(t) for t in d["times"]]
    lat = d["lat"].astype(float)
    # the latitudes are the stored indices; recover their values from the
    # ARCO grid so the weights are right
    import fetch_polar_era5_arco as FA
    full_lat = FA.latitude()
    lat = full_lat[lat.astype(int)]

    vals = cap_mean(d["values"], lat, LEVELS)
    np.savez_compressed(os.path.join(DATA, "era5_polarcap_z.npz"),
                        times=np.array(times), levels=np.array(LEVELS),
                        values=vals)
    return build_climatology(os.path.join(DATA, "era5_polarcap_z.npz"), CLIM)


def load_recent():
    """The reanalysis in front of the forecast -> (times, values, levels).

    The file is checked for signs of being synthetic: the polar-cap mean
    geopotential height is a positive number of a few hundred thousand m2/s2
    at 10 hPa, so a file whose 10 hPa values are near zero, or that holds
    fewer days than the window, is refused rather than drawn.

    CORe comes first: the ERA5 in ARCO's own store is about 600 m too low
    at 10 hPa over the polar cap (it is ARCO's own vertical interpolation,
    and the ECMWF's own IFS analysis and NOAA's GEFS both disagree with it),
    so the reanalysis half is measured with NOAA's CORe reanalysis, which
    needs no queue and agrees with the models.  The ERA5 file is the
    fallback.
    """
    for path, name in ((RECENT_CORE, "CORe"), (RECENT, "ERA5")):
        if not os.path.exists(path):
            continue
        d = np.load(path, allow_pickle=True)
        times = [str(t) for t in d["times"]]
        vals = np.asarray(d["values"], float)
        levels = [int(x) for x in (d["levels"] if "levels" in d else LEVELS)]
        if len(times) < 20:
            # too few days to draw a section: the reanalysis half is simply
            # left out.  It must NOT raise, or a partly fetched file would
            # stop the whole site from being published.
            print("   the recent %s holds only %d days - the section is "
                  "drawn without the reanalysis half" % (name, len(times)))
            return [], np.zeros((0, len(LEVELS))), {}
        i10 = levels.index(10) if 10 in levels else 0
        if not np.all(np.isfinite(vals[:, i10])) or vals[:, i10].max() < 1e5:
            raise ValueError("the recent %s file does not hold real polar-cap "
                             "geopotential heights (the 10 hPa values are %s)"
                             % (name, vals[:, i10][:3]))
        return times, vals, {"levels": levels, "name": name}
    return [], np.zeros((0, len(LEVELS))), {}


def load_series(path, tag):
    """-> (times, values (n, nlev), levels) for one model's daily series.

    The same guard as the ERA5 side: the model's polar-cap mean
    geopotential height is a positive number of a few hundred thousand
    m2/s2 at 10 hPa, so a file of zeros or noise is refused rather than
    drawn.
    """
    if not os.path.exists(path):
        return None, None, []
    d = json.load(open(path))
    rec = d.get(tag)
    if not rec:
        return None, None, []
    times = list(rec["times"])
    vals = np.array(rec["values"], float)
    levels = [int(x) for x in (rec.get("levels") or LEVELS)]
    order = np.argsort(times)
    times = [times[i] for i in order]
    vals = vals[order]
    # one value per calendar day.  The seasonal and the GEFS products are
    # published at 12Z, but the ECMWF's sub-seasonal runs are at 00Z, so the
    # hour is not the rule - the day is.  The earliest value of each day is
    # the one that is kept.
    seen = {}
    for i, t in enumerate(times):
        seen.setdefault(t[:10], i)
    keep = sorted(seen.values())
    times = [times[i] for i in keep]
    vals = vals[keep]
    if len(times) < 3:
        # three days is the least that shows a trend; a section with fewer
        # than that is not worth drawing
        return None, None, []
    i10 = levels.index(10) if 10 in levels else 0
    if not np.all(np.isfinite(vals[:, i10])) or vals[:, i10].max() < 1e5:
        raise ValueError("the %s series does not hold real polar-cap "
                         "geopotential heights (the 10 hPa values are %s)"
                         % (tag, vals[:, i10][:3]))
    return times, vals, levels


# the short name of each product, for the descriptor and the panel labels
SHORT_NAME = {"gefsv12": "GEFSv12", "ecmwf-seas5": "SEAS5", "ec46": "EC46"}


def main(tag="ecmwf-seas5", label="ECMWF SEAS5", short=None,
         rebase="forecast"):
    # `rebase` says how the forecast half is put on the reanalysis's scale:
    # "forecast" measures the forecast against the model's OWN climate and
    # leaves the reanalysis on the observed one; "both" measures the two
    # halves against the model's own climate, so the forecast starts exactly
    # where the analysis ends.
    # `short` is the name the DESCRIPTOR line uses, when the title's name is
    # too long for it (the GEFS's title carries "(35-day extended)")
    # the name the DESCRIPTOR and the panel labels use.  It is a CONSTANT
    # per product, so every caller gets it - the narrow publisher draws the
    # GEFSv12 with the long product name and no short one, and the panel
    # labels then ran into each other.
    short = short or SHORT_NAME.get(tag) or label
    # 1. the climatology.  The one that comes first is the one built from
    # the CDS DAILY reanalysis: the same product and the same grid as the
    # reanalysis half, with the real ERA5's spread.  The ARCO native store
    # comes next (it mutes the stratospheric variability), the CDS monthly
    # means after that, and the reduced store's daily climate last.
    clim = load_clim_monthly(CLIM_CDSDAILY)
    if clim is not None:
        kind = "cds-daily"
    else:
        clim = load_clim_monthly(CLIM_CORE)
    if clim is not None:
        kind = "core"
    else:
        nat = load_clim_native()
        if nat is not None:
            clim = nat[0]
            kind = "native"
        else:
            clim_m = load_clim_monthly()
            if clim_m is not None:
                clim = clim_m
                kind = "monthly"
            else:
                if not os.path.exists(CLIM):
                    if not os.path.exists(PROFILES):
                        print("   no ERA5 polar-cap profiles yet")
                        return
                    build_clim()
                clim = load_climatology(CLIM)
                kind = "daily"

    # 2. the analysis (the recent past, up to the model's init)
    rt, rv, d_recent = load_recent()

    # 3. the model's own forecast
    mt, mv, ser_levels = load_series(cache_for(tag), tag)
    if mt is None:
        print("   no series for %s yet" % tag)
        # a chart left over from an earlier build would be published with
        # no data behind it, so it goes
        stale = os.path.join(OUT, "polar_cap_%s.png" % tag)
        if os.path.exists(stale):
            os.remove(stale)
            print("   the stale chart removed: %s" % stale)
        return None

    # the record behind it: the run time and the size of the ensemble
    try:
        _all = json.load(open(cache_for(tag)))
    except Exception:
        _all = {}
    _rec = _all.get(tag) or {}
    members = _rec.get("members")
    run = str(_rec.get("run") or "")
    # a sub-seasonal run is a different kind of product from a seasonal one,
    # and the chart has to say which it is
    sub_seasonal = bool(mt) and len(mt) <= 90
    kind_word = "sub-seasonal" if sub_seasonal else "seasonal"
    freq = _rec.get("frequency")
    run_txt = ""
    if run:
        run_txt = "%s run" % run.replace("Z", "Z")
        # a product that runs every day says so: the ECMWF's sub-seasonal
        # set is a daily run with a 48-hour delay, and a reader comparing it
        # with a 35-day GEFS needs to know it
        freq = _rec.get("frequency")
        if freq:
            run_txt += " · %s" % freq
        if members:
            run_txt += " · %s members" % members
    else:
        run_txt = "%s members" % members if members else ""

    # the levels actually present: the seasonal archive carries all twelve
    # of the reference's levels, but a series built from another source may
    # not, and the climatology has to be subset to match
    levs = [l for l in LEVELS if l in list(ser_levels or LEVELS)]
    if not levs or mv.shape[1] != len(levs):
        print("   the %s series carries %d levels, which do not match the "
              "climatology" % (tag, mv.shape[1]))
        return

    # 4. join them on the calendar day
    rday = {t[:10]: i for i, t in enumerate(rt)}
    mday = {t[:10]: i for i, t in enumerate(mt)}

    first = mt[0][:10]
    # the ERA5 half may carry a different level set from the forecast
    # (the ERA5 reanalysis product serves the same twelve levels, but a
    # series built from another source may not), so the section is drawn on
    # the levels BOTH sides have
    rlevs = [int(x) for x in (d_recent.get("levels") if d_recent else LEVELS)]
    common = [l for l in levs if l in rlevs] if rt else list(levs)
    if rt and len(common) != len(levs):
        print("   the analysis carries %d of the %d levels; the section is "
              "drawn on those" % (len(common), len(levs)))
        mcols = [levs.index(l) for l in common]
        mv = mv[:, mcols]
        levs = common

    # The reanalysis ends the day before the model's init, and the model's
    # own run follows from its init.  The two halves therefore meet exactly
    # at the run's start, and no day is drawn twice.
    ana_days = sorted(d for d in rday if d < first)[-ANA_DAYS:]
    fc_days = sorted(mday)

    # The clock hour the model's own points are on - 12Z for the GEFS and
    # the SEAS5, 00Z for the EC46.  The reanalysis is drawn at the SAME
    # clock hour, out of the 3-hourly CORe tree, so the two halves are
    # like for like: the daily file holds a day's MEAN (stepRange 0-21),
    # and comparing that with an instant 25 hours later is what made the
    # handover look like nothing at all.
    clock = (mt[0][11:13] if len(mt[0]) > 11 else "12")
    three = load_core_3h()
    # The reanalysis half is drawn at the model's clock hour out of the
    # 3-hourly CORe tree.  If the tree does not cover the window yet, the
    # pull is made HERE: it needs no key and no queue, and without it the
    # handover would again compare a day's mean with an instant.
    if ana_days:
        need = [d.replace("-", "") + clock for d in ana_days]
        if any(x not in three for x in need):
            try:
                import fetch_polar_core_3hourly as F3
                print("   the 3-hourly CORe is not covering the window - "
                      "pulling it now")
                three = F3.ensure([d.replace("-", "") for d in ana_days], levs)
            except Exception as e:                   # noqa: BLE001
                print("   the 3-hourly CORe could not be pulled (%s) - the "
                      "section is drawn on the daily file" % str(e)[:70])
    ana_vals = None
    n_three = 0
    if ana_days:
        rcols = [rlevs.index(l) for l in levs]
        rows = []
        for d in ana_days:
            hit = core_at(three, d.replace("-", "") + clock, levs)
            if hit is None:
                break
            rows.append(hit)
        if len(rows) == len(ana_days):
            ana_vals = np.array(rows, float)
            n_three = len(rows)
        else:
            # the 3-hourly tree does not cover every day of the window
            # yet: the whole half stays on the one basis it has
            ana_vals = rv[[rday[d] for d in ana_days]][:, rcols]

    # THE MODEL'S OWN ANALYSIS, when the product serves one (the GEFS
    # does, at lead f000).  It is the segment the reference site calls
    # "Past Days": the model's own value of the atmosphere, standing
    # between the reanalysis and the forecast, so the reader can see the
    # two of them at the same instant instead of guessing where the
    # reanalysis stops.
    digits = "".join(ch for ch in run if ch.isdigit()) if run else ""
    ma = load_model_analysis(tag, digits or None)
    # THE MODEL'S OWN ANALYSIS.  The GEFS serves one (lead f000); the
    # products that do not are said so on the chart.  When the run's own
    # analysis is not on disk yet, it is pulled here - it needs no key and
    # no queue.
    if not ma.get("mean") and tag == "gefsv12" and len(digits) >= 10:
        try:
            import subprocess
            print("   the model's own analysis is not on disk - pulling it")
            subprocess.run([sys.executable,
                            os.path.join(HERE, "tools", "fetch_gefs_analysis.py"),
                            digits[:8], digits[8:10]],
                           cwd=HERE, timeout=2400,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ma = load_model_analysis(tag, digits)
        except Exception as e:                       # noqa: BLE001
            print("   the model's own analysis could not be pulled (%s)"
                  % str(e)[:70])
    ma_vals = None
    ma_day = None
    if ma.get("mean") and run:
        digits = "".join(ch for ch in run if ch.isdigit())
        if digits[:8] == str(ma.get("date")) and digits[8:10] == str(ma.get("hour")):
            row = []
            for l in levs:
                v = (ma.get("mean") or {}).get(str(l))
                if v is None:
                    row = None
                    break
                row.append(float(v))
            if row:
                ma_vals = row
                ma_day = "%s-%s-%s %s" % (str(ma["date"])[:4], str(ma["date"])[4:6],
                                          str(ma["date"])[6:8], ma["hour"])

    days = ana_days + ([ma_day] if ma_vals is not None else []) + fc_days
    parts = []
    if ana_vals is not None:
        parts.append(ana_vals)
    if ma_vals is not None:
        parts.append(np.array([ma_vals], float))
    parts.append(mv[[mday[d] for d in fc_days]])
    values = np.vstack(parts)
    split = len(ana_days) + (1 if ma_vals is not None else 0)
    split2 = len(ana_days) if ma_vals is not None else None

    # where "now" falls, so the reader can tell the model's past days from
    # the days it is still forecasting
    today = None
    import datetime as _dt
    _now = _dt.date.today().isoformat()
    for i, d in enumerate(days):
        if d <= _now:
            today = i
    if today is not None and split and today < split:
        today = None

    rebase_txt = ""
    if kind in ("monthly", "native", "core", "cds-daily"):
        cmonths, clevs, cmean, csigma = clim
        keep = [clevs.index(l) for l in levs]
        cmean = cmean[:, keep]
        csigma = csigma[:, keep]
        # A SEASONAL model's mean state is not the observed climate - the
        # SEAS5's own climate sits about 5,000 m2/s2 below the observed one
        # by the far end of its run, and the June sigma of the observed
        # climate is only 429 m2/s2 there, so that offset was drawn as
        # -4 sigma of a cold stratosphere when it is the model's own mean
        # state and nothing to do with the forecast.
        #
        # The forecast is therefore measured against the model's OWN
        # hindcast climate and added back to the observed one.  The
        # reanalysis half keeps the observed climate as its reference, so
        # the reader still sees the analysis on the scale the rest of the
        # site quotes.
        corr, note = polar_rebase.correction(
            days, levs, {int(m): cmean[i] for i, m in enumerate(cmonths)},
            cmonths, mode=rebase, run=run)
        if corr is not None:
            values = values.copy()
            if rebase == "both":
                values[:] = values - corr
            else:
                values[split:] = values[split:] - corr[split:]
            rebase_txt = " · " + note
        anom, norm = normalise_monthly(days, values, levs,
                                       (cmonths, levs, cmean, csigma))
        # THE HANDOVER, AT THE SAME INSTANT.  What the reader wants to know
        # is whether the reanalysis and the model agree, and that can only
        # be asked at one instant: the CORe's own value at the model's
        # first point's hour, against the model's own value there.
        hand_txt = ""
        seam_col = None
        lev10 = 10 if 10 in levs else (levs[0] if levs else None)
        if lev10 is not None and fc_days:
            c10 = levs.index(lev10)
            if ma_vals is not None:
                hd_day = ma_day[:10]
                hd_val = float(ma_vals[c10])
                hd_stamp = "%s%s" % (ma["date"], ma["hour"])
            else:
                hd_day = fc_days[0]
                hd_val = float(mv[0, c10])
                hd_stamp = fc_days[0].replace("-", "") + clock
            core_v = (three.get(hd_stamp) or {}).get(str(lev10))
            if core_v is not None:
                _, hsig = daily_climate([hd_day], cmonths,
                                        cmean[:, [c10]], csigma[:, [c10]])
                if float(hsig[0, 0]) > 0:
                    dsig = (hd_val - float(core_v)) / float(hsig[0, 0])
                    # the number goes on the seam itself, not in the
                    # caption: it belongs where the reader is looking
                    hand_txt = ("model \u2212 CORe: %+.2f \u03c3" % dsig)
                    if ma_vals is not None:
                        seam_col = split2
                    else:
                        seam_col = split
    else:
        cdays, clevs, cmean, csigma = clim
        keep = [clevs.index(l) for l in levs]
        anom, _sig = normalise(days, values, levs,
                               (cdays, levs, cmean[:, keep], csigma[:, keep]))
    # The field is the NORMALISED anomaly: the geopotential height anomaly
    # in standard deviations of the ERA5 1991-2020 climatology.  The
    # reanalysis and the forecast are measured against the same climate, so
    # the two halves of the section are directly comparable.
    init_day = fc_days[0] if fc_days else ""
    end_day = fc_days[-1] if fc_days else ""
    nlev = len(levs)
    lev_txt = "%d-%d" % (min(levs), max(levs))
    title = ("%s · Polar Cap (60-90°N) Normalized Geopotential Height Anomaly"
             % label)
    clim_txt = {"core": "CORe 1991-2020 climatology",
                "cds-daily": "ERA5 1991-2020 climatology",
                "native": "ERA5 1991-2020 climatology",
                "monthly": "ERA5 1991-2020 monthly climatology",
                "daily": "ERA5 1991-2020 climatology"}[kind]
    ana_name = (d_recent or {}).get("name") or "ERA5"
    # The descriptor is fitted to the figure: the parts that can be given up
    # are the level count (the y axis labels the levels) and the run time
    # (the init date is on the chart already).  What cannot be given up is
    # the climate the anomaly is measured against - and, for a model that is
    # re-based, the note that says so.
    parts = []
    if ana_days:
        # the reanalysis is drawn at an instant (the 3-hourly CORe at the
        # model's own clock hour) or at a day's mean - the caption says
        # which, because the two are not the same thing
        basis = ("%sZ, 3-hourly" % clock if n_three == len(ana_days)
                 else "daily means")
        parts.append(("%d days of %s reanalysis (%s)"
                       % (len(ana_days), ana_name, basis), False))
    parts.append(("the %s forecast from %s to %s"
                  % (short, init_day, end_day), False))
    if members:
        parts.append(("%s members" % members, True))
    if run:
        parts.append(("%s run" % run.replace("Z", "Z"), True))
    if freq:
        parts.append((str(freq), True))
    parts.append(("%d levels (%s hPa)" % (nlev, lev_txt), True))
    parts.append((clim_txt, False))
    if rebase_txt:
        parts.append((rebase_txt.strip(" ·"), False))
    subtitle = fit_subtitle(parts)
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "polar_cap_%s.png" % tag)
    plot_section(days, norm, levs, p, title, subtitle,
                 split=split if split else None,
                 split2=split2,
                 middle_label=("%s analysis" % short) if ma_vals is not None else None,
                 seam_note=hand_txt or None, seam_note_col=seam_col,
                 credit=credit_for_polar(tag),
                 analysis_label=("%s reanalysis" % ana_name) if ana_days else None,
                 forecast_label="%s %s forecast" % (
                     short, "sub-seasonal" if sub_seasonal else "seasonal"),
                 today=today)
    print("   the figure: %s" % p)
    return p


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "ecmwf-seas5"
    label = sys.argv[2] if len(sys.argv) > 2 else "ECMWF SEAS5"
    short = sys.argv[3] if len(sys.argv) > 3 else None
    rebase = sys.argv[4] if len(sys.argv) > 4 else "forecast"
    main(tag, label, short, rebase)
