"""NOAA CFSv2 seasonal forecast, taken from NCEP's own CPC product.

CFSv2 cannot be pulled from the C3S archive for the current init (the
non-ECMWF contribution is access-restricted for the newest init, and NOAA's
C3S system entry serves no recent data), so the forecast is read from CPC:

    https://www.cpc.ncep.noaa.gov/products/CFSv2/CFSv2seasonal.shtml

That page publishes the monthly means of the 40-member ensemble for the
current init (1 Nov 2026 at the time of writing) as netCDF.  The files hold
the ANOMALY of the ensemble mean with respect to the 1991-2020 CFSv2 hindcast
climatology, so:

  * the anomaly panels are the published anomaly itself (it is already the
    model's own hindcast anomaly);
  * the absolute snowfall panels add the ERA5 1991-2020 climatology to the
    published anomaly.  That is an approximation - CPC does not publish the
    raw CFSv2 hindcast fields - and the figure says so.

Snowfall is precipitation x the fraction that falls as snow, the same
derivation used for the ERA5 climatology.
"""
import os, sys, json, calendar, urllib.request, time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
CPC = "https://www.cpc.ncep.noaa.gov/products/CFSv2"


def _bilinear(src, slat, slon, tlat, tlon):
    """Bilinear resample of a 2-D field (order-agnostic)."""
    o = np.argsort(slat); slat = np.asarray(slat)[o]; src = src[o, :]
    o = np.argsort(slon); slon = np.asarray(slon)[o]; src = src[:, o]
    i = np.clip(np.searchsorted(slat, tlat) - 1, 0, len(slat) - 2)
    dy = (tlat - slat[i]) / (slat[i + 1] - slat[i])
    j = np.clip(np.searchsorted(slon, tlon) - 1, 0, len(slon) - 2)
    dx = (tlon - slon[j]) / (slon[j + 1] - slon[j])
    ii, jj = i[:, None], j[None, :]
    return ((1 - dy)[:, None] * ((1 - dx)[None, :] * src[ii, jj] +
                                 dx[None, :] * src[ii, jj + 1]) +
            dy[:, None] * ((1 - dx)[None, :] * src[ii + 1, jj] +
                           dx[None, :] * src[ii + 1, jj + 1]))


def download(name, outdir, max_age_h=6.0):
    """Fetch a CPC file, re-fetching it if the cached copy is old.

    CPC regenerates the seasonal files when a new init is launched, and the
    file on the server is replaced in place - the November init landed on
    11 Nov 2026 at 13:33 UTC, under the same name as the October one.  So
    the cache has to be aged out, not just size-checked.
    """
    os.makedirs(outdir, exist_ok=True)
    p = os.path.join(outdir, name)
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        age = (time.time() - os.path.getmtime(p)) / 3600.0
        if age < max_age_h:
            return p
        print("  the cached %s is %.0f h old - refetching" % (name, age), flush=True)
    url = "%s/dataInd1/%s" % (CPC, name)
    print("downloading", url, flush=True)
    with urllib.request.urlopen(url, timeout=180) as r, open(p, "wb") as f:
        f.write(r.read())
    return p


def read_cpc(path):
    import h5netcdf
    with h5netcdf.File(path, "r") as f:
        anom = np.asarray(f["anom"][0, :, 0], float)      # (time, lat, lon)
        lat = np.asarray(f["lat"][:], float)
        lon = np.asarray(f["lon"][:], float)
        t = np.asarray(f["time"][:], float)
        units = str(f["anom"].attrs.get("units", ""))
    lon = np.where(lon > 180, lon - 360, lon)
    return anom, lat, lon, t, units


def months_from_cpc(t):
    import datetime
    out = []
    for x in t:
        d = datetime.date(2021, 1, 1) + datetime.timedelta(days=int(x))
        out.append((d.year, d.month))
    return out


