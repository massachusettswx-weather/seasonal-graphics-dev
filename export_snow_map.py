"""Export the seasonal snowfall fields for the interactive map.

The maps page paints the snowfall on the world, so the browser needs the
field itself - not a picture of it.  This script reads the same monthly
snowfall GRIBs the panels are drawn from, with the same readers and the
same unit arithmetic (metres of water equivalent per second, accumulated
over the month and turned into inches of snow depth with the 10:1 ratio),
and writes one JSON manifest per model for the browser:

    docs/data/snowmap_<tag>.json
    docs/data/snowmap_<tag>_m<k>_total.png     the snowfall
    docs/data/snowmap_<tag>_m<k>_anom.png      the anomaly

WHAT CHANGED FROM THE FIRST VERSION
-----------------------------------
The first version exported a 1 degree box over the eastern United States -
which is what the static panels cover - and painted it on the world.  The
field is now the WHOLE WORLD, on the model's OWN grid: no interpolation,
no resampling, no regridding.  The monthly product of every centre is a
global field at its native resolution (1 degree for most of them), so the
map can be as sharp as the model that made it.

The anomaly is the second half of the job: the field against **the model's
own hindcast climate**, which is the only baseline that is honest for these
systems - the ECCC is genuinely about three times drier than the others,
and that is a model property, not a bug.  Where the model's own climate
expects essentially no snow the anomaly is masked, because "drier than
normal" is not a statement worth making about a place that never sees
snow.

THE RASTER
----------
Each field is written as an 8-bit greyscale PNG, one byte per cell, and
the browser turns the byte into the house colour (the published 0-300 in
snow-depth ladder for the totals, the house brown-white-teal palette for
the anomalies).  A PNG of a smooth field compresses far better than the
same numbers in JSON, and the browser can hand the pixels straight to the
canvas.

usage:  python3 export_snow_map.py
"""
import os
import sys
import json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
OUT = os.path.join(HERE, "docs", "data")

# the models whose own panels are not published (they are pooled)
POOLED_INTO = {"eccc-canesm5": "eccc-cansips", "eccc-gem5": "eccc-cansips"}

# the C3S systems that go into the multi-model mean (the ECCC counts ONCE,
# as the pooled canSIPS)
MULTI_MEMBERS = ["ecmwf-seas5", "ukmo-gloseas6", "meteo-france-s9",
                  "eccc-cansips", "cmcc-sps4", "dwd-gcfs2"]

# the byte that means "nothing to show here": for the totals it is the top
# of the ladder (over 300 in), for the anomalies it is the mask
OVER = 255


def write_png(path, arr):
    """Write an 8-bit greyscale PNG.  arr is (rows, cols), uint8."""
    from PIL import Image
    im = Image.fromarray(arr, mode="L")
    im.save(path, optimize=True)


def quantise_total(field_in, levels):
    """inches of snow depth -> a byte on the PUBLISHED ladder.

    The published snow-depth ladder is a log scale (0.01 in at the bottom,
    300 in at the top), so the byte is the position on that ladder and not a
    linear scale: a byte of 128 then means the same colour as the middle of
    the colour bar, and a light snowfall still lands in the light end
    instead of being crushed into the first byte.

    0 is white (no snow), 255 is over the top of the ladder.
    """
    lo = float(levels[0])
    hi = float(levels[-1])
    v = np.where(np.isfinite(field_in), field_in, hi)
    t = (np.log10(np.maximum(v, lo)) - np.log10(lo)) / (np.log10(hi) - np.log10(lo))
    out = np.round(np.clip(t, 0.0, 1.0) * 254.0).astype(np.uint8)  # NaN-safe
    out[v > hi] = OVER
    out[v <= 0.0] = 0
    return out


def quantise_anom(field_in, scale):
    """signed anomaly -> 0..254 over +-scale, 255 = masked."""
    a = np.clip((field_in + scale) / (2.0 * scale), 0.0, 1.0) * 254.0
    a = np.where(np.isfinite(a), a, 0.0)
    out = np.round(a).astype(np.uint8)
    out[~np.isfinite(field_in)] = OVER
    out[field_in < -scale] = 0
    out[field_in > scale] = 254
    return out


def nice_scale(v, floor=4.0):
    """A round number for the anomaly scale, so the legend reads well."""
    if not np.isfinite(v) or v <= 0:
        return floor
    for m in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.5, 10.0):
        c = m * 10.0 ** np.floor(np.log10(v))
        if c >= v:
            return max(c, floor)
    return max(10.0 ** (np.floor(np.log10(v)) + 1), floor)


