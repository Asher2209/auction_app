"""The visual theme: dark matte with an amber accent, a light variant, local fonts and icons. These tests keep it readable.

(The palette rules themselves, no purple, glass or glow, are guarded in test_phase8_ui.py.)
"""
import re
from pathlib import Path

import pytest
from flask import g

from app.icons import icon

from .test_legal import anon, audit

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
TOKENS = (STATIC / "css" / "design-tokens.css").read_text(encoding="utf-8")
CSS = (STATIC / "css" / "theme.css").read_text(encoding="utf-8")


# ---- WCAG contrast, computed from the real tokens in design-tokens.css -------------------------------------------------
def block(css, selector):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)  # comments may mention tokens too
    start = re.search("^" + re.escape(selector) + r" \{", css, re.M).start()  # the whole selector, not a tail of a list
    return dict(re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", css[start:css.index("\n}", start)]))


BASE = block(TOKENS, ':root, [data-bs-theme="light"]')
THEMES = {"dark": {**BASE, **block(TOKENS, '[data-bs-theme="dark"]')},
          "light": {**BASE, **block(TOKENS, '[data-bs-theme="light"]')}}


def rgb(value):
    v = value.split("/*")[0].strip().lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def lum(c):
    def ch(x):
        x /= 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("name", ["dark", "light"])
def test_every_text_colour_meets_wcag_aa_on_every_background(name):
    t = THEMES[name]
    low = {f"{fg} on {bg}": round(ratio(rgb(t[fg]), rgb(t[bg])), 2)
           for fg in ("--dt-text-primary", "--dt-text-secondary", "--dt-text-muted", "--dt-accent", "--dt-accent-hover")
           for bg in ("--dt-bg-0", "--dt-bg-1", "--dt-bg-2", "--dt-bg-3")
           if ratio(rgb(t[fg]), rgb(t[bg])) < 4.5}
    assert low == {}, f"{name}: below 4.5:1 {low}"


@pytest.mark.parametrize("name", ["dark", "light"])
def test_primary_button_text_is_readable_in_every_state(name):
    t = THEMES[name]  # .btn-primary: --dt-bg-0 text on the accent, its hover and its pressed colour
    assert "--bs-btn-color: var(--dt-bg-0)" in CSS and "--bs-btn-bg: var(--dt-accent)" in CSS
    for state in ("--dt-accent", "--dt-accent-hover", "--dt-accent-dark"):
        assert ratio(rgb(t["--dt-bg-0"]), rgb(t[state])) >= 4.5, (name, state)


def test_bootstrap_links_follow_the_accent_of_each_theme():
    """Bootstrap colours links from RGB triplets, not from --dt-accent, so they must be kept in step by hand."""
    for selector, name in ((":root", "dark"), ('[data-bs-theme="light"]', "light")):
        own = block(CSS, selector)
        assert tuple(int(x) for x in own["--bs-link-color-rgb"].split("/*")[0].split(",")) == rgb(THEMES[name]["--dt-accent"])
        assert (tuple(int(x) for x in own["--bs-link-hover-color-rgb"].split("/*")[0].split(","))
                == rgb(THEMES[name]["--dt-accent-hover"]))


# ---- fonts and icons ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["inter-latin-wght-normal.woff2", "space-grotesk-latin-wght-normal.woff2",
                                  "instrument-serif-latin-400-italic.woff2"])
def test_every_font_is_served_from_this_site(app, name):
    r = app.test_client().get(f"/static/fonts/{name}")
    assert r.status_code == 200 and r.data[:4] == b"wOF2"
    r.close()
    assert f'url("../fonts/{name}")' in CSS


def test_fonts_are_licensed_and_have_system_fallbacks():
    licences = (STATIC / "fonts" / "LICENSES.txt").read_text()
    assert all(n in licences for n in ("Inter", "Space Grotesk", "Instrument Serif", "Lucide"))
    assert CSS.count("font-display: swap") == 3  # text shows at once in the fallback while a font file loads
    assert "--bs-body-font-family: var(--dt-font-primary)" in CSS
    for token in ("--dt-font-primary", "--dt-font-display", "--dt-font-accent"):
        assert re.search(r"system-ui|Georgia", BASE[token]), token