def fetch_global(tag="cfsv2"):
    """The same model over the WHOLE WORLD, for the interactive map.

    The panels are drawn over the eastern United States, so the monthly
    files above are cut to that box.  The map needs the whole globe, so
    the same calculation is done on the global ERA5 climatology
    (data/era5_snow_clim_arco_global.npz) and written beside the others
    as snowfall_monthly_global.npz / snowfall_hindcast_global.npz - the
    names the map exporter looks for.

    The anomaly is still the model's OWN: the CPC file already holds the
    CFSv2 ensemble-mean anomaly against the model's own hindcast
    climatology, so subtracting the ERA5 climatology back out leaves
    exactly the anomaly the model published.
    """
    d = os.path.join(DATA, "models", tag)
    clim_path = os.path.join(DATA, "era5_snow_clim_arco_global.npz")
    if not os.path.exists(clim_path):
        print("no global ERA5 climatology yet - the map keeps the box field")
        return
    pp = download("glbPrecMon.nc", os.path.join(DATA, "cpc"))
    tp = download("glbT2mMon.nc", os.path.join(DATA, "cpc"))
    prec, plat, plon, t, punit = read_cpc(pp)
    mons = months_from_cpc(t)
    init = "%04d-%02d" % mons[0]

    cz = np.load(clim_path, allow_pickle=True)
    glat = np.asarray(cz["lat"], float)              # ascending
    glon = np.asarray(cz["lon"], float)              # 0..360
    gmon = [int(x) for x in cz["months"]]
    gclim = np.asarray(cz["clim"], float)            # (month, lat, lon) mm
    gclim_p = (np.asarray(cz["clim_precip"], float)
               if "clim_precip" in cz.files else None)
    print("global climatology:", glat.shape, glon.shape, gmon,
          "| with precip:", gclim_p is not None)

    fcst = []
    anom = []
    # The CPC grid runs -179..180 and the global climatology grid runs
    # 0..360, so the longitudes have to be in the SAME convention before
    # the model's anomaly is resampled onto it.  Without this the
    # interpolation runs off the end of the source grid and extrapolates:
    # the field comes out about ten times too big and the world map shows
    # snow in places that never get any.
    plon360 = np.where(np.asarray(plon, float) < 0,
                       np.asarray(plon, float) + 360.0,
                       np.asarray(plon, float))
    for k, (y, m) in enumerate(mons):
        days = calendar.monthrange(y, m)[1]
        pr_anom = _bilinear(prec[k], plat, plon360, glat, glon) * days   # mm/month
        if m in gmon:
            i = gmon.index(m)
            base = gclim[i]
            if gclim_p is not None:
                frac = np.clip(base / np.maximum(gclim_p[i], 1e-6), 0.0, 1.0)
            else:
                frac = (base > 0.5).astype(float)
        else:
            base = np.zeros_like(pr_anom)
            frac = np.zeros_like(pr_anom)
        snow_anom = pr_anom * frac
        fcst.append(base + snow_anom)
        anom.append(snow_anom)

    # the renderer's convention: a rate in m w.e. s-1, the latitudes
    # descending, the longitudes ascending
    lat = glat[::-1].copy()
    lon = glon.copy()
    order = np.argsort(lon)
    lon = lon[order]
    months = ["%04d-%02d" % m for m in mons]
    sec = np.array([calendar.monthrange(*m)[1] * 86400.0 for m in mons])

    def pack(arrs):
        a = np.stack(arrs)
        a = np.clip(a, 0.0, None)
        a = a[:, :, order][:, ::-1, :]
        return (a[None, :, :, :] / 1000.0 /
                sec[None, :, None, None]).astype(np.float32)

    os.makedirs(d, exist_ok=True)
    np.savez_compressed(os.path.join(d, "snowfall_monthly_global.npz"),
                        months=np.array(months),
                        member_numbers=np.array([0]),
                        values=pack(fcst),
                        lat=lat, lon=lon,
                        meta=np.array(json.dumps(
                            dict(tag=tag, name="NOAA CFSv2", init=init,
                                 members=40, source="NCEP CPC monthly means",
                                 note="the whole world; absolute snowfall = the "
                                      "ERA5 1991-2020 climatology plus the "
                                      "CFSv2 hindcast anomaly"))))
    base = []
    for (y, m) in mons:
        base.append(gclim[gmon.index(m)] if m in gmon else np.zeros_like(anom[0]))
    np.savez_compressed(os.path.join(d, "snowfall_hindcast_global.npz"),
                        months=np.array(months),
                        values=pack(base),
                        lat=lat, lon=lon,
                        meta=np.array(json.dumps(dict(init=init))))
    print("wrote the global fields for %s: %d months on a %dx%d grid"
          % (tag, len(months), len(lat), len(lon)))


