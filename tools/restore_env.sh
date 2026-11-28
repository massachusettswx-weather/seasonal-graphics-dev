#!/bin/bash
# Restore the Python packages the pipeline needs.
#
# The sandbox's system packages (/usr/local/lib/python3.11/dist-packages) are
# reset from time to time, and `requests` and `eccodes` disappear with them -
# which kills every fetcher and every GRIB reader in the pipeline without
# an error message that says so.
#
# They are installed into the USER site, which lives under the workspace
# (/workspace/.home) and therefore survives the reset.  Note that the user
# site is only on sys.path when the directory exists, so this script creates
# it first.
#
# THE DECEMBER ROLLOVER'S PACKAGES ARE IN HERE TOO (28 Nov 2026).  The
# seasonal job needs xarray, cdsapi, netCDF4 and scipy, and the reinstall
# that the 2 a.m. job did was INCOMPLETE - those four were missing, so the
# 6 December release would have failed on the first C3S request.  They are
# part of the standard set now, so a rebuilt sandbox is ready for the
# rollover without anybody repairing it by hand.
#
#     ./tools/restore_env.sh
set -u
cd "$(dirname "$0")/.."
SITE="$HOME/.local/lib/python3.11/site-packages"
mkdir -p "$SITE"
# the Aliyun mirror in PIP_INDEX_URL is not reachable from here; pypi.org is
pip install --break-system-packages --index-url https://pypi.org/simple \
    --target "$SITE" requests eccodes numcodecs h5netcdf h5py Pillow \
    s3fs zarr xarray cdsapi netCDF4 scipy 2>&1 | tail -3
python3 - <<'PY'
import requests, eccodes
print("requests %s and eccodes %s are in place" % (requests.__version__,
                                                   eccodes.__version__))
PY
python3 - <<'PY'
# The December rollover's packages.  They are checked separately, because
# their absence is what broke the 6 December release and nothing else
# says so.
missing = []
for m in ("xarray", "cdsapi", "netCDF4", "scipy"):
    try:
        __import__(m)
    except Exception:
        missing.append(m)
if missing:
    print("MISSING for the December rollover: %s" % ", ".join(missing))
else:
    print("xarray, cdsapi, netCDF4 and scipy are in place")
PY
