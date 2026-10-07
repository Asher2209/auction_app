"""Phase 5: the seller's path from a verified, token-backed card to a live auction, enforced on the server."""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Auction, Notification, Product, User, utcnow
from app.services import auction_service
from app.services import card_auction_service as cas

from .conftest import login, make_user
from .test_listing_validation import WALLET_A, WALLET_B, cat, card_type, make_card, seller  # noqa: F401 (fixtures)
from .test_minting import chain, mint_through_flow, verified_asset  # noqa: F401 (fixtures)

FMT = "%Y-%m-%dT%H:%M"


def ready_card(seller, cat, card_type, **kw):
    """A verified card with a blockchain identity owned by the seller, approved by the admin."""
    p = make_card(seller, cat, card_type, **kw)
    p.approval_status = "approved"
    db.session.commit()
    return p


def form(**over):
    data = {"starting_bid": "500", "duration_hours": "168", "start_time": "", "confirm_ownership": "y"}
    data.update(over)
    return data


def create(client, product, **over):
    return client.post(f"/seller/cards/{product.collectible_card.id}/auction", data=form(**over))


@pytest.fixture
def as_seller(client, users, seller):
    login(client, "seller@t.test")
    return client


def auctions():
    return Auction.query.all()


# ---- the happy path ---------------------------------------------------------------------------------------
def test_seller_creates_an_auction_for_a_verified_card(as_seller, users, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    before = utcnow()
    r = create(as_seller, p)
    (a,) = auctions()
    assert r.status_code == 302 and r.location.endswith(f"/auctions/{a.id}")
    assert a.product_id == p.id and a.status == "active" and a.current_bid == Decimal("500") and a.highest_bidder_id is None
    assert a.end_time - a.start_time == timedelta(days=7) and a.original_end_time == a.end_time
    assert before - timedelta(seconds=5) <= a.start_time <= utcnow() + timedelta(seconds=5)
    assert db.session.get(Product, p.id).starting_price == Decimal("500")
    assert "Auction created" in [n.title for n in Notification.query.filter_by(user_id=users["seller"].id)]


def test_a_future_start_time_schedules_the_auction(as_seller, users, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    create(as_seller, p, start_time=(utcnow() + timedelta(hours=3)).strftime(FMT), duration_hours="24")
    (a,) = auctions()
    assert a.status == "scheduled" and a.end_time - a.start_time == timedelta(days=1)


def test_the_new_auction_accepts_bids_and_refuses_the_seller(as_seller, users, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    create(as_seller, p)
    (a,) = auctions()
    with pytest.raises(auction_service.BidError, match="minimum"):
        auction_service.place_bid(a.id, users["buyer"], "499")
    assert auction_service.place_bid(a.id, users["buyer"], "500").bid.amount == Decimal("500")
    with pytest.raises(auction_service.BidError):
        auction_service.place_bid(a.id, users["seller"], "900")


def test_the_public_auction_page_renders_for_a_card_auction(as_seller, client, users, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    create(as_seller, p)
    (a,) = auctions()
    client.post("/auth/logout")
    assert client.get(f"/auctions/{a.id}").status_code == 200


# ---- the gate: a card that fails any rule is never listed ------------------------------------------------------
@pytest.mark.parametrize("kwargs, words", [
    ({"verified": False}, "verified"),
    ({"asset": False}, "blockchain identity"),
    ({"owner": WALLET_B}, "registered owner"),
    ({"status": "transferred", "token_id": 9}, "transferred"),
])
def test_an_unlistable_card_is_refused_and_no_auction_exists(as_seller, users, cat, card_type, kwargs, words):
    p = ready_card(users["seller"], cat, card_type, **kwargs)
    r = create(as_seller, p)
    assert r.status_code == 409 and words in r.get_data(as_text=True)
    assert auctions() == []


def test_a_seller_without_a_wallet_is_refused(as_seller, users, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    users["seller"].wallet_address = None
    db.session.commit()
    assert create(as_seller, p).status_code == 409 and auctions() == []


def test_a_card_whose_certificate_is_already_in_a_live_auction_is_refused(as_seller, users, cat, card_type):
    ready_card(users["seller"], cat, card_type, auction_status="active", cert="555")
    second = ready_card(users["seller"], cat, card_type, cert="555")
    r = create(as_seller, second)
    assert r.status_code == 409 and "already in an active auction" in r.get_data(as_text=True)
    assert second.auction is None and len(auctions()) == 1


def test_a_listing_the_admin_has_not_approved_is_refused(as_seller, users, cat, card_type):
    p = make_card(users["seller"], cat, card_type)  # verified, but the product is still "pending"
    assert create(as_seller, p).status_code == 409 and auctions() == []


def test_a_second_request_cannot_create_a_second_auction(as_seller, users, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    first = create(as_seller, p)
    second = create(as_seller, p)
    assert first.status_code == 302 and second.status_code == 302 and len(auctions()) == 1


def test_the_service_refuses_a_duplicate_even_if_the_page_is_bypassed(users, cat, card_type, seller):
    p = ready_card(users["seller"], cat, card_type)
    cas.create_card_auction(p, users["seller"], "500", None, 24)
    with pytest.raises(cas.CardAuctionError) as e:
        cas.create_card_auction(p, users["seller"], "500", None, 24)
    assert e.value.status == 409 and len(auctions()) == 1


# ---- who may do it -----------------------------------------------------------------------------------------------
def test_only_the_owning_seller_can_create_the_auction(client, users, seller, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    url = f"/seller/cards/{p.collectible_card.id}/auction"
    assert client.post(url, data=form()).status_code == 302  # anonymous: sent to log in
    login(client, "buyer@t.test")
    assert client.post(url, data=form()).status_code == 403
    client.post("/auth/logout")
    make_user("other@t.test", "seller")
    login(client, "other@t.test")
    assert client.get(url).status_code == 404 and client.post(url, data=form()).status_code == 404
    assert auctions() == []


def test_the_service_refuses_another_user_and_non_cards(users, cat, card_type, seller):
    p = ready_card(users["seller"], cat, card_type)
    with pytest.raises(cas.CardAuctionError) as e:
        cas.create_card_auction(p, users["buyer"], "500", None, 24)
    assert e.value.status == 403
    plain = Product(seller_id=users["seller"].id, category_id=cat.id, title="Book", description="d" * 12,
                    starting_price=Decimal("5"), auction_start=utcnow(), auction_end=utcnow() + timedelta(days=1),
                    approval_status="approved")
    db.session.add(plain)
    db.session.commit()
    with pytest.raises(cas.CardAuctionError, match="trading cards"):
        cas.create_card_auction(plain, users["seller"], "500", None, 24)
    assert auctions() == []


# ---- input is never trusted -------------------------------------------------------------------------------------
@pytest.mark.parametrize("bid", ["0", "0.99", "-5", "abc", "", "1e3", "nan", "inf", "100.123", "10000001", "99999999999"])
def test_bad_starting_bids_create_nothing(as_seller, users, cat, card_type, bid):
    p = ready_card(users["seller"], cat, card_type)
    assert create(as_seller, p, starting_bid=bid).status_code in (200, 400)
    assert auctions() == []


def test_the_page_cannot_be_submitted_without_confirming_ownership(as_seller, users, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    data = form()
    del data["confirm_ownership"]
    as_seller.post(f"/seller/cards/{p.collectible_card.id}/auction", data=data)
    assert auctions() == []


def test_a_forged_duration_choice_is_refused(as_seller, users, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    for bad in ("0", "-1", "99999", "abc"):
        create(as_seller, p, duration_hours=bad)
    assert auctions() == []


@pytest.mark.parametrize("hours", [0, -3, 721, 10_000, True, "24", 1.5, None])
def test_the_service_enforces_the_duration_limits(users, cat, card_type, seller, hours):
    p = ready_card(users["seller"], cat, card_type)
    with pytest.raises(cas.CardAuctionError):
        cas.create_card_auction(p, users["seller"], "500", None, hours)
    assert auctions() == []


def test_the_service_enforces_the_start_window(users, cat, card_type, seller):
    p = ready_card(users["seller"], cat, card_type)
    for start in (utcnow() - timedelta(hours=1), utcnow() + timedelta(days=31)):
        with pytest.raises(cas.CardAuctionError):
            cas.create_card_auction(p, users["seller"], "500", start, 24)
    assert auctions() == []
    a = cas.create_card_auction(p, users["seller"], "500", utcnow() - timedelta(minutes=2), 24)  # inside the grace
    assert a.status == "active" and a.start_time >= utcnow() - timedelta(seconds=5)


# ---- the generic product routes cannot be used to dodge the card rules -------------------------------------------
def test_a_card_cannot_be_edited_or_deleted_through_the_generic_product_routes(as_seller, users, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    card_page = f"/seller/cards/{p.collectible_card.id}"
    for r in (as_seller.get(f"/seller/products/{p.id}/edit"), as_seller.post(f"/seller/products/{p.id}/edit", data={}),
              as_seller.post(f"/seller/products/{p.id}/delete")):
        assert r.status_code == 302 and r.location.endswith(card_page)
    assert db.session.get(Product, p.id) is not None and db.session.get(Product, p.id).approval_status == "approved"


def test_the_generic_routes_still_work_for_ordinary_products(as_seller, users, cat):
    plain = Product(seller_id=users["seller"].id, category_id=cat.id, title="Book", description="d" * 12,
                    starting_price=Decimal("5"), auction_start=utcnow() + timedelta(hours=1),
                    auction_end=utcnow() + timedelta(days=1), approval_status="pending")
    db.session.add(plain)
    db.session.commit()
    assert as_seller.get(f"/seller/products/{plain.id}/edit").status_code == 200
    assert as_seller.post(f"/seller/products/{plain.id}/delete").status_code == 302
    assert db.session.get(Product, plain.id) is None


# ---- the seller's card page ------------------------------------------------------------------------------------
def test_card_page_offers_the_auction_when_listable(as_seller, users, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    html = as_seller.get(f"/seller/cards/{p.collectible_card.id}").get_data(as_text=True)
    assert f"/seller/cards/{p.collectible_card.id}/auction" in html and "Create auction" in html


def test_card_page_explains_why_a_card_cannot_be_listed(as_seller, users, cat, card_type):
    p = ready_card(users["seller"], cat, card_type, verified=False)
    html = as_seller.get(f"/seller/cards/{p.collectible_card.id}").get_data(as_text=True)
    assert "cannot be listed yet" in html and "not been platform verified" in html
    assert f"/seller/cards/{p.collectible_card.id}/auction" not in html
    page = as_seller.get(f"/seller/cards/{p.collectible_card.id}/auction").get_data(as_text=True)
    assert "cannot be listed yet" in page and "Create auction</button>" not in page


def test_card_page_links_to_the_auction_once_it_exists(as_seller, users, cat, card_type):
    p = ready_card(users["seller"], cat, card_type)
    create(as_seller, p)
    (a,) = auctions()
    html = as_seller.get(f"/seller/cards/{p.collectible_card.id}").get_data(as_text=True)
    assert f"/auctions/{a.id}" in html and "View auction" in html and "Create auction" not in html


# ---- against a real chain ------------------------------------------------------------------------------------------
def minted_card(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    asset.collectible_card.product.approval_status = "approved"
    db.session.commit()
    mint_through_flow(asset, chain)
    return asset


def test_a_minted_card_is_listed_when_the_chain_confirms_the_owner(app, as_seller, users, cat, card_type, chain):
    app.config["LISTING_REQUIRES_MINTED_TOKEN"] = True
    asset = minted_card(users["seller"], cat, card_type, chain)
    assert create(as_seller, asset.collectible_card.product).status_code == 302
    assert len(auctions()) == 1


def test_a_token_moved_to_someone_else_cannot_be_listed(app, as_seller, users, cat, card_type, chain):
    asset = minted_card(users["seller"], cat, card_type, chain)
    chain.contract.functions.transferFrom(chain.seller_wallet, chain.stranger, asset.token_id).transact(
        {"from": chain.seller_wallet})
    r = create(as_seller, asset.collectible_card.product)
    assert r.status_code == 409 and "OWNERSHIP SYNC ERROR" in r.get_data(as_text=True)
    assert auctions() == [] and asset.owner_wallet == chain.seller_wallet  # flagged, never silently rewritten


def test_an_unreachable_chain_blocks_listing_in_strict_mode_only(app, as_seller, users, cat, card_type, chain):
    asset = minted_card(users["seller"], cat, card_type, chain)
    product = asset.collectible_card.product
    del app.extensions["web3"]
    app.config["RPC_URL"] = None
    app.config["LISTING_REQUIRES_MINTED_TOKEN"] = True
    assert create(as_seller, product).status_code == 409 and auctions() == []
    app.config["LISTING_REQUIRES_MINTED_TOKEN"] = False
    assert create(as_seller, product).status_code == 302 and len(auctions()) == 1
