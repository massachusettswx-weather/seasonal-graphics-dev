#!/usr/bin/env python3
"""Trim the Natural Earth admin-1 file to the states and provinces the
site draws.

The Natural Earth 1:50m admin-1 file carries 294 features - every state
of Russia, every province of China, the states of India, Indonesia and
Brazil - which is a great deal of payload for a map whose subject is the
United States and Canada.  The static panels draw exactly those two
(the US states and the Canadian provinces), so the map draws the same
two, and the file that goes to the browser carries only those.

The output is committed to the repository, like the other Natural Earth
files, so the site never depends on a download at build time.

    python3 tools/make_states_geojson.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

SRC = os.path.join(DATA, "ne_50m_admin_1_states_provinces.geojson")
OUT = os.path.join(DATA, "ne_50m_admin_1_states_us_can.geojson")

# the two the panels draw: the US states and the Canadian provinces
KEEP = ("USA", "CAN")


def main():
    with open(SRC) as f:
        d = json.load(f)
    keep = []
    for feat in d["features"]:
        props = feat.get("properties", {})
        if props.get("adm0_a3") in KEEP:
            keep.append(feat)
    out = {"type": "FeatureCollection", "features": keep}
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    pts = 0
    for feat in keep:
        g = feat["geometry"]
        if g["type"] == "Polygon":
            pts += sum(len(r) for r in g["coordinates"])
        else:
            pts += sum(sum(len(r) for r in p) for p in g["coordinates"])
    print("%s: %d features, %d points, %.1f kB" %
          (os.path.basename(OUT), len(keep), pts,
           os.path.getsize(OUT) / 1024.0))


if __name__ == "__main__":
    main()
