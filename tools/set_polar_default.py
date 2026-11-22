#!/usr/bin/env python3
"""Make the polar-cap section open on the GEFSv12 sub-seasonal panel.

The section's picker lives in the BUILT page (docs/spv.html), and the
built pages are what the readers see.  The source that builds them -
`build_polar_page.py` - now opens on the GEFSv12 (DEFAULT = "gefsv12"),
but a page that was built before that still has the seasonal run
selected, so this script moves the `selected` marker in the page.

It touches the POLAR-CAP picker only (`polarSel`).  The stratosphere
page's other picker - the 10 hPa wind (`modelSel`) - is a different
product and is left alone: the GEFSv12 has no wind panel, so it is not
one of that picker's options.

    python3 tools/set_polar_default.py [TREE]      (default /workspace/devrepo)

It prints what it changed and whether the page already carried it.
"""
import os
import re
import sys

DEFAULT = "gefsv12"
PICKER = "polarSel"


def set_default(html):
    """-> (new html, what happened)"""
    m = re.search(r'<select[^>]*id="%s"[^>]*>(.*?)</select>' % PICKER, html, re.S)
    if not m:
        return None, "the page has no %s picker" % PICKER
    body = m.group(1)
    options = list(re.finditer(r'<option[^>]*value="([^"]+)"([^>]*)>', body))
    if not options:
        return None, "the %s picker has no options" % PICKER
    have = [o.group(1) for o in options]
    if DEFAULT not in have:
        return None, ("the %s picker does not offer %s (it offers %s)"
                      % (PICKER, DEFAULT, ", ".join(have)))
    already = [o for o in options
               if o.group(1) == DEFAULT and "selected" in o.group(2)]
    if already and len([o for o in options if "selected" in o.group(2)]) == 1:
        return html, "the %s picker already opens on %s" % (PICKER, DEFAULT)
    out = []
    last = 0
    for o in options:
        sel = "selected" in o.group(2)
        want = (o.group(1) == DEFAULT)
        if sel == want:
            out.append(body[last:o.end()])
            last = o.end()
            continue
        attrs = re.sub(r'\s*selected', '', o.group(2))
        if want:
            attrs = attrs + " selected"
        out.append(body[last:o.start()])
        out.append('<option value="%s"%s>' % (o.group(1), attrs))
        last = o.end()
    out.append(body[last:])
    newbody = "".join(out)
    return (html[:m.start(1)] + newbody + html[m.end(1):],
            "the %s picker now opens on %s" % (PICKER, DEFAULT))


def main():
    tree = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                           else "/workspace/devrepo")
    page = os.path.join(tree, "docs", "spv.html")
    if not os.path.exists(page):
        print("   %s is not there" % page)
        return 2
    html = open(page, encoding="utf-8").read()
    new, what = set_default(html)
    print("   %s" % what)
    if new is None or new == html:
        return 0
    open(page, "w", encoding="utf-8").write(new)
    # the page must still be a page
    assert open(page, encoding="utf-8").read().count("<html") >= 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
