"""Legal pages, the cookie banner, and the consent checkboxes on every form that collects or commits something."""
import re

import pytest
from flask import g

from app import legal
from app.extensions import db
from app.models import CryptoPayment, Feedback, Payment, Product, User

from .conftest import PASSWORD, login
from .test_accessibility import audit
from .test_auth import REG
from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)
from .test_payments import card, client_for, pay, won
from .test_seller import form_data, post_new

PAGES = {"/legal/privacy": "Privacy Policy", "/legal/terms": "Terms of Service", "/legal/refunds": "Refund Policy", "/legal/cookies": "Cookie Policy"}


def anon(app):
    g.pop("_login_user", None)
    return app.test_client()


def banner_shown(response):
    return b'aria-label="Cookie notice"' in response.data


# ---- the four pages ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("path,title", PAGES.items())
def test_each_policy_page_is_public_and_complete(app, path, title):
    r = anon(app).get(path)
    assert r.status_code == 200
    html = r.data.decode()
    assert f"<h1" in html and title in html
    assert legal.POLICY_VERSION in html and legal.LAST_UPDATED in html
    assert app.config["LEGAL_CONTACT_EMAIL"] in html
    assert "academic project" in html and "not legal" in html  # never presented as vetted legal advice
    a = audit(html)
    assert a.h1 == 1 and a.problems == []


def test_the_policies_describe_what_the_software_really_does(app):
    c = anon(app)
    privacy, terms, refunds, cookies = (c.get(p).data.decode() for p in PAGES)
    assert "Card numbers and CVVs are never stored" in privacy and "private key" in privacy
    assert "cannot be erased" in privacy and "no self-service" in privacy  # the limits are stated, not hidden
    assert "binding" in terms and "60 seconds" in terms and "2 minutes" in terms
    assert "no real money" in terms
    assert "Blockchain transactions are final" in refunds and "no automatic refund" in refunds
    assert "sets no advertising, analytics or tracking cookies" in cookies.replace("<strong>", "").replace("</strong>", "")


def test_the_cookie_policy_lists_exactly_the_cookies_the_app_sets(app, users):
    """If a new cookie ever appears, this fails until the Cookie Policy names it."""
    documented = set(re.findall(r"<code>([a-z_]+)</code></th>", anon(app).get("/legal/cookies").data.decode()))
    assert documented == {"session", legal.CONSENT_COOKIE}
    c = app.test_client()
    g.pop("_login_user", None)
    c.get("/auth/login")
    login(c, "buyer@t.test", PASSWORD)
    c.get("/auctions/")
    c.post("/legal/cookies/consent", data={"choice": "all"})
    c.get("/buyer/")
    seen = {cookie.key for cookie in c._cookies.values()}
    assert seen and seen <= documented


@pytest.mark.parametrize("who", [None, "buyer@t.test", "seller@t.test", "admin@t.test"])
def test_every_page_links_to_all_four_policies_in_the_footer(app, users, who):
    c = anon(app) if who is None else client_for(app, who)
    g.pop("_login_user", None)
    html = c.get("/").data.decode()
    for path in PAGES:
        assert f'href="{path}"' in html
    assert "/legal/cookies#settings" in html


