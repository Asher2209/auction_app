"""Phase 8: the collector-facing pages, and regression tests for the bugs found while reviewing them."""
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.extensions import db
from app.models import Auction, Bid, CardImage, Product, utcnow

from .conftest import login
from .test_listing_validation import WALLET_A, cat, card_type, make_card, seller  # noqa: F401 (fixtures)

ROOT = Path(__file__).resolve().parent.parent


_tokens = iter(range(11, 1000))


def listed(seller, cat, card_type, status="active", verified=True, **kw):
    """A card with a live auction, approved so the public pages can show it, with a front image."""
    p = make_card(seller, cat, card_type, verified=verified, auction_status=status, status="minted", token_id=next(_tokens), **kw)
    p.approval_status = "approved"
    card = p.collectible_card
    card.set_name, card.release_year, card.card_number, card.grade = "Base Set", 1999, "4/102", "PSA 9"
    db.session.add(CardImage(collectible_card_id=card.id, image_type="front", path="products/front-photo.png"))
    db.session.commit()
    return p


def page(client, url):
    r = client.get(url)
    assert r.status_code == 200, f"{url} returned {r.status_code}"
    return r.get_data(as_text=True)


# ---- the card image URL (it used to be a bare file name, so every card page showed a broken image) ------------------------
def test_an_uploaded_card_image_is_served_from_the_uploads_folder(app):
    with app.test_request_context():
        assert CardImage(path="products/a.png").get_image_src() == "/static/uploads/products/a.png"
        assert CardImage(url="https://example.org/a.png", path="ignored.png").get_image_src() == "https://example.org/a.png"
        assert CardImage().get_image_src() is None


# ---- the card auction page ------------------------------------------------------------------------------------------------
def test_the_auction_page_keeps_the_live_bidding_contract(client, users, seller, cat, card_type):
    a = listed(users["seller"], cat, card_type).auction
    login(client, "buyer@t.test")
    html = page(client, f"/auctions/{a.id}")
    assert f'id="auction-live"' in html and f'data-auction-id="{a.id}"' in html and "data-end=" in html
    for element in ("current-bid", "bid-count", "countdown", "bid-form", "bid-rows", "status-badge", "live-indicator", "winner-box", "notice"):
        assert f'id="{element}"' in html, element
    assert "js/auction.js" in html  # without this script nothing on the page updates live


def test_the_auction_page_uses_working_image_urls_and_no_inline_handlers(client, users, seller, cat, card_type):
    a = listed(users["seller"], cat, card_type).auction
    html = page(client, f"/auctions/{a.id}")
    assert 'id="gallery-main" src="/static/uploads/products/front-photo.png"' in html
    assert not re.search(r"\son(click|change|load|error|submit)=", html)  # handlers belong in script files


def test_the_auction_page_shows_the_card_identity_in_separate_labelled_panels(client, users, seller, cat, card_type):
    a = listed(users["seller"], cat, card_type, cert="12345678").auction
    html = page(client, f"/auctions/{a.id}")
    for heading in ("Card details", "Condition &amp; grading", "Platform verification", "Blockchain identity"):
        assert heading in html, heading
    assert "Base Set" in html and "4/102" in html and "12345678" in html
    assert "Platform verified" in html and "not a guarantee" in html and "Seller provided" in html
    assert f"#{a.product.collectible_card.blockchain_asset.token_id}" in html and "Not registered" not in html
    assert f"/collectibles/card-verification/{a.product.collectible_card.platform_card_id}" in html


def test_an_unverified_card_is_not_presented_as_verified(client, users, seller, cat, card_type):
    a = listed(users["seller"], cat, card_type, verified=False).auction
    html = page(client, f"/auctions/{a.id}")
    assert "Not platform verified" in html and "Platform verified" not in html.replace("Not platform verified", "")


def test_the_bid_history_names_bidders_safely_and_shows_the_time(client, users, seller, cat, card_type):
    a = listed(users["seller"], cat, card_type).auction
    db.session.add(Bid(auction_id=a.id, buyer_id=users["buyer"].id, amount=Decimal("150"), bid_time=utcnow()))
    db.session.commit()
    anonymous = page(client, f"/auctions/{a.id}")
    assert "buyer" not in anonymous.split('id="bid-rows"')[1].split("</tbody>")[0]  # the name is masked, not printed
    login(client, "buyer@t.test")
    mine = page(client, f"/auctions/{a.id}").split('id="bid-rows"')[1].split("</tbody>")[0]
    assert "<strong>You</strong>" in mine and "UTC" in mine