def ladder_lut(levels, colors):
    """The 256-entry table: the quantised byte -> the colour the STATIC
    panels give it.

    The byte is the position on the published ladder (0.01 in at the
    bottom, 300 in at the top).  The static panels turn a value into a
    bucket with BoundaryNorm(clip=True), so over the top of the ladder is
    the TOP COLOUR and not a hole, and a trace of snow is the bottom
    colour.  This table makes exactly the same decision for every cell,
    which is what makes the interactive map the same map as the static
    panels and not merely a map of the same data.
    """
    from matplotlib.colors import ListedColormap, BoundaryNorm, to_hex
    cmap = ListedColormap(colors, name="snow_depth")
    norm = BoundaryNorm(levels, cmap.N, clip=True)
    lo, hi = float(levels[0]), float(levels[-1])
    lut = []
    for b in range(256):
        if b >= OVER:
            lut.append(colors[-1])          # over the top of the ladder
            continue
        t = b / 254.0
        v = 10 ** (np.log10(lo) + t * (np.log10(hi) - np.log10(lo)))
        lut.append(to_hex(cmap(norm(v))))
    return lut


def house_palette():
    """The house colours the browser needs: the published snow-depth ladder
    for the totals, and the house brown-white-teal palette for the
    anomalies.

    The browser is given the ladder's own table, bucket for bucket.  An
    interpolated ramp of its own was what made the first version of the
    map read as a different product from the static panels - softer greys,
    muddied blues, and a magenta that was not the published one.
    """
    import plot_snow_models as PSM
    from plot_snow_totals import boost_saturation

    d = json.load(open(os.path.join(DATA, "snow_depth_scale.json")))
    levels = list(reversed(list(d["levels"])))         # ascending
    colors = list(reversed(list(boost_saturation(list(d["colors"])))))
    colors[0] = "#ffffff"          # zero snowfall is white

    anom_colors = [c for c in PSM.anom_cmap().colors]
    return levels, colors, ladder_lut(levels, colors), anom_colors