def fetch(tag="cfsv2"):
    d = os.path.join(DATA, "cpc")
    pp = download("glbPrecMon.nc", d)
    tp = download("glbT2mMon.nc", d)
    prec, plat, plon, t, punit = read_cpc(pp)
    mons = months_from_cpc(t)
    print("CFSv2 lead months:", ["%04d-%02d" % m for m in mons], "| precip units:", punit)
    # the first lead month identifies the init: the CPC replaces the file in
    # place when a new run starts, so the init comes from the data and not
    # from a constant that would have to be edited every month
    init = "%04d-%02d" % mons[0]
    print("CFSv2 init: %s" % init)

    # ERA5 1991-2020 climatology for the absolute snowfall panels
    clim_path = os.path.join(DATA, "era5_snow_clim_arco_conus.npz")
    if not os.path.exists(clim_path):
        clim_path = os.path.join(DATA, "era5_snow_clim_arco.npz")
    cz = np.load(clim_path, allow_pickle=True)
    clat = np.asarray(cz["lat"], float)
    clon = np.asarray(cz["lon"], float)
    clon = np.where(clon > 180, clon - 360, clon)
    cmon = [int(x) for x in cz["months"]]
    clim = np.asarray(cz["clim"], float)                    # (month, lat, lon) mm
    clim_p = None
    if "clim_precip" in cz.files:
        clim_p = np.asarray(cz["clim_precip"], float)       # (month, lat, lon) mm
    print("ERA5 climatology:", os.path.basename(clim_path), clat.shape, clon.shape, cmon,
          "| with precip:", clim_p is not None)

    fcst = []
    anom = []
    for k, (y, m) in enumerate(mons):
        days = calendar.monthrange(y, m)[1]
        pr_anom = _bilinear(prec[k], plat, plon, clat, clon) * days   # mm/month
        if m in cmon:
            i = cmon.index(m)
            base = clim[i]
            if clim_p is not None:
                frac = np.clip(base / np.maximum(clim_p[i], 1e-6), 0.0, 1.0)
            else:
                frac = (base > 0.5).astype(float)
        else:
            base = np.zeros_like(pr_anom)
            frac = np.zeros_like(pr_anom)
        snow_anom = pr_anom * frac
        fcst.append(base + snow_anom)
        anom.append(snow_anom)
        print("  lead %d (%04d-%02d): ERA5 clim max %.1f mm | model anomaly max %.1f mm | "
              "forecast max %.1f mm" % (k + 1, y, m, base.max(), snow_anom.max(),
                                       (base + snow_anom).max()), flush=True)

    # the renderer works on the C3S convention: a rate in m w.e. s-1, the
    # latitudes descending
    lat = clat[::-1].copy()
    lon = clon.copy()
    order = np.argsort(lon)
    lon = lon[order]
    months = ["%04d-%02d" % m for m in mons]
    sec = np.array([calendar.monthrange(*m)[1] * 86400.0 for m in mons])

    def pack(arrs):
        a = np.stack(arrs)                       # (nmonth, nlat, nlon) mm w.e.
        a = np.clip(a, 0.0, None)                # a snowfall cannot be negative
        a = a[:, :, order][:, ::-1, :]
        # the renderer wants a rate in m w.e. s-1
        return (a[None, :, :, :] / 1000.0 /
                sec[None, :, None, None]).astype(np.float32)

    os.makedirs(os.path.join(MDIR, tag), exist_ok=True)
    np.savez_compressed(os.path.join(MDIR, tag, "snowfall_monthly.npz"),
                        months=np.array(months),
                        member_numbers=np.array([0]),
                        values=pack(fcst),
                        lat=lat, lon=lon,
                        meta=np.array(json.dumps(
                            dict(tag=tag, name="NOAA CFSv2", init=init,
                                 members=40, source="NCEP CPC monthly means",
                                 note="absolute snowfall = the ERA5 1991-2020 climatology "
                                      "plus the CFSv2 hindcast anomaly"))))
    # the "hindcast" the renderer subtracts is the ERA5 climatology, so the
    # anomaly panels show exactly the model's own hindcast anomaly
    base = []
    for (y, m) in mons:
        base.append(clim[cmon.index(m)] if m in cmon else np.zeros_like(anom[0]))
    np.savez_compressed(os.path.join(MDIR, tag, "snowfall_hindcast.npz"),
                        months=np.array(months),
                        values=pack(base),
                        lat=lat, lon=lon,
                        meta=np.array(json.dumps(dict(init=init))))
    print("wrote", tag, "npz files")

    sp = os.path.join(DATA, "models_fetched.json")
    state = json.load(open(sp)) if os.path.exists(sp) else {}
    state[tag] = {"name": "NOAA CFSv2", "init": init, "members": 40,
                  "source": "NCEP CPC", "leads": len(mons)}
    json.dump(state, open(sp, "w"), indent=1)
    print("registered %s in models_fetched.json" % tag)


if __name__ == "__main__":
    fetch()
    fetch_global()