def test_the_auction_page_has_no_invented_seller_facts(client, users, seller, cat, card_type):
    html = page(client, f"/auctions/{listed(users['seller'], cat, card_type).auction.id}")
    assert "Within 24 hours" not in html and "Response time" not in html


def test_the_watchlist_button_is_a_real_form(client, users, seller, cat, card_type):
    a = listed(users["seller"], cat, card_type).auction
    login(client, "buyer@t.test")
    html = page(client, f"/auctions/{a.id}")
    assert f'action="/buyer/watchlist/{a.id}/toggle"' in html and "Add to watchlist" in html
    client.post(f"/buyer/watchlist/{a.id}/toggle")
    assert "Remove from watchlist" in page(client, f"/auctions/{a.id}")


def test_an_ordinary_product_auction_still_renders_without_card_panels(client, users, cat):
    start = utcnow() - timedelta(hours=1)
    product = Product(seller_id=users["seller"].id, category_id=cat.id, title="Old book", description="d" * 12,
                      starting_price=Decimal("100"), auction_start=start, auction_end=start + timedelta(days=2), approval_status="approved")
    db.session.add(product)
    db.session.commit()
    auction = Auction(product_id=product.id, start_time=start, end_time=start + timedelta(days=2), original_end_time=start + timedelta(days=2),
                      current_bid=Decimal("100"), status="active")
    db.session.add(auction)
    db.session.commit()
    html = page(client, f"/auctions/{auction.id}")
    assert "Old book" in html and "Card details" not in html and 'id="auction-live"' in html


# ---- the public QR page (it used to return HTTP 500 for any card that was in an auction) ------------------------------------
def test_the_public_page_works_for_a_card_in_a_live_auction(client, users, seller, cat, card_type):
    p = listed(users["seller"], cat, card_type)
    html = page(client, f"/collectibles/card-verification/{p.collectible_card.platform_card_id}")
    assert "Current auction" in html and "Live now" in html and f'href="/auctions/{p.auction.id}"' in html


def test_the_public_page_works_for_a_scheduled_auction(client, users, seller, cat, card_type):
    p = listed(users["seller"], cat, card_type, status="scheduled")
    assert "Upcoming" in page(client, f"/collectibles/card-verification/{p.collectible_card.platform_card_id}")


def test_the_public_page_shows_the_card_identity_and_the_distinctions(client, users, seller, cat, card_type):
    p = listed(users["seller"], cat, card_type, cert="12345678")
    html = page(client, f"/collectibles/card-verification/{p.collectible_card.platform_card_id}")
    for text in ("Card details", "Blockchain Identity", "Seller provided", "Platform review", "not a guarantee",
                 f"#{p.collectible_card.blockchain_asset.token_id}"):
        assert text in html, text
    assert "100% authentic" not in html.lower()


# ---- the marketplace tile -------------------------------------------------------------------------------------------------------
def test_the_marketplace_tile_leads_with_the_card(client, users, seller, cat, card_type):
    listed(users["seller"], cat, card_type)
    html = page(client, "/auctions/")
    tile = html.split('class="cc ')[1].split("</a>")[0]
    assert 'class="cc-media"' in tile and "cc-name" in tile and "Base Set &middot; 1999 &middot; #4/102" in tile
    for text in ("PSA 9 &middot; Near Mint", "Starting at", "0 bids", "left"):  # nobody has bid yet
        assert text in tile, text
    assert "/static/uploads/products/front-photo.png" in tile


def test_only_a_verified_card_gets_the_verified_badge(client, users, seller, cat, card_type):
    listed(users["seller"], cat, card_type, verified=True)
    listed(users["seller"], cat, card_type, verified=False)
    html = page(client, "/auctions/")
    assert html.count('class="cc-badge"') == 1 and html.count('class="cc ') == 2


# ---- guards for the visual direction and the layout bugs ---------------------------------------------------------------------------
LIVE_CSS = ("design-tokens", "theme", "components", "layouts", "style", "modern-ui", "cookies")
PURPLE = re.compile(r"8b5cf6|a78bfa|7c3aed|6d28d9|139,\s*92,\s*246|109,\s*40,\s*217", re.I)


