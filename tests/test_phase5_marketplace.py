"""Phase 5, marketplace essentials.

  Bid steps ............... steps_*    (the next bid must beat the current one by a step that grows with the price)
  Automatic bidding ....... proxy_*    (a secret maximum; the site bids one step above rivals, up to it)
  Reserve price ........... reserve_*  (below it the auction ends without a sale; only "met or not" is ever shown)
  Buy It Now .............. buynow_*   (until the first bid: buying ends the auction at that price)
  Seller's listing form .. seller_*   (reserve and Buy It Now are optional, and must make sense with the starting bid)
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.extensions import db, socketio
from app.models import Auction, Bid, MaxBid, Notification, Payment, Product, Winner, utcnow
from app.services import auction_service as svc
from app.services.auction_service import BidError

from .conftest import make_user
from .test_auction import client_for
from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)
from .test_card_auction import as_seller, create, ready_card  # noqa: F401  (as_seller is a fixture)
from .test_listing_validation import card_type, cat, seller  # noqa: F401  (fixtures)

D = Decimal


@pytest.fixture
def lot(users, cats):  # noqa: F811
    """Active, starting at 100, five hours left, no bids."""
    return make_auction(users["seller"], cats["Books"], "Charizard", 100)


def fresh(a):
    db.session.expire_all()
    return db.session.get(Auction, a.id)


def history(a):
    """(bidder email, amount, automatic?) in the order the bids were recorded."""
    return [(b.buyer.email, b.amount, b.is_auto) for b in Bid.query.filter_by(auction_id=a.id).order_by(Bid.id)]


def titles(user):
    return [n.title for n in Notification.query.filter_by(user_id=user.id).order_by(Notification.id)]


# =================================== bid steps ================================================================================
@pytest.mark.parametrize("price,step", [(D("0"), D("10")), (D("499.99"), D("10")), (D("500"), D("25")), (D("2000"), D("50")),
                                        (D("5000"), D("100")), (D("20000"), D("250")), (D("100000"), D("500")), (D("9999999"), D("500"))])
def test_steps_grow_with_the_price(app, price, step):
    assert svc.bid_increment(price) == step


def test_steps_the_first_bid_may_be_the_starting_price_and_later_ones_must_add_a_step(lot, users):
    svc.place_bid(lot.id, users["buyer"], "100")
    assert svc.min_next_bid(fresh(lot)) == D("110")
    with pytest.raises(BidError, match="minimum"):
        svc.place_bid(lot.id, make_user("b2@t.test"), "109.99")


# =================================== automatic bidding ========================================================================
def test_proxy_a_maximum_answers_a_lower_bid_one_step_above_it(lot, users):
    a, b = users["buyer"], make_user("b@t.test")
    svc.place_bid(lot.id, a, "100", raw_max="300")
    result = svc.place_bid(lot.id, b, "150")
    lot = fresh(lot)
    assert lot.highest_bidder_id == a.id and lot.current_bid == D("160")  # 150 + one ₹10 step, well inside A's limit
    assert history(lot) == [(a.email, D("100"), False), (b.email, D("150"), False), (a.email, D("160"), True)]
    assert [r.amount for r in result.new_bids] == [D("150"), D("160")]
    assert "You have been outbid" in titles(b) and "Your automatic bid kept you ahead" in titles(a)


def test_proxy_a_higher_maximum_wins_one_step_above_the_other_limit(lot, users):
    a, b = users["buyer"], make_user("b@t.test")
    svc.place_bid(lot.id, a, "100", raw_max="300")
    svc.place_bid(lot.id, b, "200", raw_max="500")
    lot = fresh(lot)
    assert lot.highest_bidder_id == b.id and lot.current_bid == D("310")  # A's 300, plus a step; B never pays its 500
    assert (a.email, D("300"), True) in history(lot)  # A's limit was fought for in full
    assert "You have been outbid" in titles(a)


def test_proxy_on_equal_maximums_the_earlier_one_wins(lot, users):
    a, b = users["buyer"], make_user("b@t.test")
    svc.place_bid(lot.id, a, "100", raw_max="300")
    svc.place_bid(lot.id, b, "120", raw_max="300")
    lot = fresh(lot)
    assert lot.highest_bidder_id == a.id and lot.current_bid == D("300")


def test_proxy_a_maximum_never_goes_above_itself(lot, users):
    a, b = users["buyer"], make_user("b@t.test")
    svc.place_bid(lot.id, a, "100", raw_max="155")
    svc.place_bid(lot.id, b, "150")
    lot = fresh(lot)
    assert lot.highest_bidder_id == a.id and lot.current_bid == D("155")  # the step would be 160: capped at A's 155
    svc.place_bid(lot.id, b, "165")
    assert fresh(lot).highest_bidder_id == b.id  # A's limit is spent


def test_proxy_the_maximum_must_cover_the_bid(lot, users):
    with pytest.raises(BidError, match="at least your bid"):
        svc.place_bid(lot.id, users["buyer"], "200", raw_max="150")
    assert MaxBid.query.count() == 0 and Bid.query.count() == 0


def test_proxy_a_maximum_is_never_shown_to_anyone_else(app, lot, users):
    svc.place_bid(lot.id, users["buyer"], "100", raw_max="8765")
    rival = make_user("rival@t.test")
    page = client_for(app, "rival@t.test").get(f"/auctions/{lot.id}").get_data(as_text=True)
    state = client_for(app, "rival@t.test").get(f"/auctions/{lot.id}/state").get_data(as_text=True)
    r = client_for(app, "rival@t.test").post(f"/auctions/{lot.id}/bid", data={"amount": "150"}, headers={"Accept": "application/json"})
    for text in (page, state, r.get_data(as_text=True)):
        assert "8765" not in text and "8,765" not in text
    assert r.json["leading_bidder_id"] != rival.id and r.json["current_bid"] == "160.00"


def test_proxy_automatic_bids_are_broadcast_live_when_auction_and_product_ids_differ(app, users, cats):  # noqa: F811
    # an extra product first, so the auction's id is not its product's: joining the room once compared the wrong id
    db.session.add(Product(seller_id=users["seller"].id, category_id=cats["Books"].id, title="No auction", description="x",
                           starting_price=D("1"), approval_status="approved", auction_start=utcnow(), auction_end=utcnow()))
    db.session.commit()
    lot = make_auction(users["seller"], cats["Books"], "Charizard", 100)
    assert lot.id != lot.product_id
    viewer = socketio.test_client(app)
    viewer.emit("join", {"auction_id": lot.id})
    assert [e["name"] for e in viewer.get_received()] == ["joined"]
    svc.place_bid(lot.id, users["buyer"], "100", raw_max="300")
    make_user("b@t.test")
    client_for(app, "b@t.test").post(
        f"/auctions/{lot.id}/bid", data={"amount": "150"}, headers={"Accept": "application/json"})
    (ev,) = [e["args"][0] for e in viewer.get_received() if e["name"] == "bid_update"]
    assert [(r["amount"], r["auto"]) for r in ev["new_bids"]] == [("150.00", False), ("160.00", True)]
    assert ev["current_bid"] == "160.00" and ev["amount"] == "160.00" and ev["bidder_id"] == users["buyer"].id
    assert "300" not in str(ev)  # the maximum is never broadcast


def test_proxy_the_bid_form_can_set_a_maximum(app, lot, users):
    r = client_for(app, "buyer@t.test").post(f"/auctions/{lot.id}/bid", data={"amount": "100", "max_amount": "400"})
    assert r.status_code == 302
    (mx,) = MaxBid.query.all()
    assert mx.buyer_id == users["buyer"].id and mx.max_amount == D("400")


# =================================== reserve price ============================================================================
def with_reserve(lot, reserve):
    lot.reserve_price = D(reserve)
    db.session.commit()
    return lot


def test_reserve_below_it_the_auction_ends_without_a_sale(lot, users):
    with_reserve(lot, "1000")
    svc.place_bid(lot.id, users["buyer"], "500")
    assert svc.auction_state(fresh(lot))["reserve_met"] is False
    info = svc.close_auction(lot.id, now=fresh(lot).end_time + timedelta(seconds=1))
    assert info["reserve_not_met"] is True and Winner.query.count() == 0 and Payment.query.count() == 0
    assert "Reserve not met" in titles(users["seller"]) and "Auction ended without a sale" in titles(users["buyer"])


def test_reserve_a_maximum_above_it_lifts_the_price_to_it(lot, users):
    with_reserve(lot, "1000")
    svc.place_bid(lot.id, users["buyer"], "500", raw_max="1500")
    lot = fresh(lot)
    assert lot.current_bid == D("1000") and svc.reserve_met(lot)
    svc.close_auction(lot.id, now=lot.end_time + timedelta(seconds=1))
    assert Winner.query.one().winning_amount == D("1000")


def test_reserve_its_amount_is_never_shown(app, lot, users):
    with_reserve(lot, "4321")
    page = client_for(app, "buyer@t.test").get(f"/auctions/{lot.id}").get_data(as_text=True)
    assert "4321" not in page and "4,321" not in page and "Reserve not met" in page


# =================================== Buy It Now ===============================================================================
def with_buy_now(lot, price):
    lot.buy_now_price = D(price)
    db.session.commit()
    return lot


def test_buynow_ends_the_auction_with_the_buyer_as_winner(app, lot, users):
    with_buy_now(lot, "900")
    r = client_for(app, "buyer@t.test").post(f"/auctions/{lot.id}/buy-now")
    assert r.status_code == 302 and r.location.endswith(f"/payments/{lot.id}")
    lot = fresh(lot)
    assert lot.status == "closed" and lot.current_bid == D("900")
    assert Winner.query.one().buyer_id == users["buyer"].id and Payment.query.one().amount == D("900")


def test_buynow_disappears_with_the_first_bid(app, lot, users):
    with_buy_now(lot, "900")
    assert svc.auction_state(fresh(lot))["buy_now_price"] == "900.00"
    svc.place_bid(lot.id, make_user("b@t.test"), "100")
    assert svc.auction_state(fresh(lot))["buy_now_price"] is None
    with pytest.raises(BidError, match="no longer available"):
        svc.buy_now(lot.id, users["buyer"])
    assert fresh(lot).status == "active" and Winner.query.count() == 0


def test_buynow_not_for_the_seller_an_admin_or_an_unconfirmed_account(lot, users):
    with_buy_now(lot, "900")
    with pytest.raises(BidError, match="own product"):
        svc.buy_now(lot.id, users["seller"])
    with pytest.raises(BidError):
        svc.buy_now(lot.id, users["admin"])
    users["buyer"].email_verified_at = None
    db.session.commit()
    with pytest.raises(BidError, match="Confirm your email"):
        svc.buy_now(lot.id, users["buyer"])
    assert fresh(lot).status == "active"


def test_buynow_without_a_price_is_refused(lot, users):
    with pytest.raises(BidError, match="no longer available"):
        svc.buy_now(lot.id, users["buyer"])


# =================================== the seller sets them =====================================================================
def test_seller_lists_a_card_with_a_reserve_and_a_buy_now_price(as_seller, users, cat, card_type):  # noqa: F811
    p = ready_card(users["seller"], cat, card_type)
    page = as_seller.get(f"/seller/cards/{p.collectible_card.id}/auction").get_data(as_text=True)
    assert "Reserve price (optional)" in page and "Buy It Now price (optional)" in page
    r = create(as_seller, p, reserve_price="800", buy_now_price="1500")
    assert r.status_code == 302
    (a,) = Auction.query.all()
    assert a.reserve_price == D("800") and a.buy_now_price == D("1500") and a.current_bid == D("500")


@pytest.mark.parametrize("over,words", [
    ({"reserve_price": "400"}, "reserve price must be at least the starting bid"),
    ({"buy_now_price": "500"}, "Buy It Now price must be above the starting bid"),
    ({"reserve_price": "900", "buy_now_price": "800"}, "Buy It Now price must be at least the reserve"),
])
def test_seller_prices_that_make_no_sense_are_refused(as_seller, users, cat, card_type, over, words):  # noqa: F811
    p = ready_card(users["seller"], cat, card_type)
    r = create(as_seller, p, **over)
    assert words in r.get_data(as_text=True) and Auction.query.count() == 0


def test_seller_both_prices_stay_optional(as_seller, users, cat, card_type):  # noqa: F811
    p = ready_card(users["seller"], cat, card_type)
    assert create(as_seller, p, reserve_price="", buy_now_price="").status_code == 302
    (a,) = Auction.query.all()
    assert a.reserve_price is None and a.buy_now_price is None


def test_proxy_my_bids_shows_my_own_maximum_and_marks_automatic_bids(app, lot, users):
    svc.place_bid(lot.id, users["buyer"], "100", raw_max="777")
    svc.place_bid(lot.id, make_user("b@t.test"), "150")
    page = client_for(app, "buyer@t.test").get("/buyer/bids").get_data(as_text=True)
    assert "777.00" in page and "automatic" in page
    assert "777" not in client_for(app, "b@t.test").get("/buyer/bids").get_data(as_text=True)
