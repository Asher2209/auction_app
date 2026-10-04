from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from flask import g
from sqlalchemy import event

from app.extensions import db
from app.models import Auction, Bid, Category, CryptoPayment, Payment, Product, User, utcnow
from app.services import analytics_service as an

from .conftest import make_user
from .test_payments import client_for

NOW = datetime(2026, 10, 15, 12, 0, 0)


@pytest.fixture
def world(app, users):
    """Two sellers, three buyers, three categories. Helpers build auctions and payments with exact dates."""
    s1, s2 = users["seller"], make_user("seller2@t.test", "seller")
    b1, b2, b3 = users["buyer"], make_user("b2@t.test"), make_user("b3@t.test")
    cats = {n: Category(name=n) for n in ("Books", "Electronics", "Sports")}
    db.session.add_all(cats.values())
    db.session.commit()

    class W:
        pass

    w = W()
    w.s1, w.s2, w.b1, w.b2, w.b3, w.cats = s1, s2, b1, b2, b3, cats
    w.n = 0

    def auction(seller, cat, title, start=NOW - timedelta(days=5), status="closed", bids=()):
        w.n += 1
        p = Product(seller_id=seller.id, category_id=cats[cat].id, title=title, description="d" * 12, starting_price=Decimal(100),
                    approval_status="approved", auction_start=start, auction_end=start + timedelta(days=2))
        db.session.add(p)
        db.session.flush()
        a = Auction(product_id=p.id, start_time=start, end_time=start + timedelta(days=2), original_end_time=start + timedelta(days=2),
                    current_bid=Decimal(100), status=status)
        db.session.add(a)
        db.session.flush()
        for i, buyer in enumerate(bids):
            db.session.add(Bid(auction_id=a.id, buyer_id=buyer.id, amount=Decimal(100 + i), bid_time=start + timedelta(hours=1 + i)))
        db.session.commit()
        return a

    def sale(seller, cat, title, amount, when, buyer=None, kind="card", eth=None, status="successful", bids=None):
        buyer = buyer or b1
        a = auction(seller, cat, title, start=when - timedelta(days=3), bids=bids if bids is not None else (buyer,))
        pay = Payment(auction_id=a.id, buyer_id=buyer.id, amount=Decimal(amount), payment_status=status,
                      payment_method="crypto" if kind == "crypto" else "simulated", method_detail="eth" if kind == "crypto" else kind,
                      payment_date=when if status == "successful" else None)
        db.session.add(pay)
        db.session.flush()
        if kind == "crypto":
            db.session.add(CryptoPayment(payment_id=pay.id, wallet_address="0x" + "1" * 40, cryptocurrency="ETH", amount=Decimal(eth or "0.1"),
                                         transaction_hash="0x" + f"{pay.id:064x}", blockchain_network="Test",
                                         status={"successful": "confirmed", "failed": "failed"}.get(status, "pending"), confirmations=2))
        db.session.commit()
        return a

    w.auction, w.sale = auction, sale
    return w


def idx(data, label):
    return data["labels"].index(label)


# ---- parameters ------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [("3", 3), ("6", 6), ("12", 12), ("24", 24), (None, 12), ("", 12), ("abc", 12), ("7", 12),
                                          ("-3", 12), ("9999", 12), ("12.5", 12), ("0", 12), (" 6 ", 6)])
def test_parse_months(raw, expected):
    assert an.parse_months(raw) == expected


def test_month_range_crosses_year_boundaries():
    assert an.month_range(3, datetime(2026, 3, 15)) == [(2026, 1), (2026, 2), (2026, 3)]
    assert an.month_range(3, datetime(2026, 1, 31)) == [(2025, 11), (2025, 12), (2026, 1)]
    r = an.month_range(24, datetime(2026, 10, 1))
    assert len(r) == 24 and r[0] == (2024, 11) and r[-1] == (2026, 10) and len(set(r)) == 24