def test_no_purple_remains_in_the_live_styles_or_templates():
    files = [ROOT / "app" / "static" / "css" / f"{name}.css" for name in LIVE_CSS] + list((ROOT / "app" / "templates").rglob("*.html"))
    offenders = [str(f.relative_to(ROOT)) for f in files if PURPLE.search(f.read_text(encoding="utf-8", errors="ignore"))]
    assert offenders == []


def test_no_glow_or_gradient_on_the_new_components():
    css = (ROOT / "app" / "static" / "css" / "components.css").read_text(encoding="utf-8")
    block = css[css.index("Collectible card tile"):]
    assert "box-shadow" not in block and "gradient" not in block and "backdrop-filter" not in block


def test_the_stacked_layout_releases_the_sticky_gallery_after_the_base_rule():
    css = (ROOT / "app" / "static" / "css" / "layouts.css").read_text(encoding="utf-8")
    base = css.index("position: sticky")
    release = css.index("position: static", base)  # a media rule placed before the base rule would never win
    assert "@media (max-width: 1024px)" in css[base:release]


def test_the_unauthenticated_debug_route_is_gone(client):
    assert client.get("/seller/cards/debug").status_code == 404


# =================================== buyer: My cards ===========================================================================
from app.models import BlockchainAsset, Payment, Winner  # noqa: E402
from app.services import payment_service  # noqa: E402

from .conftest import make_user  # noqa: E402
from .test_card_settlement import PRICE_INR, as_buyer, authorize_on_chain, pay, pay_url, s, sold_card  # noqa: E402,F401
from .test_minting import chain  # noqa: E402,F401 (fixture)


def test_my_cards_shows_a_purchase_with_its_token_transaction_and_invoice(client, users, chain, s):
    authorize_on_chain(client, chain, s)
    tx_hash = pay(client, chain, s)
    as_buyer(client)
    html = page(client, "/buyer/cards").split('id="my-cards"')[1]
    assert s.card.card_name in html and f"{PRICE_INR:,.2f}" in html and "#1" in html and "Yours on the blockchain" in html
    assert tx_hash[:10] in html and f"/invoices/{s.auction.id}/download" in html and f"Auction #{s.auction.id}" in html


def test_my_cards_shows_a_card_still_being_paid_for(client, users, chain, s):
    as_buyer(client)
    html = page(client, "/buyer/cards")
    assert "Payment pending" in html and "Pay now" in html and pay_url(s) in html and "Yours on the blockchain" not in html


def test_my_cards_says_so_when_a_card_was_paid_without_a_token_transfer(client, users, chain, s):
    payment_service.pay_simulated(s.auction.id, users["buyer"], "card",
                                  {"card_holder": "A Buyer", "card_number": "4242 4242 4242 4242", "expiry": "12/30", "cvv": "123"})
    as_buyer(client)
    html = page(client, "/buyer/cards")
    assert "Paid. No token transfer recorded" in html and "Yours on the blockchain" not in html


def test_my_cards_lists_a_token_the_wallet_holds_even_if_it_was_not_won_here(client, users, seller, cat, card_type):
    users["buyer"].link_wallet(WALLET_A.replace("a1", "d4"))
    p = make_card(users["seller"], cat, card_type, status="minted", token_id=77, owner=users["buyer"].wallet_address)
    db.session.commit()
    login(client, "buyer@t.test")
    html = page(client, "/buyer/cards")
    assert p.collectible_card.card_name in html and "#77" in html and "Yours on the blockchain" in html


def test_my_cards_asks_for_a_wallet_when_there_is_none(client, users):
    login(client, "buyer@t.test")
    html = page(client, "/buyer/cards")
    assert "Verify a wallet" in html and "do not own any cards yet" in html


def test_my_cards_is_private_to_the_buyer(client, users, chain, s):
    authorize_on_chain(client, chain, s)
    pay(client, chain, s)
    client.post("/auth/logout")
    make_user("rival@t.test", "buyer")
    login(client, "rival@t.test")
    assert s.card.card_name not in page(client, "/buyer/cards")
    client.post("/auth/logout")
    login(client, "seller@t.test")
    assert client.get("/buyer/cards").status_code == 403
    client.post("/auth/logout")
    assert client.get("/buyer/cards").status_code == 302


