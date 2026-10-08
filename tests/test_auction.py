import re
import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from flask import g

from app import create_app
from app.config import TestConfig
from app.extensions import db, socketio
from app.models import Auction, Bid, Category, Notification, Payment, Product, User, Winner, utcnow
from app.services import auction_service as svc
from app.services.auction_service import BidError

from .conftest import PASSWORD, login, make_user
from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)


@pytest.fixture
def auction(users, cats):  # noqa: F811
    """Active auction, starting price 100, ending in 5 hours, no bids."""
    return make_auction(users["seller"], cats["Books"], "Red Lamp", 100)


def bid(auction, user, amount, now=None):
    return svc.place_bid(auction.id, user, amount, now=now)


def rejected(auction, user, amount, now=None):
    with pytest.raises(BidError) as e:
        bid(auction, user, amount, now)
    return e.value


def notes(user):
    return [n.title for n in Notification.query.filter_by(user_id=user.id)]


def client_for(app, email):
    """A logged-in client. The test fixture holds one app context open, so reset Flask-Login's cache."""
    g.pop("_login_user", None)
    c = app.test_client()
    login(c, email)
    g.pop("_login_user", None)
    return c


# ---- bid rules -------------------------------------------------------------
def test_first_bid_may_equal_starting_price(auction, users):
    r = bid(auction, users["buyer"], "100")
    assert r.bid.amount == Decimal("100")
    db.session.refresh(auction)
    assert auction.current_bid == Decimal("100") and auction.highest_bidder_id == users["buyer"].id


def test_first_bid_below_starting_price_rejected(auction, users):
    e = rejected(auction, users["buyer"], "99.99")
    assert "starting price" in e.message and Bid.query.count() == 0


def test_later_bids_must_beat_current_bid(auction, users):
    bid(auction, users["buyer"], "150")
    b2 = make_user("b2@t.test")
    for amount in ("150", "149.99", "100", "1"):
        assert "higher than the current bid" in rejected(auction, b2, amount).message
    bid(auction, b2, "150.01")
    db.session.refresh(auction)
    assert auction.current_bid == Decimal("150.01") and Bid.query.count() == 2


def test_same_bidder_can_raise_own_bid(auction, users):
    bid(auction, users["buyer"], "120")
    bid(auction, users["buyer"], "130")
    assert Bid.query.count() == 2


def test_bid_updates_state_and_notifies(auction, users):
    b1, b2 = users["buyer"], make_user("b2@t.test")
    bid(auction, b1, "120")
    bid(auction, b2, "150")
    db.session.refresh(auction)
    assert auction.highest_bidder_id == b2.id and auction.current_bid == Decimal("150")
    assert "Bid accepted" in notes(b1) and "You have been outbid" in notes(b1)
    assert "Bid accepted" in notes(b2) and "You have been outbid" not in notes(b2)
    assert notes(users["seller"]).count("New bid received") == 2


def test_raising_own_bid_does_not_send_outbid_notice(auction, users):
    bid(auction, users["buyer"], "120")
    bid(auction, users["buyer"], "130")
    assert "You have been outbid" not in notes(users["buyer"])


@pytest.mark.parametrize("raw", ["", " ", "abc", "-5", "0", "0.00", "NaN", "inf", "-inf", "1e3", "10.555",
                                 "1,000", "99999999999", "12abc", "١٢٣", None])
def test_invalid_amounts_rejected(auction, users, raw):
    rejected(auction, users["buyer"], raw)
    assert Bid.query.count() == 0


def test_sellers_and_admins_cannot_bid(auction, users):
    assert rejected(auction, users["seller"], "500").status == 403
    assert rejected(auction, users["admin"], "500").status == 403
    assert Bid.query.count() == 0


def test_seller_cannot_bid_on_own_product_even_with_buyer_role(auction, users):
    users["seller"].role = "buyer"  # defence in depth: the ownership check must hold on its own
    db.session.commit()
    e = rejected(auction, users["seller"], "500")
    assert "own product" in e.message and e.status == 403


@pytest.mark.parametrize("status,text", [("scheduled", "not started"), ("closed", "ended"), ("cancelled", "cancelled")])
def test_bids_refused_unless_active(users, cats, status, text):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "X", 100, status=status)
    if status == "scheduled":
        a.start_time = utcnow() + timedelta(hours=1)
        db.session.commit()
    assert text in rejected(a, users["buyer"], "500").message
    assert Bid.query.count() == 0


