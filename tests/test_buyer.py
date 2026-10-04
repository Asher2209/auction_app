from datetime import timedelta
from decimal import Decimal

import pytest
from flask import g

from app.extensions import db
from app.models import Auction, Bid, Category, Product, ProductImage, Watchlist, Winner, utcnow

from .conftest import login, make_user


@pytest.fixture
def cats(app):
    cs = {n: Category(name=n) for n in ("Books", "Electronics", "Sports")}
    db.session.add_all(cs.values())
    db.session.commit()
    return cs


def make_auction(seller, cat, title, price=100, status="active", hours_left=5, desc="plain text here",
                 approval="approved", bids=(), start_hours=None):
    """start_hours: hours from now the auction starts. Defaults to the future for "scheduled", else 1h ago.
    (Pages and bids start due auctions, so a "scheduled" row with a past start is a deliberate edge case.)"""
    now = utcnow()
    if start_hours is None:
        start_hours = 1 if status == "scheduled" else -1
    start = now + timedelta(hours=start_hours)
    p = Product(seller_id=seller.id, category_id=cat.id, title=title, description=desc,
                starting_price=Decimal(price), approval_status=approval,
                auction_start=start, auction_end=now + timedelta(hours=hours_left))
    p.images.append(ProductImage(path="products/x.png"))
    db.session.add(p)
    db.session.flush()
    a = Auction(product_id=p.id, start_time=start, end_time=now + timedelta(hours=hours_left),
                original_end_time=now + timedelta(hours=hours_left), current_bid=Decimal(price), status=status)
    db.session.add(a)
    db.session.flush()
    for buyer, amount in bids:
        db.session.add(Bid(auction_id=a.id, buyer_id=buyer.id, amount=Decimal(amount)))
        a.current_bid, a.highest_bidder_id = Decimal(amount), buyer.id
    db.session.commit()
    return a


def titles(client, qs="", path="/auctions/"):
    d = client.get(path + qs).data.decode()
    found = [t for t in ("Red Lamp", "Blue Book", "Green Bat", "Old Radio", "Hidden") if t in d]
    return sorted(found, key=d.index)  # in page order


@pytest.fixture
def market(users, cats):
    s, b = users["seller"], users["buyer"]
    a1 = make_auction(s, cats["Electronics"], "Red Lamp", 500, desc="A bright lamp for reading", hours_left=3)
    a2 = make_auction(s, cats["Books"], "Blue Book", 50, desc="Rare hardcover", hours_left=10,
                      bids=[(b, 60), (users["admin"], 70)])
    a3 = make_auction(s, cats["Sports"], "Green Bat", 1500, status="scheduled", hours_left=20)
    a4 = make_auction(s, cats["Electronics"], "Old Radio", 200, status="closed", hours_left=-2)
    # never publicly visible:
    make_auction(s, cats["Books"], "Hidden", 10, approval="pending")
    make_auction(s, cats["Books"], "Hidden", 10, status="cancelled")
    return {"lamp": a1, "book": a2, "bat": a3, "radio": a4}


# ---- visibility -----------------------------------------------------------
def test_browse_is_public_and_defaults_to_active(client, market):
    assert sorted(titles(client)) == ["Blue Book", "Red Lamp"]


def test_hidden_listings_never_appear_anywhere(client, market):
    assert "Hidden" not in titles(client, "?status=all")
    for a in Auction.query.join(Product).filter(Product.title == "Hidden"):
        assert client.get(f"/auctions/{a.id}").status_code == 404
    assert client.get("/auctions/99999").status_code == 404


def test_status_filter(client, market):
    assert titles(client, "?status=upcoming") == ["Green Bat"]
    assert titles(client, "?status=ended") == ["Old Radio"]
    assert sorted(titles(client, "?status=all")) == ["Blue Book", "Green Bat", "Old Radio", "Red Lamp"]
    assert sorted(titles(client, "?status=bogus")) == ["Blue Book", "Red Lamp"]


# ---- search & filters -----------------------------------------------------
def test_search_title_description_category_and_all_words(client, market):
    assert titles(client, "?q=lamp") == ["Red Lamp"]
    assert titles(client, "?q=hardcover") == ["Blue Book"]  # description match
    assert sorted(titles(client, "?q=electronics&status=all")) == ["Old Radio", "Red Lamp"]  # category match
    assert titles(client, "?q=red+lamp") == ["Red Lamp"]
    assert titles(client, "?q=red+book") == []  # every word must match
    assert titles(client, "?q=LAMP") == ["Red Lamp"]  # case-insensitive


def test_search_is_safe_against_wildcards_and_injection(client, market):
    assert titles(client, "?q=%25") == []
    assert titles(client, "?q=_ed") == []
    assert client.get("/auctions/?q=%27+OR+1%3D1+--").status_code == 200
    assert client.get("/auctions/?q=" + "x" * 5000).status_code == 200
    assert client.get("/auctions/?q=" + "+".join("a" * 50)).status_code == 200