# =================================== seller: My cards ==========================================================================
def inventory(users, cat, card_type):
    """One card per lifecycle group, plus a card that belongs to somebody else."""
    seller, buyer = users["seller"], users["buyer"]
    cards = {}
    cards["awaiting"] = make_card(seller, cat, card_type, verified=False, asset=False)
    cards["more_info"] = make_card(seller, cat, card_type, verified=False, asset=False)
    cards["more_info"].collectible_verification.verification_status = "more_info_needed"
    cards["rejected"] = make_card(seller, cat, card_type, verified=False, asset=False)
    cards["rejected"].collectible_verification.verification_status = "rejected"
    cards["verified"] = make_card(seller, cat, card_type)
    cards["approved"] = make_card(seller, cat, card_type, status="minted", token_id=501)
    cards["approved"].approval_status = "approved"
    cards["auction"] = make_card(seller, cat, card_type, status="minted", token_id=502, auction_status="active")
    cards["ended"] = make_card(seller, cat, card_type, auction_status="closed")
    cards["unpaid"] = make_card(seller, cat, card_type, status="minted", token_id=503, auction_status="closed", winner=buyer)
    cards["sold"] = make_card(seller, cat, card_type, status="minted", token_id=504, auction_status="closed", winner=buyer)
    for key, outcome in (("unpaid", "pending"), ("sold", "successful")):
        db.session.add(Payment(auction_id=cards[key].auction.id, buyer_id=buyer.id, amount=Decimal("100"), payment_status=outcome))
    other = make_user("other@t.test", "seller")
    make_card(other, cat, card_type, verified=False, asset=False)
    db.session.commit()
    return cards


def tabs(html):
    return {label.strip(): int(n) for label, n in re.findall(r'nav-link[^>]*>([^<(]+)<span class="text-muted">\((\d+)\)', html)}


def rows(html):
    return re.findall(r'<a href="/seller/cards/\d+">([^<]+)</a>', html.split('id="seller-cards"')[1].split("</table>")[0])


def test_the_seller_dashboard_counts_every_group(client, users, seller, cat, card_type):
    inventory(users, cat, card_type)
    login(client, "seller@t.test")
    assert tabs(page(client, "/seller/collectibles")) == {
        "All cards": 9, "Awaiting verification": 1, "More information required": 1, "Verified": 2, "Rejected": 1,
        "Active auctions": 1, "Completed auctions": 2, "Sold": 1}


@pytest.mark.parametrize("group, expected", [("awaiting", 1), ("pending", 1), ("more_info", 1), ("verified", 2), ("rejected", 1),
                                              ("auction", 1), ("completed", 2), ("sold", 1), ("all", 9), ("nonsense", 9)])
def test_each_group_shows_only_its_cards(client, users, seller, cat, card_type, group, expected):
    inventory(users, cat, card_type)
    login(client, "seller@t.test")
    assert len(rows(page(client, f"/seller/collectibles?status={group}"))) == expected


def test_each_row_offers_only_the_actions_that_apply(client, users, seller, cat, card_type):
    cards = inventory(users, cat, card_type)
    login(client, "seller@t.test")
    html = page(client, "/seller/collectibles")
    cid = lambda key: cards[key].collectible_card.id  # noqa: E731
    for key in ("verified", "approved"):
        assert f"/seller/cards/{cid(key)}/auction" in html
    for key in ("auction", "sold", "unpaid", "awaiting"):
        assert f"/seller/cards/{cid(key)}/auction" not in html
    assert f"/seller/cards/{cid('unpaid')}/sale" in html and f"/seller/cards/{cid('sold')}/sale" not in html
    for key in ("awaiting", "more_info", "rejected"):
        assert f"/seller/cards/{cid(key)}/edit" in html
    for key in ("verified", "auction", "sold"):
        assert f"/seller/cards/{cid(key)}/edit" not in html


def test_each_row_shows_the_blockchain_and_auction_state(client, users, seller, cat, card_type):
    inventory(users, cat, card_type)
    login(client, "seller@t.test")
    html = page(client, "/seller/collectibles").split('id="seller-cards"')[1]
    for text in ("Not registered", "Awaiting minting", "Token #501", "Active", "Closed", "CARD-"):
        assert text in html, text


def test_sorting_by_name_orders_the_rows(client, users, seller, cat, card_type):
    inventory(users, cat, card_type)
    login(client, "seller@t.test")
    names = rows(page(client, "/seller/collectibles?sort=name"))
    assert names == sorted(names, key=str.lower)


def test_an_empty_dashboard_invites_the_first_card_and_is_for_sellers_only(client, users):
    login(client, "seller@t.test")
    assert "Add your first card" in page(client, "/seller/collectibles")
    client.post("/auth/logout")
    login(client, "buyer@t.test")
    assert client.get("/seller/collectibles").status_code == 403