def test_bid_after_end_time_rejected_even_if_not_yet_closed(auction, users):
    auction.end_time = utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert "ended" in rejected(auction, users["buyer"], "500").message


def test_bid_exactly_at_end_time_rejected(auction, users):
    assert "ended" in rejected(auction, users["buyer"], "500", now=auction.end_time).message


def test_unapproved_or_missing_auction_not_found(auction, users):
    assert svc_status(lambda: svc.place_bid(99999, users["buyer"], "5")) == 404
    auction.product.approval_status = "rejected"
    db.session.commit()
    assert rejected(auction, users["buyer"], "500").status == 404


def svc_status(fn):
    with pytest.raises(BidError) as e:
        fn()
    return e.value.status


def test_bid_just_after_start_activates_scheduled_auction(users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "X", 100, status="scheduled", start_hours=-1)  # start passed
    bid(a, users["buyer"], "100")
    db.session.refresh(a)
    assert a.status == "active"


# ---- anti-sniping ------------------------------------------------------------
def test_bid_in_final_minute_extends_by_two_minutes(auction, users):
    end = auction.end_time
    r = bid(auction, users["buyer"], "120", now=end - timedelta(seconds=59))
    db.session.refresh(auction)
    assert r.extended and auction.end_time == end + timedelta(minutes=2)
    assert auction.extension_count == 1 and auction.original_end_time != auction.end_time


def test_extension_boundary_is_inclusive_at_60s(auction, users):
    end = auction.end_time
    assert bid(auction, users["buyer"], "120", now=end - timedelta(seconds=60)).extended
    auction2 = make_auction(users["seller"], Category.query.first(), "Y", 100)
    assert not bid(auction2, users["buyer"], "120", now=auction2.end_time - timedelta(seconds=61)).extended
    db.session.refresh(auction2)
    assert auction2.end_time == auction2.original_end_time and auction2.extension_count == 0


def test_extensions_stack_and_only_for_accepted_bids(auction, users):
    b2 = make_user("b2@t.test")
    end = auction.end_time
    bid(auction, users["buyer"], "120", now=end - timedelta(seconds=30))          # -> end+120s
    rejected(auction, b2, "119", now=end - timedelta(seconds=20))                 # invalid: no extension
    db.session.refresh(auction)
    assert auction.end_time == end + timedelta(seconds=120)
    bid(auction, b2, "130", now=end + timedelta(seconds=100))                      # 20s left of new end
    db.session.refresh(auction)
    assert auction.end_time == end + timedelta(seconds=240) and auction.extension_count == 2


def test_extended_auction_does_not_close_at_original_end(auction, users):
    end = auction.end_time
    bid(auction, users["buyer"], "120", now=end - timedelta(seconds=10))
    assert svc.close_auction(auction.id, now=end + timedelta(seconds=1)) is None
    db.session.refresh(auction)
    assert auction.status == "active"
    assert svc.close_auction(auction.id, now=end + timedelta(minutes=2, seconds=1)) is not None


# ---- closing & winner selection ---------------------------------------------
def ended(auction):
    return auction.end_time + timedelta(seconds=1)


def test_close_selects_highest_bidder_and_creates_records(auction, users):
    b2 = make_user("b2@t.test")
    bid(auction, users["buyer"], "120")
    bid(auction, b2, "200")
    info = svc.close_auction(auction.id, now=ended(auction))
    db.session.refresh(auction)
    assert auction.status == "closed" and info["bid_count"] == 2 and info["winning_amount"] == "200.00"
    w = Winner.query.one()
    assert w.buyer_id == b2.id and w.winning_amount == Decimal("200")
    p = Payment.query.one()
    assert p.buyer_id == b2.id and p.amount == Decimal("200") and p.payment_status == "pending"
    assert {"Auction won", "Payment pending"} <= set(notes(b2))
    assert {"Auction completed", "Winner selected"} <= set(notes(users["seller"]))
    assert "Auction won" not in notes(users["buyer"])


def test_close_without_bids(auction, users):
    info = svc.close_auction(auction.id, now=ended(auction))
    assert info["winning_amount"] is None and Winner.query.count() == 0 and Payment.query.count() == 0
    assert "Auction completed" in notes(users["seller"])


def test_close_is_idempotent_and_refuses_early_or_inactive(auction, users):
    bid(auction, users["buyer"], "120")
    assert svc.close_auction(auction.id, now=auction.end_time - timedelta(seconds=1)) is None  # not ended yet
    assert svc.close_auction(auction.id, now=ended(auction)) is not None
    assert svc.close_auction(auction.id, now=ended(auction)) is None  # second time: nothing to do
    assert Winner.query.count() == 1 and Payment.query.count() == 1
    assert notes(users["buyer"]).count("Auction won") == 1