# ---- empty database ----------------------------------------------------------------------------
def test_empty_database_gives_well_formed_empty_data(app):
    d = an.build(12, NOW)
    assert d["labels"][0] == "Nov 2025" and d["labels"][-1] == "Oct 2026" and len(d["labels"]) == 12
    assert d["kpis"] == {"revenue": 0.0, "paid_sales": 0, "average_sale": 0.0}
    assert d["revenue"] == {"simulated": [0.0] * 12, "crypto": [0.0] * 12} and d["empty"] == {"revenue": True, "auctions": True}
    assert d["categories"] == d["top_products"] == d["top_sellers"] == d["active_buyers"] == []
    assert [s["value"] for s in d["status"]] == [0, 0, 0, 0] and [m["value"] for m in d["methods"]] == [0, 0, 0, 0]
    assert d["crypto"] == {"confirmed": 0, "pending": 0, "failed": 0, "eth_total": 0.0, "inr_total": 0.0, "avg_confirmations": None, "success_rate": None}
    assert d["eth_per_month"] == [0.0] * 12


# ---- revenue -------------------------------------------------------------------------------------
def test_monthly_revenue_buckets_split_and_zero_fill(world):
    w = world
    w.sale(w.s1, "Books", "A", 1000, datetime(2026, 10, 2, 9))
    w.sale(w.s1, "Books", "B", 500, datetime(2026, 10, 14), kind="upi")
    w.sale(w.s2, "Sports", "C", 8000, datetime(2026, 8, 20), kind="crypto", eth="0.025")
    w.sale(w.s2, "Sports", "D", 200, datetime(2026, 8, 21), kind="wallet")
    d = an.build(12, NOW)
    assert d["revenue"]["simulated"][idx(d, "Oct 2026")] == 1500.0 and d["revenue"]["crypto"][idx(d, "Oct 2026")] == 0.0
    assert d["revenue"]["simulated"][idx(d, "Aug 2026")] == 200.0 and d["revenue"]["crypto"][idx(d, "Aug 2026")] == 8000.0
    assert d["revenue"]["simulated"][idx(d, "Sep 2026")] == 0.0  # a month without sales is a zero, not a gap
    assert sum(d["revenue"]["simulated"]) + sum(d["revenue"]["crypto"]) == d["kpis"]["revenue"] == 9700.0
    assert d["kpis"]["paid_sales"] == 4 and d["kpis"]["average_sale"] == 2425.0
    assert d["empty"]["revenue"] is False


def test_revenue_ignores_unpaid_failed_and_pending_payments(world):
    w = world
    w.sale(w.s1, "Books", "paid", 100, datetime(2026, 10, 1))
    w.sale(w.s1, "Books", "failed", 99999, datetime(2026, 10, 1), status="failed")
    w.sale(w.s1, "Books", "pending", 88888, datetime(2026, 10, 1), status="pending")
    d = an.build(12, NOW)
    assert d["kpis"] == {"revenue": 100.0, "paid_sales": 1, "average_sale": 100.0}
    assert [p["label"] for p in d["top_products"]] == ["paid"]


def test_month_boundaries_and_window_edges(world):
    w = world
    w.sale(w.s1, "Books", "last second of Sep", 10, datetime(2026, 9, 30, 23, 59, 59))
    w.sale(w.s1, "Books", "first second of Oct", 20, datetime(2026, 10, 1, 0, 0, 0))
    w.sale(w.s1, "Books", "too old for 3 months", 5000, datetime(2026, 7, 31, 23, 59, 59))
    w.sale(w.s1, "Books", "first moment of window", 7, datetime(2026, 8, 1, 0, 0, 0))
    d = an.build(3, NOW)
    assert d["labels"] == ["Aug 2026", "Sep 2026", "Oct 2026"]
    assert d["revenue"]["simulated"] == [7.0, 10.0, 20.0]
    assert an.build(6, NOW)["revenue"]["simulated"][idx(an.build(6, NOW), "Jul 2026")] == 5000.0


