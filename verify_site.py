"""Check the published site: pages load, no broken images, no console errors.

    python3 verify_site.py [base-url]

The base URL defaults to the operational site; the development copy is at
https://matthew22-cmd.github.io/seasonal-graphics-dev/ .

TWO THINGS THIS HAS TO GET RIGHT
---------------------------------
* the browser.  The installed Playwright wants a headless shell that is
  not in this sandbox, so the full Chromium is used instead - without this
  the verification fails on a missing executable instead of on the site.
* the gate.  The development copy is private behind a password, and the
  password's hash is published in the pages, so the verifier sets it in
  localStorage and then sees the real pages instead of the login form.
"""
import asyncio
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE          # the script sits in the repository root
BASE = sys.argv[1] if len(sys.argv) > 1 else \
    os.environ.get("SITE_URL",
                   "https://massachusettswx-weather.github.io/seasonal-graphics/")
CORE = ("index.html", "model.html", "snow.html", "spv.html", "enso.html")
# the maps page is a DEVELOPMENT page - the operational site does not carry
# it, so it is only checked where it exists
PAGES = CORE + (("maps.html",) if "dev" in BASE.lower() else ())

# the Chromium that is actually installed
CHROME_CANDIDATES = (
    "/root/.cache/ms-playwright/chromium-1243/chrome-linux/chrome",
    os.path.expanduser("~/.cache/ms-playwright/chromium-1243/chrome-linux/chrome"),
)


def chromium_path():
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def gate_hash():
    """The development copy's gate hash, read from the built page."""
    for name in ("maps.html", "index.html"):
        p = os.path.join(ROOT, "docs", name)
        if not os.path.exists(p):
            continue
        m = re.search(r'var H="([0-9a-f]+)"', open(p).read())
        if m:
            return m.group(1)
    return None


async def main():
    from playwright.async_api import async_playwright
    ok = True
    exe = chromium_path()
    gate = gate_hash()
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=exe,
                                    args=["--no-sandbox"] if exe else None)
        ctx = await b.new_context(viewport={"width": 1400, "height": 1000})
        if gate:
            # the development copy's gate: the hash is published in the page
            await ctx.add_init_script(
                "try{localStorage.setItem('devgate', %r);}catch(e){}" % gate)
        pg = await ctx.new_page()
        errs, bad = [], []
        # the favicon 404 is not a site problem
        pg.on("console", lambda m: errs.append(m.text)
              if m.type == "error" and "favicon" not in m.text else None)
        pg.on("pageerror", lambda e: errs.append("PAGEERROR " + str(e)))
        pg.on("response", lambda r: bad.append((r.status, r.url))
              if r.status >= 400 and "favicon" not in r.url else None)
        for page in PAGES:
            r = await pg.goto(BASE + page, wait_until="networkidle", timeout=90000)
            await pg.wait_for_timeout(1500)
            widths = await pg.evaluate(
                "Array.from(document.images).map(i=>i.naturalWidth)")
            broken = sum(1 for w in widths if 0 == w)
            body = (await pg.inner_text("body")).lower()
            note = []
            if "weathermodels" in body:
                note.append("mentions weathermodels")
                ok = False
            if "development password" in body:
                note.append("the gate is still in the way")
                ok = False
            if broken:
                note.append("%d broken image(s)" % broken)
                ok = False
            if r.status != 200:
                note.append("HTTP %s" % r.status)
                ok = False
            print("%-12s status %s  images %3d  broken %d %s"
                  % (page, r.status, len(widths), broken,
                     ("  <-- " + "; ".join(note)) if note else ""))
        if errs:
            ok = False
        if bad:
            ok = False
        print("console errors: %d   http>=400: %d" % (len(errs), len(bad)))
        for e in errs[:5]:
            print("   ERR", e)
        for s, u in bad[:5]:
            print("   HTTP", s, u)
        await b.close()
    print("SITE OK" if ok else "SITE HAS PROBLEMS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