def test_no_bids_after_close(auction, users):
    svc.close_auction(auction.id, now=ended(auction))
    assert "ended" in rejected(auction, users["buyer"], "500").message


def test_maintenance_starts_and_closes(users, cats):  # noqa: F811
    now = utcnow()
    due_start = make_auction(users["seller"], cats["Books"], "S", 10, status="scheduled", start_hours=-1)
    due_end = make_auction(users["seller"], cats["Books"], "E", 10, hours_left=-1)
    live = make_auction(users["seller"], cats["Books"], "L", 10)
    infos = svc.run_maintenance(now)
    for a in (due_start, due_end, live):
        db.session.refresh(a)
    assert due_start.status == "active" and due_end.status == "closed" and live.status == "active"
    assert [i["auction_id"] for i in infos] == [due_end.id]
    assert svc.run_maintenance(now) == []  # nothing left to do


def test_maintenance_closes_started_and_already_ended_in_one_tick(users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "S", 10, status="scheduled", hours_left=-1, start_hours=-2)
    assert [i["auction_id"] for i in svc.run_maintenance()] == [a.id]


# ---- HTTP -------------------------------------------------------------------
def post_bid(c, a, amount, json=True):
    return c.post(f"/auctions/{a.id}/bid", data={"amount": amount},
                  headers={"Accept": "application/json"} if json else {})


def test_http_bid_success_json(app, auction, users):
    c = client_for(app, "buyer@t.test")
    r = post_bid(c, auction, "125.50")
    assert r.status_code == 200 and r.json["ok"] and r.json["current_bid"] == "125.50"
    assert r.json["bid_count"] == 1 and r.json["bidder_mask"] == "b***" and r.json["extended"] is False
    assert r.json["min_next_bid"] == "125.51" and "buyer@t.test" not in r.get_data(as_text=True)


@pytest.mark.parametrize("amount,status", [("abc", 400), ("50", 400), ("-1", 400)])
def test_http_bid_errors_json(app, auction, users, amount, status):
    r = post_bid(client_for(app, "buyer@t.test"), auction, amount)
    assert r.status_code == status and r.json["ok"] is False and r.json["error"]


def test_http_bid_html_fallback_flashes_and_redirects(app, auction, users):
    c = client_for(app, "buyer@t.test")
    r = post_bid(c, auction, "50", json=False)
    assert r.status_code == 302 and r.location.endswith(f"/auctions/{auction.id}")
    assert b"minimum" in c.get(r.location).data
    r = post_bid(c, auction, "150", json=False)
    assert b"Your bid was placed" in c.get(r.location).data


def test_http_bid_requires_login(app, auction):
    r = app.test_client().post(f"/auctions/{auction.id}/bid", data={"amount": "500"})
    assert r.status_code == 302 and "/auth/login" in r.location and Bid.query.count() == 0


def test_http_seller_and_admin_get_403(app, auction, users):
    for role in ("seller", "admin"):
        assert post_bid(client_for(app, f"{role}@t.test"), auction, "500").status_code == 403
    assert Bid.query.count() == 0


def test_http_bid_unknown_auction_404(app, users):
    assert app.test_client().post("/auctions/9/bid").status_code == 302
    r = client_for(app, "buyer@t.test").post("/auctions/999/bid", data={"amount": "5"}, headers={"Accept": "application/json"})
    assert r.status_code == 404


def test_http_bid_requires_csrf_token_when_enabled(tmp_path):
    class Strict(TestConfig):
        WTF_CSRF_ENABLED = True

    app = create_app(Strict)
    with app.app_context():
        db.create_all()
        make_user("b@t.test")
        r = app.test_client().post("/auctions/1/bid", data={"amount": "5"})
        assert r.status_code == 400
        db.drop_all()


