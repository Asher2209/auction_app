"""Structural accessibility checks on the HTML the app really produces, for every role.

These are the checks that can be automated reliably: every form control, button, link and image has an
accessible name, each page has one h1, a language, a main landmark and a skip link. (Colour contrast and
keyboard feel still need a person; see docs/TEST_MATRIX.md.)
"""
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from flask import g

from app.extensions import db
from app.models import Notification, Review, utcnow
from app.services import review_service as rs

from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)
from .test_payments import card, client_for, pay, won
from .test_seller import make_product

VOID = {"input", "img", "br", "hr", "meta", "link", "source", "wbr", "col"}


class Audit(HTMLParser):
    """Collects what a screen reader needs to know about a page."""

    def __init__(self):
        super().__init__()
        self.lang = None
        self.h1 = 0
        self.main = False
        self.skip_link = False
        self.label_for, self.controls, self.problems = set(), [], []
        self._stack, self._label_depth, self._open = [], 0, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "h1":
            self.h1 += 1
        elif tag == "main":
            self.main = a.get("id") == "main"
        elif tag == "label":
            self._label_depth += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        elif tag == "a" and a.get("href") == "#main":
            self.skip_link = True
        if tag == "img":
            if "alt" not in a:
                self.problems.append(("img without alt", a.get("src")))
            for item in self._open:  # an image's alt text names the link or button that contains it
                item["text"] += a.get("alt") or ""
        if tag in ("input", "select", "textarea") and a.get("type") != "hidden":
            named = bool(a.get("aria-label") or a.get("aria-labelledby") or a.get("title") or self._label_depth)
            self.controls.append((tag, a.get("id"), a.get("name"), named, a.get("type")))
        if tag in ("button", "a") and (tag == "button" or a.get("href")):
            self._open.append({"tag": tag, "a": a, "text": ""})
        if tag not in VOID:
            self._stack.append(tag)

    def handle_endtag(self, tag):
        if tag == "label":
            self._label_depth = max(0, self._label_depth - 1)
        if tag in ("button", "a") and self._open and self._open[-1]["tag"] == tag:
            item = self._open.pop()
            a = item["a"]
            if not (item["text"].strip() or a.get("aria-label") or a.get("title")):
                self.problems.append((f"{tag} without a name", a.get("class") or a.get("href")))

    def handle_data(self, data):
        for item in self._open:
            item["text"] += data


def audit(html):
    p = Audit()
    p.feed(html)
    for tag, id_, name, named, typ in p.controls:
        if not (named or (id_ and id_ in p.label_for)):
            p.problems.append((f"{tag} without a label", name or id_))
    return p


@pytest.fixture
def site(app, users, cats):  # noqa: F811
    """A paid purchase with a review, a notification, an active auction and a won-but-unpaid one."""
    paid = won(users, cats, amount="500")
    pay(client_for(app, "buyer@t.test"), paid, "card", card())
    rs.save_review(users["buyer"], paid.id, "4", "Nice")
    live = make_auction(users["seller"], cats["Sports"], "Live one", 100)
    unpaid = won(users, cats, amount="900")
    pending = make_product(users["seller"], cats["Books"])  # not started yet, so the seller may still delete it
    return {"paid": paid, "live": live, "unpaid": unpaid, "pending": pending}


def pages(site):
    paid, live, unpaid = site["paid"], site["live"], site["unpaid"]
    return {
        None: ["/", "/auctions/", "/auctions/?q=a&category=1&status=all&sort=newest&min_price=1", f"/auctions/{live.id}", f"/auctions/{paid.id}",
               "/auth/login", "/auth/register", "/auth/forgot-password"],
        "buyer@t.test": ["/buyer/", "/buyer/bids", "/buyer/watchlist", "/buyer/won", f"/payments/{unpaid.id}", f"/payments/{paid.id}", f"/auctions/{paid.id}",
                         f"/auctions/{live.id}", "/notifications/", "/feedback", "/auth/profile", "/auth/change-password"],
        "seller@t.test": ["/seller/collectibles", "/seller/cards/new", f"/seller/products/{paid.product_id}", f"/seller/products/{site['pending'].id}",
                          "/seller/reviews", "/auth/profile"],
        "admin@t.test": ["/admin/", "/admin/analytics", "/admin/reports", "/admin/reports/payments?from=2000-01-01&to=2030-01-01",
                         "/admin/reports/daily-auctions", "/admin/reports/crypto-transactions", "/admin/products?status=all", f"/admin/products/{paid.product_id}",
                         f"/admin/products/{live.product_id}", f"/admin/products/{site['pending'].id}", "/admin/users", "/admin/reviews", "/admin/feedback", "/notifications/"],
    }


def test_every_page_for_every_role_is_structurally_accessible(app, site):
    checked = 0
    for who, paths in pages(site).items():
        for path in paths:
            g.pop("_login_user", None)
            c = app.test_client() if who is None else client_for(app, who)
            g.pop("_login_user", None)
            r = c.get(path)
            assert r.status_code == 200, (who, path, r.status_code)
            a = audit(r.data.decode())
            assert a.lang == "en", (path, "no lang")
            assert a.h1 == 1, (path, f"{a.h1} h1 elements")
            assert a.main and a.skip_link, (path, "no main landmark / skip link")
            assert a.problems == [], (who, path, a.problems)
            checked += 1
    assert checked >= 40


def test_the_audit_itself_catches_problems():
    bad = audit('<html lang="en"><body><img src="x.png"><input name="q"><select name="s"></select><button></button><a href="/x"></a>'
                '<label for="ok">Fine</label><input id="ok" name="ok"><label>Wrapped <input name="w"></label><input name="aria" aria-label="Named">'
                '<input type="hidden" name="csrf"><button aria-label="Close"></button>'
                '<a href="/photo"><img src="p.png" alt="Photo of a lamp"></a><a href="/deco"><img src="d.png" alt=""></a></body></html>')
    kinds = sorted(p[0] for p in bad.problems)
    # (the linked image WITH alt text is fine; the linked image with empty alt leaves its link nameless)
    assert kinds == ["a without a name", "a without a name", "button without a name", "img without alt", "input without a label", "select without a label"]


def test_the_navigation_toggle_has_a_name_and_state(app):
    html = app.test_client().get("/").data.decode()
    assert 'aria-label="Toggle navigation"' in html and 'aria-controls="nav"' in html and 'aria-expanded="false"' in html


def test_error_pages_are_accessible_too(app):
    for path in ("/nope", "/admin/"):
        g.pop("_login_user", None)
        a = audit(app.test_client().get(path, follow_redirects=True).data.decode())
        assert a.problems == [] and a.h1 >= 1