def test_category_filter(client, market, cats):
    assert titles(client, f"?category={cats['Books'].id}") == ["Blue Book"]
    assert sorted(titles(client, "?category=abc")) == ["Blue Book", "Red Lamp"]  # ignored
    assert titles(client, "?category=9999") == []


def test_price_filter_uses_current_bid(client, market):
    # Blue Book started at 50 but its current bid is 70
    assert titles(client, "?min_price=60&max_price=100") == ["Blue Book"]
    assert titles(client, "?min_price=100") == ["Red Lamp"]
    assert titles(client, "?max_price=69") == []
    assert sorted(titles(client, "?min_price=abc&max_price=-5")) == ["Blue Book", "Red Lamp"]  # invalid ignored
    assert client.get("/auctions/?min_price=NaN&max_price=Infinity").status_code == 200


def test_sorting(client, market):
    assert titles(client, "?sort=ending") == ["Red Lamp", "Blue Book"]  # lamp ends in 3h
    assert titles(client, "?sort=price_low") == ["Blue Book", "Red Lamp"]
    assert titles(client, "?sort=price_high") == ["Red Lamp", "Blue Book"]
    assert titles(client, "?sort=most_bids") == ["Blue Book", "Red Lamp"]
    assert client.get("/auctions/?sort=bogus").status_code == 200


def test_pagination(client, users, cats):
    for i in range(14):
        make_auction(users["seller"], cats["Books"], f"Item {i:02d}")
    page1 = client.get("/auctions/").data.decode()
    page2 = client.get("/auctions/?page=2").data.decode()
    assert page1.count("card-title") == 12 and page2.count("card-title") == 2
    assert "14 auctions found" in page1
    assert client.get("/auctions/?page=99").status_code == 200
    assert client.get("/auctions/?page=-3").status_code == 200


def test_filters_survive_pagination_links(client, users, cats):
    for i in range(13):
        make_auction(users["seller"], cats["Books"], f"Item {i:02d}", price=10 + i)
    d = client.get("/auctions/?q=item&sort=price_low").data.decode()
    assert "page=2" in d and "q=item" in d and "sort=price_low" in d


# ---- detail ---------------------------------------------------------------
def test_detail_shows_required_fields(client, market):
    a = market["book"]
    d = client.get(f"/auctions/{a.id}").data.decode()
    assert "Blue Book" in d and "Rare hardcover" in d
    assert "Sam" not in d  # seller name below
    assert users_seller_name(a) in d
    assert "$" not in d and "70.00" in d  # current highest bid
    assert "Number of bids" in d and "Time remaining" in d and "Starting price" in d


def users_seller_name(a):
    return a.product.seller.name


def test_bid_history_masks_other_bidders(client, market, users):
    a = market["book"]
    d = client.get(f"/auctions/{a.id}").data.decode()
    assert "b***" in d and "a***" in d
    assert "buyer@t.test" not in d and ">buyer<" not in d
    login(client, "buyer@t.test")
    d = client.get(f"/auctions/{a.id}").data.decode()
    assert "<strong>You</strong>" in d and "a***" in d


def test_detail_states(client, market):
    assert "Upcoming" in client.get(f"/auctions/{market['bat'].id}").data.decode()
    assert "Ended" in client.get(f"/auctions/{market['radio'].id}").data.decode()


def test_closed_detail_shows_masked_winner(client, market, users):
    a = market["radio"]
    db.session.add(Winner(auction_id=a.id, buyer_id=users["buyer"].id, winning_amount=Decimal("250")))
    db.session.commit()
    d = client.get(f"/auctions/{a.id}").data.decode()
    assert "Won by b***" in d and "250.00" in d


def test_detail_escapes_html_in_description(client, users, cats):
    a = make_auction(users["seller"], cats["Books"], "Red Lamp", desc="<script>alert(1)</script>")
    d = client.get(f"/auctions/{a.id}").data.decode()
    assert "<script>alert(1)</script>" not in d and "&lt;script&gt;" in d


# ---- watchlist ------------------------------------------------------------
def test_watchlist_toggle_and_page(client, market, users):
    a = market["lamp"]
    login(client, "buyer@t.test")
    assert "Add to watchlist" in client.get(f"/auctions/{a.id}").data.decode()
    assert client.post(f"/buyer/watchlist/{a.id}/toggle").status_code == 302
    assert Watchlist.query.count() == 1
    assert "Remove from watchlist" in client.get(f"/auctions/{a.id}").data.decode()
    assert "Red Lamp" in client.get("/buyer/watchlist").data.decode()
    client.post(f"/buyer/watchlist/{a.id}/toggle")
    assert Watchlist.query.count() == 0
    assert "Red Lamp" not in client.get("/buyer/watchlist").data.decode()


def test_watchlist_is_per_user_and_buyers_only(client, market, users, app):
    a = market["lamp"]
    login(client, "buyer@t.test")
    client.post(f"/buyer/watchlist/{a.id}/toggle")
    other = make_user("b2@t.test", "buyer")
    c2 = app.test_client()
    g.pop("_login_user", None)
    login(c2, "b2@t.test")
    assert "Red Lamp" not in c2.get("/buyer/watchlist").data.decode()
    for role in ("seller", "admin"):
        g.pop("_login_user", None)
        cx = app.test_client()
        login(cx, f"{role}@t.test")
        assert cx.post(f"/buyer/watchlist/{a.id}/toggle").status_code == 403