def test_state_endpoint_and_lazy_close(app, auction, users):
    c = app.test_client()
    s = c.get(f"/auctions/{auction.id}/state").json
    assert s["status"] == "active" and s["current_bid"] == "100.00" and s["bid_count"] == 0
    assert s["end_time"].endswith("Z") and s["server_now"].endswith("Z")
    bid(auction, users["buyer"], "130")
    auction.end_time = utcnow() - timedelta(seconds=2)
    db.session.commit()
    s = c.get(f"/auctions/{auction.id}/state").json  # a page view closes it, no scheduler needed
    assert s["status"] == "closed" and Winner.query.count() == 1
    assert s["winner_mask"] == "b***" and s["winning_amount"] == "130.00"  # so a late-syncing page can show it
    assert c.get(f"/auctions/{auction.id}/state").json["winner_mask"] == "b***"  # and it persists
    assert c.get("/auctions/9999/state").status_code == 404


def test_detail_page_bid_form_visibility(app, auction, users):
    anon = app.test_client().get(f"/auctions/{auction.id}").data.decode()
    assert 'id="bid-form"' not in anon and "Log in" in anon
    assert 'id="bid-form"' in client_for(app, "buyer@t.test").get(f"/auctions/{auction.id}").data.decode()
    assert 'id="bid-form"' not in client_for(app, "seller@t.test").get(f"/auctions/{auction.id}").data.decode()
    d = client_for(app, "buyer@t.test").get(f"/auctions/{auction.id}").data.decode()
    assert f'data-auction-id="{auction.id}"' in d and "data-end=" in d and "Place bid" in d


def test_detail_page_hides_form_when_closed(app, auction, users):
    svc.close_auction(auction.id, now=ended(auction))
    d = client_for(app, "buyer@t.test").get(f"/auctions/{auction.id}").data.decode()
    form = re.search(r'<form id="bid-form"[^>]*>', d)
    assert form and "d-none" in form.group(0)  # the form is present but hidden once the auction has ended


# ---- Socket.IO --------------------------------------------------------------
def events(sc, name):
    return [e["args"][0] for e in sc.get_received() if e["name"] == name]


def test_live_bid_reaches_other_viewers(app, auction, users):
    viewer = socketio.test_client(app)
    viewer.emit("join", {"auction_id": auction.id})
    assert any(e["name"] == "joined" for e in viewer.get_received())
    r = post_bid(client_for(app, "buyer@t.test"), auction, "140")
    assert r.status_code == 200
    got = events(viewer, "bid_update")
    assert len(got) == 1 and got[0]["current_bid"] == "140.00" and got[0]["bid_count"] == 1
    assert got[0]["bidder_mask"] == "b***" and "name" not in got[0] and "email" not in got[0]


def test_extension_is_broadcast(app, auction, users):
    viewer = socketio.test_client(app)
    viewer.emit("join", {"auction_id": auction.id})
    viewer.get_received()
    auction.end_time = utcnow() + timedelta(seconds=30)
    db.session.commit()
    before = auction.end_time
    post_bid(client_for(app, "buyer@t.test"), auction, "140")
    ev = events(viewer, "bid_update")[0]
    assert ev["extended"] is True and ev["extension_count"] == 1
    assert ev["end_time"] == (before + timedelta(seconds=120)).isoformat() + "Z"


def test_only_room_members_get_events(app, auction, users, cats):  # noqa: F811
    other = make_auction(users["seller"], cats["Books"], "Other", 10)
    viewer = socketio.test_client(app)
    viewer.emit("join", {"auction_id": other.id})
    viewer.get_received()
    post_bid(client_for(app, "buyer@t.test"), auction, "140")
    assert events(viewer, "bid_update") == []


def test_cannot_join_hidden_or_invalid_rooms(app, users, cats):  # noqa: F811
    hidden = make_auction(users["seller"], cats["Books"], "H", 10, status="cancelled")
    for payload in ({"auction_id": hidden.id}, {"auction_id": 9999}, {"auction_id": "abc"}, {}, None):
        sc = socketio.test_client(app)
        sc.emit("join", payload)
        names = [e["name"] for e in sc.get_received()]
        assert "error" in names and "joined" not in names


def test_close_is_broadcast_with_masked_winner(app, auction, users):
    viewer = socketio.test_client(app)
    viewer.emit("join", {"auction_id": auction.id})
    viewer.get_received()
    bid(auction, users["buyer"], "170")
    auction.end_time = utcnow() - timedelta(seconds=1)
    db.session.commit()
    app.test_client().get(f"/auctions/{auction.id}")  # any page view runs maintenance
    ev = events(viewer, "auction_closed")
    assert len(ev) == 1 and ev[0]["winner_mask"] == "b***" and ev[0]["winning_amount"] == "170.00"