def test_future_dated_payments_do_not_break_the_buckets(world):
    world.sale(world.s1, "Books", "future", 123, datetime(2027, 3, 1))
    d = an.build(12, NOW)
    assert sum(d["revenue"]["simulated"]) == 0.0 and d["kpis"]["revenue"] == 123.0  # in the headline, not in a past bucket


def test_amounts_do_not_drift_in_floating_point(world):
    w = world
    for amt in ("0.10", "0.20", "0.30"):
        w.sale(w.s1, "Books", f"x{amt}", amt, datetime(2026, 10, 3))
    assert an.build(12, NOW)["revenue"]["simulated"][-1] == 0.6


# ---- auctions ------------------------------------------------------------------------------------------
def test_auctions_per_month_excludes_cancelled(world):
    w = world
    w.auction(w.s1, "Books", "a", start=datetime(2026, 10, 3))
    w.auction(w.s1, "Books", "b", start=datetime(2026, 10, 9), status="active")
    w.auction(w.s1, "Books", "c", start=datetime(2026, 10, 9), status="cancelled")
    w.auction(w.s1, "Books", "d", start=datetime(2026, 6, 1))
    w.auction(w.s1, "Books", "e", start=datetime(2024, 1, 1))  # outside the window
    d = an.build(12, NOW)
    assert d["auctions_per_month"][idx(d, "Oct 2026")] == 2 and d["auctions_per_month"][idx(d, "Jun 2026")] == 1
    assert sum(d["auctions_per_month"]) == 3 and d["empty"]["auctions"] is False


def test_status_split_always_has_all_four_in_a_fixed_order(world):
    w = world
    for status in ("active", "active", "closed", "scheduled"):
        w.auction(w.s1, "Books", status, status=status)
    d = an.build(12, NOW)
    assert [(s["key"], s["label"], s["value"]) for s in d["status"]] == [
        ("active", "Active", 2), ("scheduled", "Scheduled", 1), ("closed", "Completed", 1), ("cancelled", "Cancelled", 0)]


# ---- rankings ----------------------------------------------------------------------------------------------
def test_categories_ranked_by_bids_then_auctions(world):
    w = world
    w.auction(w.s1, "Books", "b1", bids=(w.b1, w.b2, w.b3))             # Books: 3 bids, 1 auction
    w.auction(w.s1, "Electronics", "e1", bids=(w.b1,))                   # Electronics: 3 bids, 2 auctions
    w.auction(w.s1, "Electronics", "e2", bids=(w.b2, w.b3))
    w.auction(w.s1, "Sports", "s1")                                      # Sports: 0 bids, 1 auction
    cats = an.build(12, NOW)["categories"]
    assert [(c["label"], c["value"], c["auctions"]) for c in cats] == [("Electronics", 3, 2), ("Books", 3, 1), ("Sports", 0, 1)]


def test_categories_without_auctions_are_left_out_and_list_is_capped(world):
    w = world
    for i in range(12):
        c = Category(name=f"Cat{i:02d}")
        db.session.add(c)
        db.session.commit()
        w.cats[c.name] = c
        w.auction(w.s1, c.name, f"item{i}", bids=(w.b1,) * (i % 4))
    names = [c["label"] for c in an.build(12, NOW)["categories"]]
    assert len(names) == an.TOP_N and "Books" not in names  # Books/Electronics/Sports have no auctions here


def test_top_products_highest_paid_sales_first_and_capped(world):
    w = world
    for i in range(10):
        w.sale(w.s1 if i % 2 else w.s2, "Books", f"P{i}", 1000 + i * 100, datetime(2026, 10, 1 + i))
    w.sale(w.s1, "Books", "unpaid giant", 999999, datetime(2026, 10, 1), status="pending")
    top = an.build(12, NOW)["top_products"]
    assert [p["label"] for p in top] == [f"P{i}" for i in (9, 8, 7, 6, 5, 4, 3, 2)]
    assert top[0]["value"] == 1900.0 and top[0]["seller"] == "seller"


