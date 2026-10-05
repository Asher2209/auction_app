"""The visual theme: gradient, Inter, glass, icons, dark mode. The look is decorative; these tests keep it from costing readability."""
import re
from pathlib import Path

import pytest
from flask import g

from app.icons import icon

from .test_legal import anon, audit

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
CSS = (STATIC / "css" / "theme.css").read_text(encoding="utf-8")


# ---- WCAG contrast, computed from the real tokens in theme.css --------------------------------------------------
def tokens(selector_start):
    block = CSS[CSS.index(selector_start):]
    block = block[block.index("{") + 1:block.index("\n}")]
    return dict(re.findall(r"(--cb-[a-z-]+):\s*([^;]+);", block))


def rgb(value):
    value = value.strip()
    if value.startswith("#"):
        v = value[1:]
        if len(v) == 3:
            v = "".join(c * 2 for c in v)
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4)) + (1.0,)
    m = re.match(r"rgba?\(([^)]+)\)", value)
    parts = [float(p) for p in m.group(1).split(",")]
    return (parts[0], parts[1], parts[2], parts[3] if len(parts) > 3 else 1.0)


def over(fg, bg):
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3)) + (1.0,)


def lum(c):
    def ch(x):
        x /= 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


LIGHT, DARK = tokens(':root, [data-bs-theme="light"]'), tokens('[data-bs-theme="dark"] {')


@pytest.mark.parametrize("name,t", [("light", LIGHT), ("dark", {**LIGHT, **DARK})])
def test_every_text_and_background_pair_meets_wcag_aa(name, t):
    bg, surface, solid = rgb(t["--cb-bg"]), rgb(t["--cb-surface"]), rgb(t["--cb-glass-solid"])
    glass = over(rgb(t["--cb-glass"]), bg)  # glass is translucent: judge it as it looks over the page
    pairs = {
        "text on page": (t["--cb-text"], bg), "text on surface": (t["--cb-text"], surface), "text on glass": (t["--cb-text"], glass),
        "muted on page": (t["--cb-muted"], bg), "muted on surface": (t["--cb-muted"], surface), "muted on glass": (t["--cb-muted"], glass),
        "link on page": (t["--cb-link"], bg), "link on glass": (t["--cb-link"], glass), "link on solid": (t["--cb-link"], solid),
        "gradient text start on page": (t["--cb-gt-from"], bg), "gradient text end on page": (t["--cb-gt-to"], bg),
        "gradient text start on glass": (t["--cb-gt-from"], glass), "gradient text end on glass": (t["--cb-gt-to"], glass),
        "badge text on badge": (t["--cb-badge-text"], rgb(t["--cb-badge-bg"])),
    }
    low = {k: round(ratio(rgb(fg), bg_), 2) for k, (fg, bg_) in pairs.items() if ratio(rgb(fg), bg_) < 4.5}
    assert low == {}, f"{name}: below 4.5:1 {low}"
    if name == "dark":  # a dark theme here is soft, not murky: body text is well above the minimum
        assert ratio(rgb(t["--cb-text"]), bg) >= 10 and ratio(rgb(t["--cb-muted"]), bg) >= 7


def test_white_text_on_the_gradient_and_the_hover_fade_stays_readable():
    violet, blue, white = rgb(LIGHT["--cb-violet"]), rgb(LIGHT["--cb-blue"]), (255, 255, 255, 1.0)
    assert ratio(white, violet) >= 4.5 and ratio(white, blue) >= 4.5
    for page in (rgb(LIGHT["--cb-bg"]), rgb(DARK["--cb-bg"])):  # a hovered (82% opaque) button over either page colour
        for base in (violet, blue):
            faded = over(base[:3] + (0.82,), page)
            assert ratio(white, faded) >= 3, "faded button text must stay legible (large/bold UI text threshold)"
    assert ratio(white, rgb("#5b21b6")) >= 4.5  # pressed state


# ---- fonts and icons ---------------------------------------------------------------------------------------------
def test_inter_is_served_from_this_site_and_used_everywhere(app):
    font = app.test_client().get("/static/fonts/inter-latin-wght-normal.woff2")
    assert font.status_code == 200 and font.data[:4] == b"wOF2"
    font.close()
    assert 'url("../fonts/inter-latin-wght-normal.woff2")' in CSS and "--bs-body-font-family: \"Inter Variable\"" in CSS
    assert "font-family: inherit" in CSS  # charts follow the body font too
    assert "Inter" in (STATIC / "fonts" / "LICENSES.txt").read_text() and "Lucide" in (STATIC / "fonts" / "LICENSES.txt").read_text()