# =================================== admin dashboard ===========================================================================
def test_the_admin_dashboard_counts_cards_and_blockchain_records(client, users, seller, cat, card_type):
    make_card(users["seller"], cat, card_type, verified=False, asset=False)
    make_card(users["seller"], cat, card_type, status="minted", token_id=601, auction_status="active")
    rejected = make_card(users["seller"], cat, card_type, verified=False, asset=False)
    rejected.collectible_verification.verification_status = "rejected"
    db.session.commit()
    login(client, "admin@t.test")
    html = page(client, "/admin/").split('id="card-stats"')[1].split("Waiting for review")[0]
    tiles = dict(re.findall(r'text-muted small">([^<]+)</div>\s*<div class="fs-3 fw-semibold">(?:<a[^>]*>)?(\d+)', html))
    assert tiles["Collectible cards"] == "3" and tiles["Pending verification"] == "1" and tiles["Verified"] == "1"
    assert tiles["Rejected"] == "1" and tiles["More information required"] == "0"
    assert tiles["Card auctions live or scheduled"] == "1" and tiles["Card auctions completed"] == "0" and tiles["Cards sold and paid"] == "0"
    assert tiles["Blockchain assets"] == "1" and tiles["Tokens minted"] == "1" and tiles["Ownership transfers"] == "0"


def test_the_admin_navigation_reaches_card_verification(client, users):
    login(client, "admin@t.test")
    assert 'href="/admin/cards/verify"' in page(client, "/admin/")


# =================================== admin: reviewing a card ===================================================================
def review(client, card_product):
    return client.get(f"/admin/cards/verify/{card_product.collectible_verification.id}")


def test_an_admin_can_open_a_graded_card_for_review(client, users, seller, cat, card_type):
    p = make_card(users["seller"], cat, card_type, verified=False, asset=False, grader="PSA", cert="12345678")
    p.collectible_verification.is_graded = True  # a graded card used to be answered with HTTP 403
    db.session.commit()
    login(client, "admin@t.test")
    r = review(client, p)
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Professional Grading" in html and "12345678" in html


def test_the_review_page_shows_the_listing_facts_and_the_type_details(client, users, seller, cat, card_type):
    p = make_card(users["seller"], cat, card_type, verified=False, asset=False)
    card = p.collectible_card
    card.estimated_value = Decimal("90000")
    card.set_type_details({"player_name": "Lionel Messi", "season": "2022", "is_rookie": True, "hp": ""})
    db.session.commit()
    login(client, "admin@t.test")
    html = review(client, p).get_data(as_text=True).split('id="admin-card-facts"')[1].split("</dl>")[0]
    assert "90,000.00" in html and "100.00" in html  # estimated value and starting price
    assert "Lionel Messi" in html and "2022" in html and "Is rookie" in html and ">Yes<" in html and "Hp" not in html


def test_the_review_page_warns_about_a_shared_certificate_before_the_decision(client, users, seller, cat, card_type):
    make_card(users["seller"], cat, card_type, verified=False, asset=False, cert="777")
    p = make_card(users["seller"], cat, card_type, verified=False, asset=False, cert="777")
    login(client, "admin@t.test")
    html = review(client, p).get_data(as_text=True)
    assert 'id="admin-duplicates"' in html and "Admin review required" in html and "not proof" in html
    clean = make_card(users["seller"], cat, card_type, verified=False, asset=False, cert="888")
    assert 'id="admin-duplicates"' not in review(client, clean).get_data(as_text=True)


def test_only_an_admin_can_open_the_review_page(client, users, seller, cat, card_type):
    p = make_card(users["seller"], cat, card_type, verified=False, asset=False)
    for role in ("buyer", "seller"):
        client.post("/auth/logout")
        login(client, f"{role}@t.test")
        assert review(client, p).status_code == 403


def test_the_superseded_grader_dashboard_redirects_instead_of_failing(client, users):
    login(client, "admin@t.test")
    r = client.get("/admin/collectibles/verify")
    assert r.status_code == 302 and r.location.endswith("/admin/cards/verify")


def test_the_waiting_list_sends_a_card_to_its_checklist(client, users, seller, cat, card_type):
    p = make_card(users["seller"], cat, card_type, verified=False, asset=False)
    login(client, "admin@t.test")
    html = page(client, "/admin/")
    assert f'href="/admin/cards/verify/{p.collectible_verification.id}"' in html and f'href="/admin/products/{p.id}"' not in html
