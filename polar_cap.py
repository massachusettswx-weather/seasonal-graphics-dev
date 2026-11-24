"""Polar cap (60-90N) geopotential height: the zonal-mean machinery.

The reference figure is a time-height section of the polar cap geopotential
height anomaly, normalised by the climatological standard deviation.  It
needs three things, and this module owns all three:

  1. the polar cap mean of the geopotential height on a set of pressure
     levels, area weighted over 60-90N (cos(lat) weights), for a set of
     times;
  2. the ERA5 1991-2020 climatology of that quantity, per calendar day, so
     the anomaly can be taken and then divided by sigma;
  3. the drawing routine that lays the result out as a time-height section
     with a pressure axis on the left and an approximate-altitude axis on
     the right.

The two data sources are the same for every model:

  * ERA5 (the analysis) comes from the CDS "ERA5 post-processed daily
    statistics on pressure levels" product, requested over the polar cap
    only, which gives daily means for the whole 1991-2020 record;
  * the forecast comes from the seasonal sub-daily archive
    ("seasonal-original-pressure-levels"), which carries geopotential on
    exactly the twelve levels the reference uses, at every 12-hourly step
    out to 215 days.

The zonal mean is taken the same way everywhere, so an ECMWF member and an
ERA5 day are directly comparable.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# the levels the C3S seasonal archive serves, in the order it serves them
LEVELS = [10, 30, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]

# the polar cap: 60N to the pole
CAP_N = 90.0
CAP_S = 60.0


# ---------------------------------------------------------------- the zonal mean
def cap_weights(lat):
    """The area weights (cos(lat)) for the polar cap band.

    The comparison is made with a tolerance: the grids this runs on store
    their latitudes as floating point, and ARCO's 60N row is
    59.999999999999986 - an exact comparison drops the bottom row of the
    cap, which shifts the mean.
    """
    lat = np.asarray(lat, float)
    w = np.cos(np.deg2rad(lat))
    inside = (lat >= CAP_S - 1e-6) & (lat <= CAP_N + 1e-6)
    return np.where(inside, w, 0.0)


def zonal_mean(field, lat):
    """The area-weighted zonal mean of a 2-D field over the polar cap.

    field: (nlat, nlon); lat: (nlat,)
    -> a single number

    The denominator is n_lon * sum(w): the polar cap is a band of latitudes
    that wraps the whole globe, so every longitude is present at every
    latitude in the band.  Getting this wrong inflates the mean by
    n_lon / n_lat_used.
    """
    w = cap_weights(lat)
    used = w > 0
    if not used.any():
        return np.nan
    nlon = field.shape[1]
    ww = w[used]
    return float((field[used, :] * ww[:, None]).sum() / (nlon * ww.sum()))


def sector_mean(field, lat, lon, lon0, lon1):
    """The area-weighted zonal mean of a 2-D field over ONE longitude sector.

    field: (nlat, nlon); lat: (nlat,); lon: (nlon,) in degrees east
    lon0 -> lon1, going east; the sector wraps if lon1 < lon0.

    The same reduction as the full cap mean, but only over the longitudes
    of the sector: the field is averaged east-west over the sector at every
    latitude of the band, and then weighted by cos(lat).
    """
    w = cap_weights(lat)
    used = w > 0
    if not used.any():
        return np.nan
    lons = np.asarray(lon, float) % 360.0
    if lon1 >= lon0:
        m = (lons >= lon0) & (lons < lon1)
    else:
        m = (lons >= lon0) | (lons < lon1)
    if not m.any():
        return np.nan
    f = field[used, :][:, m]
    ww = w[used][:, None]
    return float((f * ww).sum() / (float(m.sum()) * ww.sum()))


# The polar cap split into two sectors, so that a warming over one ocean
# can be told from a warming over the other - the Atlantic and the Pacific
# do not warm together, and the difference between them is the story.
# The sectors do not overlap and together they cover the WHOLE polar cap:
# the Pacific runs from 120E to 240E, the Arctic sector from 240E to 300E
# (the Barents and the Siberian side), the Atlantic from 300E to 60E, and
# the last wedge - 60E to 120E, the Barents Sea and the Kara Sea - closes
# the circle.  The chart used to leave 240E-300E out, and then 60E-120E
# with it, so the by-sector charts did not account for a third of the cap
# and a reader comparing a sector with the whole-cap chart had no way to
# know where the rest of the cap was.
# The two sectors the section is drawn for: the North Pacific and the
# North Atlantic, 60-90N.  The Arctic and the Barents-Kara are NOT on the
# site - they were never asked for - so the wedge between 60E and 120E is
# simply not in the by-sector charts, and the whole-cap chart is the only
# place the full 60-90N circle appears.
SECTORS = {
    "natl": (300.0, 60.0),
    "npac": (120.0, 240.0),
}
SECTOR_LABELS = {
    "natl": "North Atlantic",
    "npac": "North Pacific",
}
# the order the panels are drawn in: the Pacific first, the Atlantic second
SECTOR_ORDER = ("npac", "natl")


def read_grib_levels(path, levels=None):
    """-> (times, {level: polar cap mean geopotential height}).

    Reads a GRIB with geopotential on pressure levels and reduces each
    field to the polar cap mean.  Returns the times as ISO date strings
    (hourly resolution kept in the key) and the values in m**2 s**-2.

    An ENSEMBLE file carries every member at the same valid time and level,
    so the member values are averaged: the section shows the ensemble mean,
    and a file with one member (a control run) comes through unchanged.
    """
    times, cap, _sector = read_grib_levels_sectors(path, levels)
    return times, cap


def read_grib_levels_sectors(path, levels=None):
    """-> (times, cap, sectors).

    cap:    {time: {level: the polar cap mean}}
    sectors: {time: {sector: {level: the sector mean}}}

    The same reduction as read_grib_levels, plus the sector means, so one
    pass over the file serves both.
    """
    import eccodes
    from datetime import datetime, timedelta
    from collections import defaultdict
    acc = defaultdict(lambda: defaultdict(list))
    sacc = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                ni = int(eccodes.codes_get(gid, "Ni", 0) or 0)
                nj = int(eccodes.codes_get(gid, "Nj", 0) or 0)
                if ni and nj and v.size == ni * nj:
                    lat2d = la.reshape(nj, ni)
                    lon2d = lo.reshape(nj, ni)
                    v = v.reshape(nj, ni)
                else:
                    lats = np.unique(la)[::-1]
                    lons = np.unique(lo)
                    if v.size != lats.size * lons.size:
                        continue
                    v = v.reshape(len(lats), len(lons))
                    lat2d = np.repeat(lats[:, None], len(lons), axis=1)
                    lon2d = np.repeat(lons[None, :], len(lats), axis=0)
                lats = lat2d[:, 0]
                lons = lon2d[0, :]
                # the valid time: eccodes' own validityDate/validityTime
                # already carry the reference time plus the forecast step,
                # and they are the same for a reanalysis (12Z, step 0) and
                # for a seasonal run (the 00Z init plus the lead time).
                # Reading dataDate/dataTime/step instead puts every ERA5
                # field at 00Z and every seasonal field a whole day out.
                try:
                    vd = int(eccodes.codes_get(gid, "validityDate"))
                    vt = int(eccodes.codes_get(gid, "validityTime"))
                    valid = datetime(vd // 10000, (vd // 100) % 100, vd % 100) \
                        + timedelta(hours=vt // 100, minutes=vt % 100)
                except Exception:
                    dd = int(eccodes.codes_get(gid, "dataDate"))
                    tt = int(eccodes.codes_get(gid, "dataTime", 0) or 0)
                    st = int(eccodes.codes_get(gid, "step", 0) or 0)
                    valid = datetime(dd // 10000, (dd // 100) % 100, dd % 100) \
                        + timedelta(hours=tt // 100, minutes=tt % 100) \
                        + timedelta(hours=st)
                lev = int(eccodes.codes_get(gid, "level"))
                key = valid.strftime("%Y-%m-%d %H")
                acc[key][lev].append(zonal_mean(v, lats))
                for name, (a, b) in SECTORS.items():
                    sacc[key][name][lev].append(
                        sector_mean(v, lats, lons, a, b))
            except Exception:
                pass
            finally:
                eccodes.codes_release(gid)
    out = {t: {lev: float(np.mean(vals)) for lev, vals in d.items()}
           for t, d in acc.items()}
    sout = {t: {name: {lev: float(np.mean(vals)) for lev, vals in ld.items()}
                for name, ld in sd.items()}
            for t, sd in sacc.items()}
    times = sorted(out)
    return times, out, sout


# ---------------------------------------------------------------- the climatology
def build_climatology(clim_path, out_path=None):
    """Build the ERA5 1991-2020 polar cap climatology.

    clim_path: an npz with
        times   : (n,)   ISO "YYYY-MM-DD" daily strings
        levels  : (nlev,) the pressure levels
        values  : (n, nlev) the polar cap mean geopotential height

    Writes an npz with, per calendar day (mm-dd) and level, the mean, the
    standard deviation and the count of the 1991-2020 samples.  A month is
    given its own entry where the record is long enough.
    """
    d = np.load(clim_path, allow_pickle=True)
    times = [str(t) for t in d["times"]]
    levels = [int(x) for x in d["levels"]]
    values = np.asarray(d["values"], float)

    from collections import defaultdict
    by_md = defaultdict(list)
    for i, t in enumerate(times):
        if t[:4] in [str(y) for y in range(1991, 2021)]:
            by_md[t[5:10]].append(values[i])

    out = {}
    for md, arr in by_md.items():
        a = np.asarray(arr, float)
        good = np.isfinite(a).all(axis=1)
        a = a[good]
        if a.size == 0:
            continue
        out[md] = {
            "n": int(a.shape[0]),
            "mean": a.mean(axis=0).tolist(),
            "sigma": a.std(axis=0, ddof=1).tolist() if a.shape[0] > 1
                     else [0.0] * len(levels),
        }
    res = {"levels": np.array(levels), "days": np.array(sorted(out))}
    res["mean"] = np.array([out[m]["mean"] for m in sorted(out)], float)
    res["sigma"] = np.array([out[m]["sigma"] for m in sorted(out)], float)
    res["count"] = np.array([out[m]["n"] for m in sorted(out)], int)
    p = out_path or os.path.join(DATA, "polar_cap_clim.npz")
    np.savez_compressed(p, **res)
    return p


def load_climatology(path=None):
    """-> (days, levels, mean, sigma) with the day-of-year lookup."""
    p = path or os.path.join(DATA, "polar_cap_clim.npz")
    d = np.load(p, allow_pickle=True)
    days = [str(x) for x in d["days"]]
    return days, [int(x) for x in d["levels"]], d["mean"], d["sigma"]


def daily_climate(times, months, mean, sigma=None):
    """The monthly climate put on each day of a series.

    mean: (nmonths, ...) the monthly means; sigma the same shape.

    The monthly means are turned into a smooth cycle: each month's mean
    sits at the middle of its month and the days in between are
    interpolated.  A monthly climate applied to a daily series steps at
    every month boundary, and the step draws a vertical seam across the
    whole section - which reads as a fault in the chart rather than as a
    change in the weather.
    """
    import datetime as dt
    nmonths = len(months)
    # the middle of each month, as a day of the year.  The months are
    # counted from January, so December's mid-point lands near the end of
    # the year rather than back at 16 January.
    mid = []
    total = 0
    for m in months:
        nxt = dt.date(2001 + (m == 12), m % 12 + 1, 1)
        ndays = (nxt - dt.date(2001, m, 1)).days
        mid.append(total + (ndays + 1) / 2.0)
        total += ndays
    mean = np.asarray(mean, float)
    xs = np.array([-mid[-1] + 365.0] + mid + [365.0 + mid[0]])
    ys = np.concatenate([mean[-1:], mean, mean[:1]], axis=0)
    shape = mean.shape[1:]
    out = np.empty((len(times),) + shape, float)
    for i, t in enumerate(times):
        doy = dt.datetime.strptime(t[:10], "%Y-%m-%d").timetuple().tm_yday
        if shape:
            out[i] = np.array([np.interp(doy, xs, ys[:, k])
                               for k in range(shape[0])]).reshape(shape)
        else:
            out[i] = np.interp(doy, xs, ys)
    if sigma is None:
        return out
    return out, daily_climate(times, months, sigma)


def load_clim_native(path=None):
    """The climatology built from ARCO's native ERA5 store.

    -> (months, levels, mean, sigma) and, when the file carries them, the
    sector climate in the same shape: {sector: {month: (mean, sigma)}}.

    This is the climate the chart is measured against: the same product and
    the same grid as the reanalysis half, so the anomaly means what it
    says.  The CDS's monthly means came out about 10 K colder than the
    store in the stratosphere, which inflated every anomaly by about
    1200 m.
    """
    p = path or os.path.join(DATA, "polar_cap_clim_native_daily.npz")
    if not os.path.exists(p):
        return None
    d = np.load(p, allow_pickle=True)
    times = [str(t) for t in d["times"]]
    vals = np.asarray(d["values"], float)
    levels = [int(x) for x in d["levels"]]
    months = sorted({int(t[5:7]) for t in times})
    mean = np.zeros((len(months), len(levels)))
    sigma = np.zeros_like(mean)
    idx_of = {}
    for j, m in enumerate(months):
        idx = [i for i, t in enumerate(times) if int(t[5:7]) == m]
        idx_of[m] = idx
        mean[j] = vals[idx].mean(axis=0)
        sigma[j] = vals[idx].std(axis=0, ddof=1)
    sec = None
    if "sectors" in d:
        names = [str(x) for x in d["sector_names"]]
        arrs = d["sectors"]
        sec = {}
        for k, name in enumerate(names):
            a = arrs[k]
            if getattr(a, "dtype", None) == object and getattr(a, "ndim", 0) == 0:
                a = a.item()          # numpy saves an object array of arrays
            a = np.asarray(a, float)  # as one zero-dimensional object each
            if a.ndim == 1 and a.size == len(times) * len(levels):
                # numpy saves an object array of same-shaped arrays as one
                # flat object array; the values are all there
                a = a.reshape(len(times), len(levels))
            if a.ndim != 2 or a.shape[0] != len(times):
                continue
            sec[name] = {}
            for m in months:
                idx = idx_of[m]
                sec[name][m] = (a[idx].mean(axis=0), a[idx].std(axis=0, ddof=1))
    return (months, levels, mean, sigma), sec


def normalise(times, values, levels, clim):
    """Turn polar cap means into the normalised anomaly.

    times:  (n,)    ISO "YYYY-MM-DD" or "YYYY-MM-DD HH"
    values: (n, nlev)
    levels: (nlev,)

    The climatology is keyed by calendar day, so a value is looked up by
    its month and day.  A day with no climatological entry falls back to
    the nearest day in the same month.
    """
    days, clevels, cmean, csigma = clim
    lev_index = {l: i for i, l in enumerate(levels)}
    cidx = {l: i for i, l in enumerate(clevels)}
    mean = np.full((len(times), len(levels)), np.nan)
    sigma = np.full((len(times), len(levels)), np.nan)
    for i, t in enumerate(times):
        md = t[5:10]
        if md not in days:
            # the nearest day in the same month
            cands = [d for d in days if d[3:] == md[3:]]
            if not cands:
                cands = days
            md = min(cands, key=lambda d: abs(int(d[:2]) - int(md[:2])))
        j = days.index(md)
        for l in levels:
            if l in lev_index and l in cidx:
                mean[i, lev_index[l]] = cmean[j, cidx[l]]
                sigma[i, lev_index[l]] = csigma[j, cidx[l]]
    anom = values - mean
    with np.errstate(invalid="ignore", divide="ignore"):
        norm = np.where(sigma > 0, anom / sigma, np.nan)
    return anom, norm


# ---------------------------------------------------------------- the drawing
# The colour ladder is a diverging ramp: the site's navy through the blues
# to a pale tint, a white centre, then pale yellow into yellow, amber,
# orange and the site's own deep red.  The colours are this site's own;
# the LAYOUT is ours too - nothing here is lifted from a published figure.
#
# The field is the NORMALISED geopotential height anomaly, in standard
# deviations of the ERA5 1991-2020 climatology.  The reanalysis and the
# forecast are measured against the same climate and the same standard
# deviation, so the two halves of the section are directly comparable.
#
# The anomaly is NORMALISED - in standard deviations of the 1991-2020
# climatology - so every level is on the same footing: the stratosphere
# moves by kilometres and the troposphere by tens of metres.  The ladder
# runs to +/-5 sigma with fine steps near zero, the same shape as the
# reference's, so an ordinary day's anomaly still reads.
BREAKS = [-5, -4, -3, -2, -1.5, -1, -0.7, -0.4, -0.2,
          0.2, 0.5, 1, 1.5, 2, 3, 4, 5]
COLORS = [
    # nine blues: a saturated royal blue out to a pale tint.  The deep end
    # is a COLOURED blue, not a near-black navy - a dark, desaturated end
    # reads as a hole in the chart rather than as a strong cold anomaly.
    "#1017c4", "#101fda", "#1230ec", "#1c4cf1", "#3a77f4",
    "#5c9cf7", "#87befa", "#b2d6fb", "#d9e9fc",
    # the white centre
    "#ffffff",
    # seven warms: a bright yellow, then gold, orange, vermilion, a vivid
    # red and a deep red.  These are the saturated colours, not the dusty
    # ones - a muted ramp makes a strong anomaly look like a weak one.
    "#fff45a", "#fdc742", "#f79030", "#ee6326", "#ea4220",
    "#d52c1b", "#b22318",
]

# the house colours, the same ones the zonal-wind panels use
C_TEXT = "#1f2937"
C_MUTED = "#6b7280"
C_GRID = "#d6d3d1"
C_SPLIT = "#12263f"
C_TODAY = "#9d174d"

# the standard gravity, for turning a geopotential into a height
G0 = 9.80665

# the approximate height of the pressure levels, for the right-hand axis.
# A standard atmosphere, not a table lifted from anywhere.
def _height_km(p):
    import math
    return 0.288 * 1000.0 * math.log(1013.25 / p) / 0.0065 / 1000.0 * 10.0


def _short_date(t):
    """'13 Nov' - the full date is too wide when the run is short."""
    t = str(t)
    try:
        import datetime as _dt
        d = _dt.date.fromisoformat(t[:10])
        return "%d %s" % (d.day, ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                  "Jul", "Aug", "Sep", "Oct", "Nov",
                                  "Dec")[d.month - 1])
    except Exception:
        return t[:10]


def _alt_label(km):
    return "%d km" % round(km)


def fit_subtitle(parts, limit=1995.0, fs=9.5, fig_w=13.5, x0=0.052):
    """Join the parts of a subtitle, dropping the optional ones if it is long.

    The section figure is 2025 px wide and the descriptor has to end before
    the edge, so a long subtitle has to give something up.  The parts are
    given as (text, optional) and the optional ones are dropped from the
    right until the text fits.

    -> the subtitle
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    keep = list(parts)

    def end_px(s):
        fig = plt.figure(figsize=(fig_w, 7.0), dpi=150)
        t = fig.text(x0, 0.921, s, fontsize=fs, ha="left", va="top")
        fig.canvas.draw()
        bb = t.get_window_extent(fig.canvas.get_renderer())
        plt.close(fig)
        return x0 * fig_w * 150 + bb.width

    while True:
        s = " · ".join(p[0] for p in keep if p[0])
        if end_px(s) <= limit:
            return s
        for i in range(len(keep) - 1, -1, -1):
            if keep[i][1]:
                del keep[i]
                break
        else:
            return s