def test_watchlist_cannot_add_hidden_auction(client, users, cats):
    login(client, "buyer@t.test")
    a = make_auction(users["seller"], cats["Books"], "Hidden", status="cancelled")
    assert client.post(f"/buyer/watchlist/{a.id}/toggle").status_code == 404
    assert Watchlist.query.count() == 0


def test_watchlist_requires_login_and_post(client, market):
    assert client.post(f"/buyer/watchlist/{market['lamp'].id}/toggle").status_code == 302
    login(client, "buyer@t.test")
    assert client.get(f"/buyer/watchlist/{market['lamp'].id}/toggle").status_code == 405


def test_watchlist_hides_listing_removed_later(client, market, users):
    a = market["lamp"]
    login(client, "buyer@t.test")
    client.post(f"/buyer/watchlist/{a.id}/toggle")
    a.status = "cancelled"
    db.session.commit()
    assert "Red Lamp" not in client.get("/buyer/watchlist").data.decode()


def test_toggle_redirect_ignores_foreign_referrer(client, market):
    login(client, "buyer@t.test")
    r = client.post(f"/buyer/watchlist/{market['lamp'].id}/toggle", headers={"Referer": "https://evil.example/"})
    assert r.location.endswith(f"/auctions/{market['lamp'].id}")


# ---- buyer area -----------------------------------------------------------
def test_buyer_pages_require_buyer_role(client, users):
    paths = ["/buyer/", "/buyer/bids", "/buyer/watchlist", "/buyer/won"]
    for p in paths:
        assert client.get(p).status_code == 302
    for role in ("seller", "admin"):
        client.post("/auth/logout")
        login(client, f"{role}@t.test")
        for p in paths:
            assert client.get(p).status_code == 403


def test_my_bids_statuses(client, market, users):
    buyer = users["buyer"]
    cats_ = Category.query.first()
    lead = make_auction(users["seller"], cats_, "Lead Item", 100, bids=[(buyer, 120)])
    lost = make_auction(users["seller"], cats_, "Lost Item", 100, status="closed", bids=[(buyer, 120), (users["admin"], 150)])
    win = make_auction(users["seller"], cats_, "Win Item", 100, status="closed", bids=[(buyer, 130)])
    db.session.add(Winner(auction_id=win.id, buyer_id=buyer.id, winning_amount=Decimal("130")))
    db.session.commit()
    login(client, "buyer@t.test")
    d = client.get("/buyer/bids").data.decode()
    row = lambda name: d.split(name)[1].split("</tr>")[0]  # noqa: E731
    assert "Leading" in row("Lead Item") and "Outbid" in row("Blue Book")
    assert "Ended" in row("Lost Item") and "Won" in row("Win Item")


def test_my_bids_only_shows_own(client, market, users):
    login(client, "buyer@t.test")
    d = client.get("/buyer/bids").data.decode()
    assert d.count("<tr>") == 2  # header + the buyer's single bid on Blue Book
    assert "70.00" in d  # admin's higher bid appears only as the current highest, not as a row


def test_dashboard_stats(client, market, users):
    buyer = users["buyer"]
    lead = make_auction(users["seller"], Category.query.first(), "Lead Item", 100, bids=[(buyer, 120)])
    win = make_auction(users["seller"], Category.query.first(), "Win Item", 100, status="closed", bids=[(buyer, 130)])
    db.session.add(Watchlist(user_id=buyer.id, product_id=lead.product_id))
    db.session.add(Winner(auction_id=win.id, buyer_id=buyer.id, winning_amount=Decimal("130")))
    db.session.commit()
    login(client, "buyer@t.test")
    d = client.get("/buyer/").data.decode()
    # bidding on: Blue Book + Lead Item (2); leading: Lead Item (1); watching 1; won 1
    for label, value in (("Auctions you are bidding on", 2), ("Currently leading", 1), ("Watching", 1), ("Auctions won", 1)):
        assert f"{label}</div><div class=\"fs-3 fw-semibold\">{value}<" in d.replace("\n", "").replace("      ", "")


def test_won_page_lists_wins_with_payment_status(client, market, users):
    a = market["radio"]
    db.session.add(Winner(auction_id=a.id, buyer_id=users["buyer"].id, winning_amount=Decimal("250")))
    db.session.commit()
    login(client, "buyer@t.test")
    d = client.get("/buyer/won").data.decode()
    assert "Old Radio" in d and "250.00" in d and "Pending" in d


def test_home_page_links_and_search_form(client, market):
    d = client.get("/").data.decode()
    assert "Red Lamp" in d and 'action="/auctions/"' in d
    assert f'/auctions/{market["lamp"].id}' in d
    assert "Green Bat" not in d  # home shows live auctions only
