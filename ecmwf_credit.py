"""The ECMWF's attribution, shown on the graphics that use its data.

ECMWF asks that any graphic made from its data carries its credit on the
bottom right, inside the graphic.  The multi-model products average several
centres together, so they are not ECMWF products and do not carry it.
"""
from datetime import date

ECMWF_CREDIT = ("© %d European Centre for Medium-Range Weather Forecasts "
                "(ECMWF). This service is based on data and products of the "
                "ECMWF." % date.today().year)

# The reanalysis half of every polar-cap graphic is NOAA's CORe, so those
# graphics carry NOAA's credit whether or not the forecast is an ECMWF one.
NOAA_CORE_CREDIT = ("Reanalysis: NOAA's CORe (the FV3-GFS reanalysis).")

# the systems whose data comes from ECMWF
ECMWF_TAGS = {"ecmwf-seas5", "ecmwf-s4s", "ec46", "eps"}


def credit_for(tag):
    """The credit line for a model's graphic, or an empty string."""
    return ECMWF_CREDIT if tag in ECMWF_TAGS else ""


def credit_for_polar(tag):
    """The credit line for a polar-cap graphic.

    Every polar chart is drawn against NOAA's CORe reanalysis, so the NOAA
    credit is on all of them; the ECMWF credit is on the ones whose forecast
    comes from ECMWF.
    """
    parts = []
    if tag in ECMWF_TAGS:
        parts.append(ECMWF_CREDIT)
    parts.append(NOAA_CORE_CREDIT)
    return "  ".join(parts)