# ---- cookie banner -----------------------------------------------------------------------------------------
def test_banner_appears_until_a_choice_is_made_and_then_stays_away(app):
    c = anon(app)
    assert banner_shown(c.get("/"))
    r = c.post("/legal/cookies/consent", data={"choice": "essential", "next": "/auctions/"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/auctions/")
    assert not banner_shown(c.get("/")) and not banner_shown(c.get("/auctions/"))


@pytest.mark.parametrize("choice", legal.CONSENT_CHOICES)
def test_the_choice_is_stored_in_a_safe_cookie(app, choice):
    r = anon(app).post("/legal/cookies/consent", data={"choice": choice})
    cookie = next(h for h in r.headers.getlist("Set-Cookie") if h.startswith(legal.CONSENT_COOKIE))
    assert f"{legal.CONSENT_COOKIE}={legal.POLICY_VERSION}:{choice}" in cookie
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and f"Max-Age={legal.CONSENT_MAX_AGE}" in cookie
    assert "Secure" not in cookie  # plain-http development


def test_the_cookie_is_secure_when_the_site_is_configured_for_https(app):
    app.config["SESSION_COOKIE_SECURE"] = True
    r = anon(app).post("/legal/cookies/consent", data={"choice": "all"})
    assert "Secure" in next(h for h in r.headers.getlist("Set-Cookie") if h.startswith(legal.CONSENT_COOKIE))


@pytest.mark.parametrize("value", ["", "x", "all", "essential", "1999-01-01:all", f"{legal.POLICY_VERSION}:maybe", f"{legal.POLICY_VERSION}:", ":all", "a:b:c"])
def test_a_missing_old_or_forged_cookie_means_the_banner_asks_again(app, value):
    c = anon(app)
    c.set_cookie(legal.CONSENT_COOKIE, value)
    assert banner_shown(c.get("/"))


def test_a_valid_cookie_from_the_current_version_hides_the_banner(app):
    for choice in legal.CONSENT_CHOICES:
        c = anon(app)
        c.set_cookie(legal.CONSENT_COOKIE, f"{legal.POLICY_VERSION}:{choice}")
        assert not banner_shown(c.get("/"))


def test_an_invalid_choice_sets_nothing(app):
    c = anon(app)
    for bad in (None, "", "ALL", "all ", "none", "<script>"):
        r = c.post("/legal/cookies/consent", data={} if bad is None else {"choice": bad})
        assert r.status_code == 302
        assert not any(h.startswith(legal.CONSENT_COOKIE) for h in r.headers.getlist("Set-Cookie"))
    assert banner_shown(c.get("/"))


@pytest.mark.parametrize("target", ["https://evil.example", "//evil.example", "///evil.example", "http:evil.example", "javascript:alert(1)", "\\\\evil.example"])
def test_the_banner_cannot_be_used_as_an_open_redirect(app, target):
    r = anon(app).post("/legal/cookies/consent", data={"choice": "all", "next": target})
    assert "evil" not in r.headers["Location"].split("?")[0].replace("/legal/cookies", "") and r.headers["Location"].startswith("/")


def test_the_banner_works_without_javascript_and_is_accessible(app):
    html = anon(app).get("/").data.decode()
    banner = html[html.index('aria-label="Cookie notice"'):]
    banner = banner[:banner.index("</section>")]
    assert "<form" in banner and 'method="post"' in banner and 'name="csrf_token"' in banner and "<script" not in banner
    assert 'value="essential"' in banner and 'value="all"' in banner  # declining is exactly as easy as accepting
    assert "/legal/cookies" in banner and "/legal/privacy" in banner
    assert audit(html).problems == []


def test_the_banner_keeps_the_page_and_query_you_were_on(app):
    html = anon(app).get("/auctions/?q=lamp&sort=newest").data.decode()
    assert re.search(r'name="next" value="/auctions/\?q=lamp&amp;sort=newest"', html)


def test_the_banner_also_shows_on_error_pages_and_signed_in_pages(app, users):
    assert banner_shown(anon(app).get("/definitely-not-a-page"))
    assert banner_shown(client_for(app, "buyer@t.test").get("/buyer/"))


def test_the_cookie_page_shows_and_changes_the_current_choice(app):
    c = anon(app)
    assert b"You have not chosen yet" in c.get("/legal/cookies").data
    c.post("/legal/cookies/consent", data={"choice": "essential", "next": "/legal/cookies"})
    assert b"Essential only</strong>" in c.get("/legal/cookies").data
    c.post("/legal/cookies/consent", data={"choice": "all", "next": "/legal/cookies"})
    assert b"Accept all</strong>" in c.get("/legal/cookies").data


# ---- registration ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("value", [None, "", "false"])
def test_registration_needs_the_terms_box_ticked(client, value):
    data = {k: v for k, v in REG.items() if k != "accept_terms"}
    if value is not None:
        data["accept_terms"] = value
    r = client.post("/auth/register", data=data)
    assert r.status_code == 200 and b"You must agree to continue." in r.data
    assert User.query.filter_by(email=REG["email"]).first() is None


def test_registration_records_which_version_was_accepted_and_when(client):
    r = client.post("/auth/register", data=REG)
    assert r.status_code == 302
    u = User.query.filter_by(email=REG["email"]).one()
    assert u.consent_version == legal.POLICY_VERSION and u.consented_at is not None


def test_the_registration_form_links_to_the_policies_and_labels_the_box(client):
    html = client.get("/auth/register").data.decode()
    for path in ("/legal/terms", "/legal/privacy", "/legal/cookies"):
        assert path in html
    assert 'name="accept_terms"' in html and 'type="checkbox"' in html
    assert audit(html).problems == []
    assert "checked" not in re.search(r'<input[^>]*name="accept_terms"[^>]*>', html).group(0)  # never pre-ticked


def test_accounts_created_by_the_seed_script_predate_consent(app, users):
    assert users["buyer"].consent_version is None  # existing accounts keep NULL: nothing is claimed about them


# ---- feedback ----------------------------------------------------------------------------------------------
def test_feedback_needs_consent(app, users):
    c = client_for(app, "buyer@t.test")
    msg = "The browse page is great but search could be faster."
    r = c.post("/feedback", data={"message": msg})
    assert r.status_code == 200 and b"You must agree to continue." in r.data and Feedback.query.count() == 0
    assert c.post("/feedback", data={"message": msg, "consent": "y"}).status_code == 302
    assert Feedback.query.count() == 1


# ---- payments ----------------------------------------------------------------------------------------------
def test_a_simulated_payment_needs_the_refund_policy_box(app, users, cats):  # noqa: F811
    a = won(users, cats)
    c = client_for(app, "buyer@t.test")
    r = c.post(f"/payments/{a.id}/pay/card", data=card())  # no "accept"
    assert r.status_code == 400 and b"You must agree to continue." in r.data
    assert Payment.query.one().payment_method is None and Payment.query.one().attempts == 0
    assert pay(c, a, "card", card()).status_code == 302
    assert Payment.query.one().payment_status == "successful"


@pytest.mark.parametrize("kind,data", [("upi", {"upi_id": "bella@okbank"}), ("wallet", {"provider": "Demo Wallet", "mobile": "9876543210"})])
def test_every_simulated_method_needs_it_not_just_cards(app, users, cats, kind, data):  # noqa: F811
    a = won(users, cats)
    c = client_for(app, "buyer@t.test")
    assert c.post(f"/payments/{a.id}/pay/{kind}", data=data).status_code == 400
    assert Payment.query.one().payment_method is None
    assert pay(c, a, kind, data).status_code == 302 and Payment.query.one().payment_method == "simulated"


def test_the_payment_page_has_a_labelled_unique_box_per_method_and_links_the_policy(app, users, cats):  # noqa: F811
    a = won(users, cats)
    html = client_for(app, "buyer@t.test").get(f"/payments/{a.id}").data.decode()
    ids = re.findall(r'<input[^>]*type="checkbox"[^>]*id="(accept-[a-z]+)"', html) or re.findall(r'id="(accept-[a-z]+)"[^>]*type="checkbox"', html)
    assert sorted(ids) == ["accept-card", "accept-upi", "accept-wallet"]
    assert "/legal/refunds" in html
    assert audit(html).problems == []


def test_crypto_prepare_refuses_without_the_acknowledgement_before_doing_anything(app, users, cats):  # noqa: F811
    a = won(users, cats)
    c = client_for(app, "buyer@t.test")
    url = f"/payments/{a.id}/crypto/prepare"
    for body in ({"wallet_address": "0x" + "1" * 40}, {"wallet_address": "0x" + "1" * 40, "accept_terms": False},
                 {"wallet_address": "0x" + "1" * 40, "accept_terms": "true"}, {"wallet_address": "0x" + "1" * 40, "accept_terms": 1}):
        r = c.post(url, json=body)
        assert r.status_code == 400 and r.json["ok"] is False and "Refund Policy" in r.json["error"], body
    assert CryptoPayment.query.count() == 0
    # with it, the request gets as far as the crypto service (which is not configured in this fixture)
    assert c.post(url, json={"wallet_address": "0x" + "1" * 40, "accept_terms": True}).status_code == 503


# ---- selling and bidding -----------------------------------------------------------------------------------
def test_listing_a_product_needs_the_seller_declaration(app, users, cats):  # noqa: F811
    c = client_for(app, "seller@t.test")
    data = form_data(cats["Books"])
    del data["accept"]
    r = c.post("/seller/products/new", data=data, content_type="multipart/form-data")
    assert r.status_code == 200 and b"You must agree to continue." in r.data and Product.query.count() == 0
    assert post_new(c, cats["Books"]).status_code == 302 and Product.query.count() == 1


def test_editing_a_listing_needs_the_declaration_again(app, users, cats):  # noqa: F811
    c = client_for(app, "seller@t.test")
    post_new(c, cats["Books"])
    p = Product.query.one()
    data = form_data(cats["Books"], title="Renamed book")
    del data["accept"]
    r = c.post(f"/seller/products/{p.id}/edit", data=data, content_type="multipart/form-data")
    assert r.status_code == 200 and b"You must agree to continue." in r.data
    db.session.expire_all()
    assert db.session.get(Product, p.id).title == "Old Book"


def test_the_bid_form_tells_buyers_that_a_bid_is_binding(app, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "Lamp", 100)
    html = client_for(app, "buyer@t.test").get(f"/auctions/{a.id}").data.decode()
    assert "a bid is binding" in html and "/legal/terms#bidding" in html
    assert 'id="bidding"' in anon(app).get("/legal/terms").data.decode()
    assert 'id="selling"' in anon(app).get("/legal/terms").data.decode()