def test_top_sellers_sum_paid_sales_only(world):
    w = world
    w.sale(w.s1, "Books", "a", 1000, datetime(2026, 10, 1))
    w.sale(w.s1, "Books", "b", 500, datetime(2026, 10, 2))
    w.sale(w.s2, "Books", "c", 1200, datetime(2026, 10, 3))
    w.sale(w.s2, "Books", "d", 5000, datetime(2026, 10, 3), status="failed")
    sellers = an.build(12, NOW)["top_sellers"]
    assert [(s["label"], s["value"], s["sales"]) for s in sellers] == [("seller", 1500.0, 2), ("seller2", 1200.0, 1)]


def test_most_active_buyers_by_bid_count(world):
    w = world
    w.auction(w.s1, "Books", "x", bids=(w.b1, w.b1, w.b2))
    w.auction(w.s1, "Books", "y", bids=(w.b1, w.b2, w.b2, w.b3))
    buyers = an.build(12, NOW)["active_buyers"]
    # equal bid counts are ordered by name, so the ranking is deterministic
    assert [(b["label"], b["value"], b["auctions"]) for b in buyers] == [("b2", 3, 2), ("buyer", 3, 2), ("b3", 1, 1)]
    assert {b["label"]: b["value"] for b in buyers} == {"buyer": 3, "b2": 3, "b3": 1}
    assert all(b["label"] != "seller" for b in buyers)  # only people who bid


# ---- payment methods and crypto -------------------------------------------------------------------------
def test_payment_methods_fixed_order_with_zeros(world):
    w = world
    for i, kind in enumerate(["card", "card", "upi", "crypto"]):
        w.sale(w.s1, "Books", f"m{i}", 100, datetime(2026, 10, 1 + i), kind=kind)
    w.sale(w.s1, "Books", "failed card", 100, datetime(2026, 10, 9), kind="card", status="failed")
    assert [(m["key"], m["label"], m["value"]) for m in an.build(12, NOW)["methods"]] == [
        ("card", "Card", 2), ("upi", "UPI", 1), ("wallet", "Wallet", 0), ("crypto", "Cryptocurrency", 1)]


def test_crypto_statistics(world):
    w = world
    w.sale(w.s1, "Books", "c1", 32000, datetime(2026, 10, 1), kind="crypto", eth="0.100000")
    w.sale(w.s1, "Books", "c2", 16000, datetime(2026, 9, 1), kind="crypto", eth="0.050000")
    w.sale(w.s1, "Books", "c3", 99999, datetime(2026, 10, 1), kind="crypto", eth="9", status="failed")
    w.sale(w.s1, "Books", "c4", 77777, datetime(2026, 10, 1), kind="crypto", eth="7", status="pending")
    d = an.build(12, NOW)
    assert d["crypto"] == {"confirmed": 2, "pending": 1, "failed": 1, "eth_total": 0.15, "inr_total": 48000.0,
                           "avg_confirmations": 2.0, "success_rate": 66.7}
    assert d["eth_per_month"][idx(d, "Oct 2026")] == 0.1 and d["eth_per_month"][idx(d, "Sep 2026")] == 0.05
    assert sum(d["eth_per_month"]) == pytest.approx(0.15)  # failed and pending ETH is not counted


def test_crypto_success_rate_is_none_without_finished_payments(world):
    world.sale(world.s1, "Books", "p", 1, datetime(2026, 10, 1), kind="crypto", status="pending")
    assert an.build(12, NOW)["crypto"]["success_rate"] is None