def test_no_page_asks_a_third_party_for_fonts_or_icons():
    for f in list((ROOT / "app" / "templates").rglob("*.html")) + [STATIC / "css" / "theme.css", STATIC / "css" / "style.css"]:
        text = f.read_text(encoding="utf-8")
        assert "fonts.googleapis" not in text and "fonts.gstatic" not in text and "unpkg.com/lucide" not in text, f


def test_every_icon_used_in_a_template_exists_in_the_sprite():
    sprite = (STATIC / "icons" / "lucide.svg").read_text(encoding="utf-8")
    have = set(re.findall(r'<symbol id="([a-z0-9-]+)"', sprite))
    assert len(have) >= 40 and "ISC" in sprite and "<script" not in sprite.lower()
    used = set()
    for f in (ROOT / "app" / "templates").rglob("*.html"):
        used |= set(re.findall(r"icon\(\s*['\"]([a-z0-9-]+)['\"]", f.read_text(encoding="utf-8")))
    assert len(used) >= 15
    assert used - have == set()


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


# ---- the home page ------------------------------------------------------------------------------------------------
def home(app):
    return anon(app).get("/").data.decode()


def test_home_has_badge_gradient_headline_emoji_and_three_icon_boxes(app):
    html = home(app)
    hero = html[html.index('class="hero'):html.index('id="how-it-works"')]
    assert hero.index("hero-badge") < hero.index("<h1")  # the badge sits above the headline
    assert 'class="gradient-text"' in hero and '<span aria-hidden="true">🔨</span>' in hero
    assert "data-beam" in hero
    assert "data-reveal" not in hero.split(">")[0]  # the first screen is never hidden waiting for a scroll observer
    how = html[html.index('id="how-it-works"'):html.index('id="live-now"')]
    assert how.count("icon-box") == 3 and how.count("col-md-4") == 3 and how.count("card-accent") == 3
    assert how.count('<div class="row g-3">') == 1  # all three in one row
    assert audit(html).problems == []


def test_headline_stays_readable_without_the_gradient_effect():
    assert "forced-colors: active" in CSS and "-webkit-text-fill-color: currentColor" in CSS
    assert re.search(r"\.gradient-text \{[^}]*color: var\(--cb-gt-from\)", CSS)  # a solid colour sits under the clipped gradient


def test_auction_cards_have_the_coloured_left_border_and_glass_style(app):
    assert ".card-accent { border-left: 4px solid" in CSS and "backdrop-filter" in CSS
    assert "@supports not" in CSS  # browsers without blur get a solid card instead of unreadable text


def test_emojis_in_headings_are_hidden_from_screen_readers(app, users):
    for path in ("/", "/auctions/", "/legal/terms", "/auth/login"):
        html = anon(app).get(path).data.decode()
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S).group(1)
        assert re.search(r'<span aria-hidden="true">[^\x00-\x7f]+</span>', h1), path


def test_every_page_loads_the_theme_and_the_effects_without_inline_script(app):
    html = home(app)
    head = html[:html.index("</head>")]
    assert "css/theme.css" in head and "js/theme-init.js" in head and 'name="color-scheme"' in head
    assert head.index("css/theme.css") < head.index("js/theme-init.js")
    assert "js/effects.js" in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)


# ---- dark mode toggle ------------------------------------------------------------------------------------------------
def test_theme_toggle_is_a_labelled_button_with_state(app):
    html = home(app)
    m = re.search(r'<button id="theme-toggle"[^>]*>', html)
    assert m and 'aria-pressed="false"' in m.group(0) and 'aria-label="Switch to dark theme"' in m.group(0) and 'type="button"' in m.group(0)


def test_the_theme_choice_never_leaves_the_browser_and_is_documented(app):
    js = (STATIC / "js" / "theme-init.js").read_text() + (STATIC / "js" / "effects.js").read_text()
    assert "localStorage" in js and "fetch(" not in js and "document.cookie" not in js
    assert "try {" in js  # storage can be blocked
    policy = anon(app).get("/legal/cookies").data.decode()
    assert "chainbid-theme" in policy and "local storage" in policy