def plot_section(times, norm, levels, out_path, title, subtitle,
                 split=None, split_label="", credit=None, handle="@Massachusettswx",
                 vmax=5.0, analysis_label=None, forecast_label=None,
                 today=None, forecast_alpha=0.55):
    """Draw the time-height section.

    times:  (n,)   ISO strings
    norm:   (n, nlev) the normalised anomaly
    levels: (nlev,) the pressure levels, hPa
    split:  the index where the forecast begins, or None
    today:  the index of "now", drawn as a marker

    The layout is this site's own: a bold title and a grey descriptor line
    on the LEFT, a plain-text summary on the right, the colour bar below
    the panel and the handle bottom right.  The analysis is drawn at full
    strength and the forecast at a lighter one, so what has happened and
    what might happen are told apart at a glance.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap

    cmap = ListedColormap(COLORS)
    edges = np.array(BREAKS, float)
    norm_c = BoundaryNorm(edges, cmap.N, clip=False)

    lev = np.asarray(levels, float)
    order = np.argsort(lev)
    lev = lev[order]
    z = np.asarray(norm, float)[:, order].T      # (nlev, ntime)

    n = len(times)
    x = np.arange(n)

    # The figure is kept short and the panel is given most of it: the first
    # version of this chart carried a wide band of empty white above the
    # panel and a deep band under it, and the panel itself was squashed.
    fig_w = 13.5
    fig_h = 7.0
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor="white")
    ax = fig.add_axes([0.052, 0.148, 0.876, 0.700])
    ax.set_facecolor("white")

    # The panel is drawn in one piece.  It used to be drawn in three, each
    # with its own shading, and a contourf only fills the columns it is
    # given - so the day before the "now" line was never filled and the
    # chart carried a white stripe down it.
    #
    # The forecast side was drawn at 62% opacity over the reanalysis, which
    # laid a grey wash over the anomalies on the right of the split line and
    # made them read as weaker than they are.  Both sides are now drawn at
    # full strength: the split line and the two labels above the panel are
    # what tell the reader which half is which.
    mid = today if (today is not None and 0 < today < n) else n
    ax.contourf(x, lev, z, levels=edges, cmap=cmap,
                norm=norm_c, extend="both", alpha=1.0)

    ax.set_yscale("log")
    ax.set_ylim(1000.0, 10.0)

    # the pressure ticks
    have = set(int(v) for v in lev)
    shown = [p for p in (1000, 700, 500, 400, 300, 200, 100, 50, 30, 10) if p in have]
    ax.set_yticks(shown)
    ax.set_yticklabels(["%d" % p for p in shown], fontsize=10, color=C_TEXT)
    ax.set_ylabel("Pressure (hPa)", fontsize=11, color=C_TEXT, labelpad=8)

    # the date labels: about nine of them, and never two that overlap
    step = max(1, n // 9)
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:
        if (n - 1) - idx[-1] >= step * 0.6:
            idx.append(n - 1)
        else:
            idx[-1] = n - 1
    while len(idx) > 2:
        gaps = [(idx[i + 1] - idx[i]) for i in range(len(idx) - 1)]
        if min(gaps) >= step * 0.75:
            break
        j = int(np.argmin(gaps))
        if j == 0:
            del idx[1]
        elif j == len(gaps) - 1:
            del idx[-2]
        else:
            del idx[j + 1]
    ax.set_xticks(idx)
    ax.set_xticklabels([_short_date(times[i]) for i in idx], fontsize=9,
                        color=C_TEXT)
    ax.set_xlim(-0.5, n - 0.5)

    ax.grid(True, color=C_GRID, linestyle=(0, (1, 3)), lw=0.6, alpha=0.8)
    ax.xaxis.grid(True)
    ax.yaxis.grid(True)

    # the approximate height on the right, in this site's own thin grey
    ax2 = ax.twinx()
    ax2.set_yscale("linear")
    ax2.set_ylim(0.0, 33.0)
    hticks = [(0, 0), (8, 5), (16, 10), (24, 15), (32, 20)]
    ax2.set_yticks([t[0] for t in hticks])
    ax2.set_yticklabels([_alt_label(t[0]) for t in hticks], fontsize=9,
                        color=C_MUTED)
    ax2.set_ylabel("Approximate height", fontsize=10, color=C_MUTED,
                   labelpad=10)
    ax2.tick_params(axis="y", length=3, colors=C_MUTED)

    ax.spines["top"].set_visible(False)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#9ca3af")
        ax.spines[s].set_linewidth(0.9)
    ax2.spines["right"].set_color("#9ca3af")
    ax2.spines["right"].set_linewidth(0.9)
    ax.tick_params(length=3, colors=C_TEXT)

    # the boundary between the analysis and the forecast
    if split is not None and 0 < split < n:
        ax.axvline(split - 0.5, color=C_SPLIT, lw=1.3, ls=(0, (5, 3)),
                   zorder=6)

    # the titles: left aligned, the way the rest of the site does it
    fig.text(0.052, 0.968, title, fontsize=15.5, fontweight="bold",
             ha="left", va="top", color=C_TEXT)
    if subtitle:
        fig.text(0.052, 0.921, subtitle, fontsize=9.5, color=C_MUTED,
                 ha="left", va="top")

    # the two sides are named just above the panel
    if analysis_label and split:
        fig.text(0.056, 0.858, analysis_label, fontsize=10,
                 fontweight="bold", color=C_SPLIT, ha="left", va="bottom")
    if forecast_label:
        fig.text(0.924, 0.858, forecast_label, fontsize=10,
                 fontweight="bold", color=C_SPLIT, ha="right", va="bottom")

    # the colour bar, below the panel.  It is drawn from a clean mappable so
    # that it always shows the colours at full strength, whatever the
    # shading of the panel above.
    from matplotlib.cm import ScalarMappable
    sm = ScalarMappable(norm=norm_c, cmap=cmap)
    sm.set_array([])
    cax = fig.add_axes([0.245, 0.076, 0.48, 0.018])
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal",
                      boundaries=edges, ticks=edges[1:-1], extend="neither",
                      spacing="uniform")
    cb.ax.set_xticklabels(["%g" % e for e in edges[1:-1]], fontsize=8,
                          color=C_TEXT)
    cb.outline.set_visible(True)
    cb.outline.set_edgecolor("#c8c5c2")
    cb.outline.set_linewidth(0.8)
    cb.ax.tick_params(length=2, colors=C_TEXT)
    fig.text(0.485, 0.030, "Normalized geopotential height anomaly (\u03c3)",
             fontsize=10.5, ha="center", va="center", fontweight="bold",
             color=C_TEXT)

    if credit:
        fig.text(0.985, 0.007, credit, fontsize=6.0, color="#777777",
                 ha="right", va="bottom", linespacing=1.35)
    if handle:
        fig.text(0.985, 0.032, handle, fontsize=9.5, fontweight="bold",
                 color=C_TEXT, ha="right", va="bottom")

    fig.savefig(out_path, dpi=150, facecolor="white")
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    print("the levels:", LEVELS)
    print("the module is meant to be imported")


def plot_domain_map(ax):
    """Draw the domains on a REAL map: the polar cap and the two sectors.

    The North Pole is at the centre, Greenwich at the bottom, so the Pacific
    sector (120E-240E) sits at the top of the map and the Atlantic sector
    (300E-60E) at the bottom - the same arrangement as the panels beside it.
    The azimuthal-equidistant projection is scaled so that 30N is the outer
    ring of the map, which leaves the polar cap itself filling the middle
    half of it.

    The map is drawn from Natural Earth's 1:50m land outline (committed to
    the repo as data/ne_50m_land.geojson, so the figure never depends on a
    download at build time): the reader can see that the Pacific sector is
    the one over the Bering Sea and the Atlantic sector the one over the
    Greenland Sea, which is the whole point of splitting the cap.
    """
    import matplotlib.patches as mpatches
    from matplotlib.collections import PolyCollection

    cap_r = (90.0 - 60.0) / 60.0            # the 60N edge, as a fraction
    edge_r = (90.0 - 30.0) / 60.0           # the outer ring of the map

    def pt(lon, lat):
        r = (90.0 - lat) / 60.0
        a = np.radians(lon)
        return r * np.sin(a), -r * np.cos(a)

    # the sea, and then the land on top of it
    ocean = mpatches.Circle((0, 0), edge_r, facecolor="#eef3f7",
                             edgecolor="none", zorder=1)
    ax.add_patch(ocean)

    land = _land_polygons()
    if land is not None:
        pc = PolyCollection(land, facecolors="#d9d3c6",
                            edgecolors="#b3aa9a", linewidths=0.35, zorder=2)
        pc.set_clip_path(ocean)
        ax.add_collection(pc)

    # the sectors, over the map, so the geography shows through them
    for name, colour in (("npac", "#f4b740"), ("natl", "#3d7fd1")):
        lon0, lon1 = SECTORS[name]
        ax.add_patch(_wedge(lon0, lon1, cap_r, colour, alpha=0.62))

    # the graticule: the latitude circles and the longitude spokes
    for lat in (70.0, 80.0):
        r = (90.0 - lat) / 60.0
        th = np.linspace(0, 2 * np.pi, 361)
        ax.plot(r * np.sin(th), -r * np.cos(th), color="#8b9199",
                lw=0.7, ls=(0, (2, 3)), zorder=4)
    for lon in range(0, 360, 30):
        x0, y0 = pt(lon, 60.0)
        x1, y1 = pt(lon, 90.0)
        ax.plot([x0, x1], [y0, y1], color="#8b9199", lw=0.6,
                ls=(0, (2, 3)), zorder=4)
    # the edge of the cap, drawn solid
    th = np.linspace(0, 2 * np.pi, 361)
    ax.plot(cap_r * np.sin(th), -cap_r * np.cos(th), color="#4b5563",
            lw=1.2, zorder=6)
    # the outer ring of the map, at 30N
    ax.add_patch(mpatches.Circle((0, 0), edge_r, facecolor="none",
                                  edgecolor="#9aa0a6", lw=0.9, zorder=5))

    # the sectors, named on the map
    import matplotlib.patheffects as pe
    halo = [pe.withStroke(linewidth=2.2, foreground="white")]
    for name, colour in (("npac", "#7a5200"), ("natl", "#123f77")):
        lon0, lon1 = SECTORS[name]
        mid = (lon0 + (lon1 - lon0 if lon1 > lon0 else lon1 + 360 - lon0) / 2.0)
        # the name on the map is the SHORT one: the full label is long
        # enough to spill out of the cap and over the map's edge.
        short = {"npac": "North Pacific", "natl": "North Atlantic"}.get(name, name)
        x, y = pt(mid % 360.0, 74.0)
        ax.text(x, y, short, fontsize=8.0,
                fontweight="bold", color=colour, ha="center", va="center",
                zorder=7, path_effects=halo)

    # the latitude and longitude labels, on the outer ring
    for lat, text in ((60.0, "60°N"), (30.0, "30°N")):
        x, y = pt(0.0, lat)
        ax.text(x * 1.09, y * 1.09, text, fontsize=8.0, color=C_MUTED,
                ha="center", va="center", zorder=8, path_effects=halo)
    for lon, text in ((0, "0°"), (90, "90°E"), (180, "180°"), (270, "90°W")):
        x, y = pt(lon, 30.0)
        ax.text(x * 1.09, y * 1.09, text, fontsize=8.0, color=C_MUTED,
                ha="center", va="center", zorder=8, path_effects=halo)

    ax.set_xlim(-1.22, 1.22)
    ax.set_ylim(-1.22, 1.22)
    ax.set_aspect("equal")
    ax.axis("off")

    # the legend
    handles = [
        mpatches.Patch(facecolor="#f4b740", edgecolor="none", alpha=0.62,
                       label="North Pacific (60N-90°N)"),
        mpatches.Patch(facecolor="#3d7fd1", edgecolor="none", alpha=0.62,
                       label="North Atlantic (60N-90°N)"),
        mpatches.Patch(facecolor="#d9d3c6", edgecolor="#b3aa9a",
                       label="land"),
    ]
    leg = ax.legend(handles=handles, loc="lower center",
                    bbox_to_anchor=(0.5, -0.22), fontsize=8.0, frameon=False,
                    handlelength=1.1, handleheight=1.0, labelspacing=0.40)
    for t in leg.get_texts():
        t.set_color(C_TEXT)
    return ax


# the land outline of the map, read once
_LAND_POLY = None

# Natural Earth's 1:50m land, committed to the repo (public domain) so the
# figure never needs a download at build time
LAND_FILE = os.path.join(DATA, "ne_50m_land.geojson")


def _land_polygons():
    """-> the land as a list of projected rings, or None.

    The projection is the same azimuthal-equidistant polar projection the
    map uses: r = (90 - lat) / 60, with the pole at the centre and Greenwich
    at the bottom.  The longitudes of a ring are unwrapped first, so a
    coastline that crosses the antimeridian (Chukotka, the Aleutians) is
    drawn the short way round the pole instead of straight across the map.
    """
    global _LAND_POLY
    if _LAND_POLY is not None:
        return _LAND_POLY
    _LAND_POLY = []
    if not os.path.exists(LAND_FILE):
        return _LAND_POLY
    import json
    with open(LAND_FILE) as f:
        d = json.load(f)
    for feat in d.get("features", []):
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        polys = coords if geom.get("type") == "MultiPolygon" else [coords]
        for poly in polys:
            for ring in poly:
                lon = np.array([p[0] for p in ring], float)
                lat = np.array([p[1] for p in ring], float)
                if lat.size < 3:
                    continue
                a = np.unwrap(np.radians(lon))
                r = (90.0 - lat) / 60.0
                x = r * np.sin(a)
                y = -r * np.cos(a)
                _LAND_POLY.append(np.column_stack([x, y]))
    return _LAND_POLY


def _wedge(lon0, lon1, rmax, colour, alpha=1.0):
    """A wedge of the polar map: lon0 to lon1 (degrees east), pole to rmax."""
    import matplotlib.patches as mpatches
    from matplotlib.path import Path

    def pt(lon):
        r = rmax
        a = np.radians(lon)
        return r * np.sin(a), -r * np.cos(a)

    n = 60
    lons = np.linspace(lon0, lon1, n)
    if lon1 < lon0:                      # a wedge that crosses 360
        lons = np.concatenate([np.linspace(lon0, 360.0, n),
                                np.linspace(0.0, lon1, n)])
    verts = [(0.0, 0.0)] + [pt(l) for l in lons]
    codes = [Path.MOVETO] + [Path.LINETO] * len(lons)
    patch = mpatches.PathPatch(Path(verts, codes), facecolor=colour,
                               edgecolor="none", alpha=alpha, zorder=3)
    return patch


def plot_sector_sections(times, sectors, levels, out_path, title, subtitle,
                         split=None, credit=None, handle="@Massachusettswx",
                         order=SECTOR_ORDER,
                         forecast_alpha=0.62):
    """Draw the polar cap split into two sectors, side by side.

    times:   (n,)    ISO strings
    sectors: {name: (n, nlev)} the geopotential height ANOMALY in metres,
             one array per sector
    levels:  (nlev,) the pressure levels, hPa

    The same figure as the polar-cap section - the same colours, the same
    log pressure axis, the same height axis on the right - with one panel
    per sector.  The Atlantic and the Pacific do not warm together, and the
    difference between them is the story the polar-cap mean hides.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.cm import ScalarMappable

    cmap = ListedColormap(COLORS)
    edges = np.array(BREAKS, float)
    norm_c = BoundaryNorm(edges, cmap.N, clip=False)

    lev = np.asarray(levels, float)
    order_l = np.argsort(lev)
    lev = lev[order_l]

    names = [n for n in order if n in sectors]
    if not names:
        raise ValueError("no sector series to draw")

    n = len(times)
    x = np.arange(n)

    fig_w = 17.6
    fig_h = 6.4
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor="white")

    # The panels side by side, then the map of the domains.  The layout is
    # computed from the number of panels: with the Arctic sector added there
    # are three of them, and the hard-coded two-panel geometry put the map
    # on top of the third.
    npan = len(names)
    map_w = 0.225
    map_x = 1.0 - 0.018 - map_w
    panel_right = map_x - 0.030
    gap = 0.018
    left0 = 0.045
    width = (panel_right - left0 - (npan - 1) * gap) / npan
    axes = []
    for i in range(npan):
        ax = fig.add_axes([left0 + i * (width + gap), 0.175, width, 0.635])
        axes.append(ax)

    # the map of the domains the panels cover
    map_ax = fig.add_axes([map_x, 0.105, map_w, 0.705])
    plot_domain_map(map_ax)
    fig.text(map_x + map_w / 2.0, 0.822, "the domains", fontsize=11,
             fontweight="bold", color=C_TEXT, ha="center", va="bottom")

    for i, name in enumerate(names):
        ax = axes[i]
        ax.set_facecolor("white")
        z = np.asarray(sectors[name], float)[:, order_l].T     # (nlev, ntime)

        mid = n
        # The forecast side is drawn at full strength, like the cap section:
        # a partial-opacity overlay laid a grey wash over the anomalies and
        # made the forecast read as weaker than it is.
        ax.contourf(x, lev, z, levels=edges, cmap=cmap,
                    norm=norm_c, extend="both", alpha=1.0)

        ax.set_yscale("log")
        ax.set_ylim(1000.0, 10.0)

        have = set(int(v) for v in lev)
        shown = [p for p in (1000, 700, 500, 400, 300, 200, 100, 50, 30, 10)
                 if p in have]
        ax.set_yticks(shown)
        ax.set_yticklabels(["%d" % p for p in shown], fontsize=9.5,
                           color=C_TEXT)
        ax.set_ylabel("Pressure (hPa)", fontsize=10.5, color=C_TEXT, labelpad=6)

        # Fewer date labels when there is less room: with three panels each
        # one is narrower, and eight labels on each ran into the next
        # panel's first label.
        step = max(1, n // (8 if npan <= 2 else 5))
        idx = list(range(0, n, step))
        if idx[-1] != n - 1:
            if (n - 1) - idx[-1] >= step * 0.6:
                idx.append(n - 1)
            else:
                idx[-1] = n - 1
        while len(idx) > 2:
            gaps = [(idx[j + 1] - idx[j]) for j in range(len(idx) - 1)]
            if min(gaps) >= step * 0.75:
                break
            j = int(np.argmin(gaps))
            if j == 0:
                del idx[1]
            elif j == len(gaps) - 1:
                del idx[-2]
            else:
                del idx[j + 1]
        ax.set_xticks(idx)
        labs = [_short_date(times[k]) for k in idx]
        # A tick label centred on its tick hangs half outside the panel, so
        # the last date of one panel ran into the first date of the next.
        # The panels share one time axis, so the outer panels carry the
        # start and the end date and the inner ones leave them out.  The
        # TICKS stay on every panel, so the gridlines still line up.
        if i > 0:
            labs[0] = ""
        if i < npan - 1:
            labs[-1] = ""
        ax.set_xticklabels(labs, fontsize=8.5, color=C_TEXT)
        ax.set_xlim(-0.5, n - 0.5)

        ax.grid(True, color=C_GRID, linestyle=(0, (1, 3)), lw=0.6, alpha=0.8)
        ax.xaxis.grid(True)
        ax.yaxis.grid(True)

        ax.spines["top"].set_visible(False)
        for sname in ("left", "bottom"):
            ax.spines[sname].set_color("#9ca3af")
            ax.spines[sname].set_linewidth(0.9)
        ax.tick_params(length=3, colors=C_TEXT)

        if split is not None and 0 < split < n:
            ax.axvline(split - 0.5, color=C_SPLIT, lw=1.2, ls=(0, (5, 3)),
                       zorder=6)

        # the panel's own name, above it.  It is CENTRED over its panel:
        # left-aligned, the three names ran into each other, and the map's
        # own heading ran into the third one.  The sectors are named by
        # their LATITUDE range (60N-90N) - that is what the section is
        # about, and the longitudes are on the map.
        fig.text(left0 + i * (width + gap) + width / 2.0, 0.822,
                 "%s (60N-90°N)" % SECTOR_LABELS.get(name, name),
                 fontsize=10.0, fontweight="bold", color=C_TEXT,
                 ha="center", va="bottom")

    # the height axis, on the far right only
    ax2 = axes[-1].twinx()
    ax2.set_yscale("linear")
    ax2.set_ylim(0.0, 33.0)
    hticks = [(0, 0), (8, 5), (16, 10), (24, 15), (32, 20)]
    ax2.set_yticks([t[0] for t in hticks])
    ax2.set_yticklabels([_alt_label(t[0]) for t in hticks], fontsize=8.5,
                        color=C_MUTED)
    ax2.set_ylabel("Approximate height", fontsize=9.5, color=C_MUTED,
                   labelpad=8)
    ax2.tick_params(axis="y", length=3, colors=C_MUTED)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#9ca3af")
    ax2.spines["right"].set_linewidth(0.9)

    fig.text(0.052, 0.968, title, fontsize=15.5, fontweight="bold",
             ha="left", va="top", color=C_TEXT)
    if subtitle:
        fig.text(0.052, 0.918, subtitle, fontsize=9.5, color=C_MUTED,
                 ha="left", va="top")

    sm = ScalarMappable(norm=norm_c, cmap=cmap)
    sm.set_array([])
    cax = fig.add_axes([0.135, 0.082, 0.45, 0.018])
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal",
                      boundaries=edges, ticks=edges[1:-1], extend="neither",
                      spacing="uniform")
    cb.ax.set_xticklabels(["%g" % e for e in edges[1:-1]], fontsize=8,
                          color=C_TEXT)
    cb.outline.set_visible(True)
    cb.outline.set_edgecolor("#c8c5c2")
    cb.outline.set_linewidth(0.8)
    cb.ax.tick_params(length=2, colors=C_TEXT)
    fig.text(0.36, 0.034, "Normalized geopotential height anomaly (\u03c3)",
             fontsize=10.5, ha="center", va="center", fontweight="bold",
             color=C_TEXT)

    if credit:
        fig.text(0.985, 0.007, credit, fontsize=6.0, color="#777777",
                 ha="right", va="bottom", linespacing=1.35)
    if handle:
        fig.text(0.985, 0.032, handle, fontsize=9.5, fontweight="bold",
                 color=C_TEXT, ha="right", va="bottom")

    fig.savefig(out_path, dpi=150, facecolor="white")
    plt.close(fig)
    return out_path