def test_no_query_explosion_as_data_grows(world):
    w = world
    counter = {"n": 0}

    def count(*_):
        counter["n"] += 1

    def measure():
        counter["n"] = 0
        event.listen(db.engine, "before_cursor_execute", count)
        try:
            an.build(12, NOW)
        finally:
            event.remove(db.engine, "before_cursor_execute", count)
        return counter["n"]

    w.sale(w.s1, "Books", "one", 100, datetime(2026, 10, 1))
    few = measure()
    for i in range(30):
        w.sale(w.s1 if i % 2 else w.s2, "Sports", f"many{i}", 100 + i, datetime(2026, 9, 1 + i % 20), buyer=w.b2, kind=["card", "upi", "crypto"][i % 3])
    assert measure() == few and few < 20


# ---- the HTTP endpoints --------------------------------------------------------------------------------------------
def test_data_endpoint_for_admins(app, users):
    c = client_for(app, "admin@t.test")
    r = c.get("/admin/analytics/data")
    assert r.status_code == 200 and r.mimetype == "application/json" and "no-store" in r.headers["Cache-Control"]
    body = r.get_json()
    assert set(body) == {"months", "labels", "kpis", "revenue", "auctions_per_month", "status", "categories", "top_products", "top_sellers",
                         "active_buyers", "methods", "crypto", "eth_per_month", "empty"}
    assert body["months"] == 12 and len(body["labels"]) == 12
    assert c.get("/admin/analytics/data?months=3").get_json()["months"] == 3
    assert c.get("/admin/analytics/data?months=nonsense").get_json()["months"] == 12
    assert c.get("/admin/analytics/data?months=99999999999999999999").get_json()["months"] == 12


def test_data_endpoint_returns_real_numbers(app, world):
    world.sale(world.s1, "Books", "Live", 250, utcnow() - timedelta(days=1))
    body = client_for(app, "admin@t.test").get("/admin/analytics/data").get_json()
    assert body["kpis"] == {"revenue": 250.0, "paid_sales": 1, "average_sale": 250.0}
    assert body["top_products"][0]["label"] == "Live"


def test_analytics_is_admin_only(app, users):
    for role in ("buyer", "seller"):
        c = client_for(app, f"{role}@t.test")
        assert c.get("/admin/analytics").status_code == 403 and c.get("/admin/analytics/data").status_code == 403
    g.pop("_login_user", None)
    anon = app.test_client()
    assert anon.get("/admin/analytics").status_code == 302 and anon.get("/admin/analytics/data").status_code == 302


def test_page_has_every_chart_the_filter_and_the_script(app, users):
    html = client_for(app, "admin@t.test").get("/admin/analytics?months=6").data.decode()
    for chart in ("revenue", "auctions", "status", "categories", "methods", "products", "sellers", "buyers", "eth"):
        assert f'data-chart="{chart}"' in html, chart
    assert html.count("<canvas") == 9 and html.count("View as table") == 9
    assert '<option value="6" selected>' in html and all(f'<option value="{m}"' in html for m in (3, 6, 12, 24))
    assert "Chart.js" in html and "js/analytics.js" in html and "viz-root" in html
    bad = client_for(app, "admin@t.test").get("/admin/analytics?months=abc").data.decode()
    assert '<option value="12" selected>' in bad


def test_hostile_names_stay_plain_data_in_the_json(app, world):
    world.s1.name = "<img src=x onerror=alert(1)>"
    db.session.commit()
    world.sale(world.s1, "Books", "<script>alert(1)</script>", 100, utcnow() - timedelta(days=1))
    r = client_for(app, "admin@t.test").get("/admin/analytics/data")
    assert r.mimetype == "application/json"  # never rendered as HTML by the browser
    assert r.get_json()["top_products"][0]["label"] == "<script>alert(1)</script>"
    js = open("app/static/js/analytics.js", encoding="utf-8").read()
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js  # the chart script only ever writes text


def test_overview_dashboard_shows_crypto_payments(app, world):
    world.sale(world.s1, "Books", "c", 100, utcnow() - timedelta(days=1), kind="crypto")
    html = client_for(app, "admin@t.test").get("/admin/").data.decode()
    assert "Crypto payments (confirmed)" in html and "Analytics" in html