def main():
    import plot_snow_models as PSM
    from plot_snow_ref import MONTH_NAMES

    os.makedirs(OUT, exist_ok=True)
    state_p = os.path.join(DATA, "models_fetched.json")
    state = json.load(open(state_p)) if os.path.exists(state_p) else {}

    levels, colors, lut, anom_colors = house_palette()

    # the models we can export, and the global fields they produced
    exported = {}
    summary = []

    for tag, meta in sorted(state.items()):
        if tag in POOLED_INTO:
            continue
        d = os.path.join(MDIR, tag)
        # the map is the WHOLE WORLD.  The centres that serve a global
        # field already have one; the NOAA systems are read over a box for
        # the panels, so their global field is written beside it as
        # snowfall_monthly_global.npz and is preferred here.
        fg = os.path.join(d, "snowfall_monthly_global.npz")
        cg = os.path.join(d, "snowfall_hindcast_global.npz")
        if not os.path.exists(fg):
            fg = os.path.join(d, "snowfall_monthly.grib")
            cg = os.path.join(d, "snowfall_hindcast.grib")
            if not os.path.exists(fg):
                fg = os.path.join(d, "snowfall_monthly.npz")
                cg = os.path.join(d, "snowfall_hindcast.npz")
        if not os.path.exists(fg):
            print("skip %s (no snowfall)" % tag)
            continue
        by_step = PSM.read_snowfall(fg)
        if not by_step:
            print("skip %s (unreadable)" % tag)
            continue
        ext = {}
        xp = os.path.join(d, "snowfall_ext.npz")
        if os.path.exists(xp):
            try:
                ext = PSM.read_extended(xp)
            except Exception as e:
                print("  %s: no extended months (%s)" % (tag, e))

        yms = [ym for ym in sorted(by_step) if PSM.month_end(ym) < PSM.SNOW_END]
        ext_yms = [ym for ym in sorted(ext)
                   if ym not in yms and PSM.month_end(ym) < PSM.SNOW_END
                   and (not ext[ym][3] or ext[ym][3] >= 20)]
        yms = yms + ext_yms
        if not yms:
            print("skip %s (nothing before the end)" % tag)
            continue

        lats0, lons0, order = PSM.grid_axes(by_step[yms[0]][0])

        # the model's OWN hindcast climate - the only honest baseline
        clim = {}
        has_clim = False
        if os.path.exists(cg):
            for step, ym, la0, lo0, v in PSM.read_any(cg):
                clim.setdefault(ym, []).append((la0, lo0, v))
            has_clim = bool(clim)
        if not has_clim:
            print("  %s: no hindcast climate - the anomaly cannot be drawn"
                  % tag, flush=True)

        monthly_in = []
        labels = []
        for ym in yms:
            y, m = ym
            days = PSM.month_len(y, m)
            if ym in ext_yms:
                la, lo, v, nd = ext[ym]
                ens = PSM.interp_to(lats0, lons0, la, lo, v)
                field = ens * 1000.0 / 25.4 * PSM.SNOW_RATIO
            else:
                recs = by_step[ym]
                stack = np.array([PSM.to_2d(r, lats0, lons0, order)
                                  for r in recs])
                ens = stack.mean(axis=0)
                field = ens * days * 86400.0 * 1000.0 / 25.4 * PSM.SNOW_RATIO
            monthly_in.append(field)
            labels.append("%s %d" % (MONTH_NAMES[m - 1], y))

        total_in = np.sum(np.array(monthly_in), axis=0)

        # the anomaly against the model's own climate, month by month
        anom_in = []
        clim_in = []
        for k, ym in enumerate(yms):
            y, m = ym
            if ym not in clim:
                anom_in.append(np.full_like(monthly_in[k], np.nan))
                clim_in.append(np.zeros_like(monthly_in[k]))
                continue
            recs = clim[ym]
            stack = np.array([PSM.to_2d(r, lats0, lons0, order) for r in recs])
            cm = stack.mean(axis=0)
            days = PSM.month_len(y, m)
            cm_in = cm * days * 86400.0 * 1000.0 / 25.4 * PSM.SNOW_RATIO
            clim_in.append(cm_in)
            anom_in.append(monthly_in[k] - cm_in)
        total_anom = np.sum(np.array(anom_in), axis=0)
        total_clim = np.sum(np.array(clim_in), axis=0)

        # the anomaly scale: a round number that covers the field, so the
        # legend is readable and the timeline does not rescale as it moves
        finite = np.abs(np.concatenate([a[np.isfinite(a)] for a in anom_in]
                                       + [total_anom[np.isfinite(total_anom)]]))
        scale = nice_scale(np.percentile(finite, 99.5) if finite.size else 4.0)
        # the mask is the model's OWN climate for the month the anomaly is
        # about: a place where the model expects no snow in December is not
        # "drier than normal in December", whatever it does in January
        masks = [c < PSM.ANOM_MASK_CLIM for c in clim_in]
        mask = total_clim < PSM.ANOM_MASK_CLIM

        # ---- write the rasters ----
        files = []
        for k, lab in enumerate(labels):
            fn_t = "snowmap_%s_m%02d_total.png" % (tag, k + 1)
            fn_a = "snowmap_%s_m%02d_anom.png" % (tag, k + 1)
            write_png(os.path.join(OUT, fn_t),
                      quantise_total(monthly_in[k], levels))
            a = np.array(anom_in[k], dtype=float)
            a[masks[k]] = np.nan
            write_png(os.path.join(OUT, fn_a), quantise_anom(a, scale))
            files.append({"ym": "%04d-%02d" % ym, "label": lab,
                          "total": fn_t, "anom": fn_a})
        fn_t = "snowmap_%s_m00_total.png" % tag
        fn_a = "snowmap_%s_m00_anom.png" % tag
        write_png(os.path.join(OUT, fn_t), quantise_total(total_in, levels))
        ta = np.array(total_anom, dtype=float)
        ta[mask] = np.nan
        write_png(os.path.join(OUT, fn_a), quantise_anom(ta, scale))

        init = meta.get("init") or ""
        out = {
            "tag": tag,
            "name": meta.get("name", tag),
            "init": init,
            # the number of members the mean is made of: the .npz fields
            # carry the ensemble MEAN, so the file holds one "member" - the
            # real count comes from the registry
            "members": int(meta.get("members") or len(by_step[yms[0]])),
            # the model's own grid, north to south and west to east
            "grid": {"lat0": float(lats0[0]), "dlat": float(abs(lats0[1] - lats0[0]))
                     if len(lats0) > 1 else 1.0,
                     "nlat": int(len(lats0)),
                     "lon0": float(lons0[0]), "dlon": float(abs(lons0[1] - lons0[0]))
                     if len(lons0) > 1 else 1.0,
                     "nlon": int(len(lons0))},
            "levels": levels,
            "colors": colors,
            "ramp": colors,          # the legend bar: the published ladder
            "lut": lut,
            "anom_colors": anom_colors,
            "anom_scale": float(scale),
            "anom_available": bool(has_clim),
            "months": files,
            "total": {"total": fn_t, "anom": fn_a},
        }
        path = os.path.join(OUT, "snowmap_%s.json" % tag)
        with open(path, "w") as f:
            json.dump(out, f)
        size = os.path.getsize(path) / 1024.0
        png = sum(os.path.getsize(os.path.join(OUT, f[k])) for f in files
                  for k in ("total", "anom")) / 1024.0
        print("  %-16s %d months, grid %dx%d, manifest %.0f kB, rasters %.0f kB"
              % (tag, len(yms), len(lats0), len(lons0), size, png))
        summary.append(tag)
        exported[tag] = {"months": files, "grid": out["grid"],
                         "anom_available": bool(has_clim),
                         "monthly_in": monthly_in, "total_in": total_in,
                         "anom_in": anom_in, "total_anom": total_anom,
                         "total_clim": total_clim}

    # ---- the C3S multi-model mean, on the same grid ----
    if all(t in exported for t in MULTI_MEMBERS):
        tag = "c3s-multi"
        ref = exported[MULTI_MEMBERS[0]]
        monthly = [np.mean([exported[t]["monthly_in"][k]
                            for t in MULTI_MEMBERS], axis=0)
                   for k in range(len(ref["months"]))]
        total = np.sum(np.array(monthly), axis=0)
        # the mean of the members' anomalies: a member that is masked (no
        # snow expected) must not take the mean down with it
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            anoms = [np.nanmean([exported[t]["anom_in"][k]
                                 for t in MULTI_MEMBERS], axis=0)
                     for k in range(len(ref["months"]))]
            total_anom = np.nanmean([exported[t]["total_anom"]
                                     for t in MULTI_MEMBERS], axis=0)
        # the mask follows the MEAN climate, not the members' own masks: the
        # mean model expects snow wherever enough of the members do
        total_clim = np.mean([exported[t]["total_clim"]
                              for t in MULTI_MEMBERS], axis=0)
        finite = np.abs(np.concatenate([a[np.isfinite(a)] for a in anoms]
                                       + [total_anom[np.isfinite(total_anom)]]))
        scale = nice_scale(np.percentile(finite, 99.5) if finite.size else 4.0)
        # the mask is the model's OWN climate for the month the anomaly is
        # about: a place where the model expects no snow in December is not
        # "drier than normal in December", whatever it does in January
        masks = [c < PSM.ANOM_MASK_CLIM for c in clim_in]
        mask = total_clim < PSM.ANOM_MASK_CLIM
        files = []
        for k, f in enumerate(ref["months"]):
            fn_t = "snowmap_%s_m%02d_total.png" % (tag, k + 1)
            fn_a = "snowmap_%s_m%02d_anom.png" % (tag, k + 1)
            write_png(os.path.join(OUT, fn_t), quantise_total(monthly[k], levels))
            write_png(os.path.join(OUT, fn_a), quantise_anom(anoms[k], scale))
            files.append({"ym": f["ym"], "label": f["label"],
                          "total": fn_t, "anom": fn_a})
        fn_t = "snowmap_%s_m00_total.png" % tag
        fn_a = "snowmap_%s_m00_anom.png" % tag
        write_png(os.path.join(OUT, fn_t), quantise_total(total, levels))
        write_png(os.path.join(OUT, fn_a), quantise_anom(total_anom, scale))
        out = {
            "tag": tag,
            "name": "C3S Multi-Model Mean",
            "init": "",
            "members": 6,
            "grid": ref["grid"],
            "levels": levels, "colors": colors, "ramp": colors,
            "lut": lut,
            "anom_colors": anom_colors,
            "anom_scale": float(scale),
            "anom_available": all(exported[t].get("anom_available", False)
                                  for t in MULTI_MEMBERS),
            "months": files,
            "total": {"total": fn_t, "anom": fn_a},
        }
        with open(os.path.join(OUT, "snowmap_%s.json" % tag), "w") as f:
            json.dump(out, f)
        print("  %-16s %d months, multi-model mean" % (tag, len(files)))
        summary.append(tag)

    # the list the maps page reads to build its model picker
    index = []
    for tag in summary:
        meta = state.get(tag, {})
        index.append({"tag": tag,
                      "name": "C3S Multi-Model Mean" if tag == "c3s-multi"
                      else meta.get("name", tag),
                      "init": meta.get("init", "")})
    with open(os.path.join(OUT, "snowmap_tags.json"), "w") as f:
        json.dump(index, f)
    with open(os.path.join(DATA, "snowmap_tags.json"), "w") as f:
        json.dump(summary, f)
    print("exported %d models" % len(summary))


if __name__ == "__main__":
    main()
