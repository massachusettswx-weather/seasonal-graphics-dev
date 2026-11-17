#!/usr/bin/env python3
"""Screenshot the maps page with the REAL model data, for a look.

    python3 tools/shot_maps.py [outdir]

It serves docs/ locally, opens maps.html in headless Chromium with the
development gate key in localStorage, and writes one picture per view.
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux/chrome"


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/workspace/preview"
    os.makedirs(out, exist_ok=True)
    html = open(os.path.join(DOCS, "maps.html")).read()
    m = re.search(r"var H=\"([0-9a-f]+)\"", html)
    gate = m.group(1) if m else ""

    port = 8766
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port),
                             "--directory", DOCS],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    try:
        from playwright.sync_api import sync_playwright
        errors = []
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            pg = b.new_page(viewport={"width": 1800, "height": 1100})
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errors.append("PAGEERROR " + str(e)))
            pg.add_init_script("localStorage.setItem('devgate', %r);" % gate)
            pg.goto("http://127.0.0.1:%d/maps.html" % port)
            pg.wait_for_timeout(6000)
            pg.screenshot(path=os.path.join(out, "fix_globe.png"))

            # the model that is on the map
            models = pg.evaluate(
                "() => Array.from(document.querySelectorAll('#snowModel option'))"
                ".map(o => o.textContent)")
            print("models on the map:", models)

            # zoom in on the globe
            for _ in range(3):
                pg.query_selector('.mapctl button[data-z="in"]').click()
                pg.wait_for_timeout(700)
            pg.wait_for_timeout(1200)
            pg.screenshot(path=os.path.join(out, "fix_globe_zoom.png"))
            print("zoom:", pg.evaluate("() => document.querySelector('.mapctl .zlabel').textContent"))

            # the flat world
            pg.query_selector_all("#mapviews button")[0].click()
            pg.wait_for_timeout(3500)
            pg.screenshot(path=os.path.join(out, "fix_flat.png"))

            # the polar view
            pg.query_selector_all("#mapviews button")[2].click()
            pg.wait_for_timeout(3500)
            pg.screenshot(path=os.path.join(out, "fix_polar.png"))

            # the anomaly, on the globe
            pg.query_selector_all("#mapviews button")[1].click()
            pg.wait_for_timeout(2500)
            ab = pg.query_selector_all("#snowfield button")
            ab[1].click()
            pg.wait_for_timeout(2500)
            pg.screenshot(path=os.path.join(out, "fix_anom.png"))
            b.close()
        print("console errors:", errors if errors else "none")
    finally:
        srv.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