def test_no_page_asks_a_third_party_for_fonts_or_icons():
    for f in list((ROOT / "app" / "templates").rglob("*.html")) + list((STATIC / "css").glob("*.css")):
        text = f.read_text(encoding="utf-8")
        assert "fonts.googleapis" not in text and "fonts.gstatic" not in text and "unpkg.com/lucide" not in text, f


def test_every_icon_used_in_a_template_exists_in_the_sprite():
    sprite = (STATIC / "icons" / "lucide.svg").read_text(encoding="utf-8")
    have = set(re.findall(r'<symbol id="([a-z0-9-]+)"', sprite))
    assert len(have) >= 40 and "ISC" in sprite and "<script" not in sprite.lower()
    used = set()
    for f in (ROOT / "app" / "templates").rglob("*.html"):
        used |= set(re.findall(r"icon\(\s*['\"]([a-z0-9-]+)['\"]", f.read_text(encoding="utf-8")))
    assert used - have == set()  # no template calls icon() today; any that does must name a real symbol


def test_the_sprite_is_well_formed_and_every_symbol_draws_something():
    import xml.dom.minidom as minidom
    doc = minidom.parse(str(STATIC / "icons" / "lucide.svg"))  # raises if the XML is broken
    assert len(doc.getElementsByTagName("svg")) == 1  # only the outer element: no nested <svg> inside a <symbol>
    for sym in doc.getElementsByTagName("symbol"):
        shapes = [n for n in sym.childNodes if n.nodeType == n.ELEMENT_NODE and n.tagName in ("path", "circle", "rect", "line", "polyline", "polygon", "ellipse")]
        assert shapes, sym.getAttribute("id")


def test_the_icon_helper_is_decorative_and_safe(app):
    with app.test_request_context("/"):
        html = str(icon("gavel", 20, 'x" onload="alert(1)'))
        assert 'aria-hidden="true"' in html and 'focusable="false"' in html and "icons/lucide.svg#gavel" in html and 'width="20"' in html
        assert 'onload="alert' not in html and "&#34;" in html
        for bad in ("", "Gavel", "a b", "../x", "x\"y", "a#b"):
            with pytest.raises(ValueError):
                icon(bad)


# ---- light or dark: chosen before the first paint, kept in the browser -------------------------------------------------
def test_the_theme_is_set_in_the_head_before_the_page_paints_without_inline_script(app):
    html = anon(app).get("/").data.decode()
    head = html[:html.index("</head>")]
    assert "js/theme-init.js" in head and head.index("css/theme.css") < head.index("js/theme-init.js")
    assert "js/theme-init.js" not in html[html.index("</head>"):]  # loaded once
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)  # the CSP forbids inline scripts


def test_the_theme_choice_never_leaves_the_browser_and_is_documented(app):
    js = (STATIC / "js" / "theme-init.js").read_text() + (STATIC / "js" / "effects.js").read_text()
    assert "localStorage" in js and "fetch(" not in js and "document.cookie" not in js
    assert "try {" in js  # storage can be blocked
    assert "prefers-color-scheme: dark" in js  # with no saved choice, the system setting decides
    policy = anon(app).get("/legal/cookies").data.decode()
    assert "chainbid-theme" in policy and "local storage" in policy


def test_motion_respects_reduced_motion():
    assert "prefers-reduced-motion: reduce" in CSS


# ---- the pages themselves -------------------------------------------------------------------------------------------------
def test_the_public_pages_pass_the_accessibility_audit(app):
    for path in ("/", "/auctions/", "/legal/terms", "/auth/login"):
        a = audit(anon(app).get(path).data.decode())
        assert a.problems == [] and a.h1 == 1, (path, a.problems)


def test_the_signed_in_pages_pass_the_accessibility_audit(app, users):
    from .test_payments import client_for
    for who, path in (("buyer@t.test", "/buyer/"), ("admin@t.test", "/admin/"), ("seller@t.test", "/seller/")):
        g.pop("_login_user", None)
        page = client_for(app, who).get(path, follow_redirects=True)
        a = audit(page.data.decode())
        assert page.status_code == 200 and a.problems == [] and a.h1 == 1, (path, a.problems)