# ---- concurrency ------------------------------------------------------------
@pytest.fixture
def file_app(tmp_path):
    """Real on-disk SQLite so each thread gets its own connection, like a production server."""
    class FileConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'race.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 30}}

    app = create_app(FileConfig)
    with app.app_context():
        db.create_all()
        seller = make_user("seller@t.test", "seller")
        cat = Category(name="Books")
        db.session.add(cat)
        db.session.commit()
        buyers = [make_user(f"buyer{i}@t.test") for i in range(20)]
        a = make_auction(seller, cat, "Race", 100)
        ids = ([b.id for b in buyers], a.id)
    yield app, ids
    with app.app_context():
        db.session.remove()
        db.drop_all()


def run_threads(app, jobs):
    """Run each (user_id, auction_id, amount) in its own thread and app context, released together."""
    barrier = threading.Barrier(len(jobs))
    outcomes, errors = [], []

    def worker(uid, aid, amount):
        with app.app_context():
            barrier.wait()  # don't hold a DB connection while waiting: the pool is smaller than the thread count
            user = db.session.get(User, uid)
            try:
                svc.place_bid(aid, user, amount)
                outcomes.append((uid, amount))
            except BidError as e:
                outcomes.append((uid, e.status))
            except Exception as e:  # noqa: BLE001 - anything else is a real failure
                errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=j) for j in jobs]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    assert not errors, errors
    return outcomes


def test_simultaneous_distinct_bids_keep_highest_and_stay_monotonic(file_app):
    app, (buyer_ids, aid) = file_app
    run_threads(app, [(uid, aid, str(110 + i * 10)) for i, uid in enumerate(buyer_ids)])  # 110 .. 300
    with app.app_context():
        a = db.session.get(Auction, aid)
        bids = Bid.query.filter_by(auction_id=aid).order_by(Bid.id).all()
        amounts = [b.amount for b in bids]
        assert amounts == sorted(set(amounts)), "accepted bids must be strictly increasing"
        assert amounts[-1] == Decimal("300") and a.current_bid == Decimal("300")
        assert a.highest_bidder_id == buyer_ids[-1]
        assert bids[-1].buyer_id == a.highest_bidder_id


def test_simultaneous_identical_bids_only_one_wins(file_app):
    app, (buyer_ids, aid) = file_app
    outcomes = run_threads(app, [(uid, aid, "500") for uid in buyer_ids[:10]])
    with app.app_context():
        assert Bid.query.filter_by(auction_id=aid).count() == 1
        assert sum(1 for _, o in outcomes if o == "500") == 1
        assert sum(1 for _, o in outcomes if o == 400) == 9  # everyone else told their bid is too low


def test_simultaneous_close_creates_one_winner(file_app):
    app, (buyer_ids, aid) = file_app
    with app.app_context():
        svc.place_bid(aid, db.session.get(User, buyer_ids[0]), "150")
        db.session.get(Auction, aid).end_time = utcnow() - timedelta(seconds=1)
        db.session.commit()
    results = []
    barrier = threading.Barrier(8)

    def closer():
        with app.app_context():
            barrier.wait()
            results.append(svc.close_auction(aid))

    ts = [threading.Thread(target=closer) for _ in range(8)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    with app.app_context():
        assert sum(1 for r in results if r) == 1
        assert Winner.query.count() == 1 and Payment.query.count() == 1


def test_bids_racing_the_close_never_beat_the_winner(file_app):
    app, (buyer_ids, aid) = file_app
    with app.app_context():
        svc.place_bid(aid, db.session.get(User, buyer_ids[0]), "150")
        db.session.get(Auction, aid).end_time = utcnow() - timedelta(seconds=1)  # over, but row still "active"
        db.session.commit()
    barrier = threading.Barrier(6)
    outcomes, errors = [], []

    def bidder(uid, amount):
        with app.app_context():
            barrier.wait()
            user = db.session.get(User, uid)
            try:
                svc.place_bid(aid, user, amount)
                outcomes.append("accepted")
            except BidError:
                outcomes.append("refused")
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

    def closer():
        with app.app_context():
            barrier.wait()
            svc.close_auction(aid)

    threads = [threading.Thread(target=bidder, args=(uid, str(200 + i))) for i, uid in enumerate(buyer_ids[1:6])]
    threads.append(threading.Thread(target=closer))
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    assert not errors, errors
    with app.app_context():
        assert outcomes == ["refused"] * 5  # the auction was over, so every late bid is refused
        w = Winner.query.one()
        assert w.winning_amount == Decimal("150") and Bid.query.filter_by(auction_id=aid).count() == 1