# ---- motion ------------------------------------------------------------------------------------------------------------
def test_motion_effects_respect_reduced_motion_and_never_hide_content_without_javascript():
    assert "prefers-reduced-motion: reduce" in CSS
    reveal = [line for line in CSS.splitlines() if "[data-reveal]" in line and "opacity: 0" in line]
    assert reveal and all(line.lstrip().startswith(".js-reveal") for line in reveal)  # hidden only once JavaScript says it can reveal
    init = (STATIC / "js" / "theme-init.js").read_text()
    assert "IntersectionObserver" in init and "prefers-reduced-motion" in init
    effects = (STATIC / "js" / "effects.js").read_text()
    assert "touch" in effects and "prefers-reduced-motion" in effects and "setTimeout" in effects  # fail-safe reveal


def test_buttons_fade_on_hover_but_not_when_disabled():
    assert re.search(r"\.btn:hover:not\(:disabled\):not\(\.disabled\) \{ opacity: \.82; \}", CSS)
    assert "transition: opacity" in CSS
    assert ".btn-primary" in CSS and "var(--cb-grad)" in CSS and "linear-gradient(135deg, #6d28d9 0%, #2563eb 100%)" in CSS


def test_the_whole_app_still_passes_the_accessibility_audit_for_signed_in_pages(app, users):
    from .test_payments import client_for
    for who, path in (("buyer@t.test", "/buyer/"), ("admin@t.test", "/admin/"), ("seller@t.test", "/seller/")):
        g.pop("_login_user", None)
        a = audit(client_for(app, who).get(path).data.decode())
        assert a.problems == [] and a.h1 == 1, (path, a.problems)


# ---- type pairing and grain ---------------------------------------------------------------------------------------------
def test_display_and_accent_fonts_are_local_and_inter_stays_the_body_font(app):
    c = app.test_client()
    for name in ("space-grotesk-latin-wght-normal.woff2", "instrument-serif-latin-400-italic.woff2"):
        r = c.get(f"/static/fonts/{name}")
        assert r.status_code == 200 and r.data[:4] == b"wOF2", name
        r.close()
        assert f'url("../fonts/{name}")' in CSS
    assert '--bs-body-font-family: "Inter Variable"' in CSS  # long text and forms stay in the plainer face
    assert re.search(r"h1, h2, h3[^{]*\{ font-family: var\(--cb-font-display\); \}", CSS)
    licences = (STATIC / "fonts" / "LICENSES.txt").read_text()
    assert "Space Grotesk" in licences and "Instrument Serif" in licences
    # every custom family has a system fallback, so text shows at once while the font file loads (font-display: swap)
    assert "font-display: swap" in CSS and "Georgia" in CSS and "system-ui" in CSS


def test_serif_italic_accent_words_are_visual_only(app):
    assert re.search(r"\.accent \{[^}]*font-family: var\(--cb-font-accent\); font-style: italic", CSS)
    html = home(app)
    assert re.findall(r'<span class="accent">([^<]+)</span>', html) == ["auctions", "works", "now"]
    assert "<em" not in re.search(r"<h1.*?</h1>", html, re.S).group(0)  # a plain span: screen readers do not add emphasis to a styling choice
    assert re.sub(r"<[^>]+>", "", re.search(r"<h1.*?</h1>", html, re.S).group(0)).split() == ["🔨", "Live", "auctions"]  # reads as ordinary words


def test_grain_overlays_the_gradients_and_is_a_local_subtle_texture():
    grain = (STATIC / "img" / "grain.svg").read_text()
    assert "feTurbulence" in grain and "http" not in grain.replace("http://www.w3.org/2000/svg", "")
    opacity = float(re.search(r'opacity="([0-9.]+)"', grain).group(1))
    assert opacity <= 0.2  # subtle: text sitting on it must keep its contrast
    layered = re.findall(r'url\("\.\./img/grain\.svg"\)\s*,\s*(?:var\(--cb-grad\)|radial-gradient)', CSS)
    assert len(layered) >= 4  # navbar, hero, primary button and icon box all carry grain above their gradient
    import xml.dom.minidom as minidom
    minidom.parseString(grain)


def test_the_grain_file_is_served(app):
    r = app.test_client().get("/static/img/grain.svg")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"
    r.close()
