import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from flask import g

from app import create_app
from app.config import TestConfig
from app.extensions import db, mail
from app.models import Category, Notification, Payment, User, Winner, utcnow
from app.services import auction_service as svc
from app.services import payment_service as ps
from app.services.payment_service import PaymentError

from .conftest import login, make_user
from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)

YY = (utcnow().year + 2) % 100
PAN_OK, PAN_DECLINED, PAN_FUNDS, PAN_PENDING = "4242424242424242", "4000000000000002", "4000000000009995", "4000000000003220"


def client_for(app, email):
    g.pop("_login_user", None)
    c = app.test_client()
    login(c, email)
    g.pop("_login_user", None)
    return c


def card(pan=PAN_OK, **over):
    d = {"card_holder": "Bella Buyer", "card_number": pan, "expiry": f"12/{YY}", "cvv": "123"}
    d.update(over)
    return d


def won(users, cats, amount="500"):  # noqa: F811
    """A closed auction won by the buyer: this creates the winner and the pending payment."""
    a = make_auction(users["seller"], cats["Books"], "Red Lamp", 100)
    svc.place_bid(a.id, users["buyer"], amount)
    svc.close_auction(a.id, now=a.end_time + timedelta(seconds=1))
    return a


def pay(c, a, kind, data):
    return c.post(f"/payments/{a.id}/pay/{kind}", data=data)


def fresh(a):
    db.session.expire_all()
    return db.session.get(Payment, a.payment.id)


def titles(user):
    return [n.title for n in Notification.query.filter_by(user_id=user.id)]


@pytest.fixture
def setup(app, users, cats):  # noqa: F811
    a = won(users, cats)
    return a, client_for(app, "buyer@t.test")


# ---- validators ------------------------------------------------------------------
@pytest.mark.parametrize("num,ok", [("4242424242424242", True), ("4242 4242 4242 4242", True), ("4242-4242-4242-4242", True),
                                    ("4242424242424241", False), ("1234", False), ("", False), ("abcd efgh ijkl mnop", False),
                                    ("4" * 25, False), ("５５５５５５５５５５５５５５５５", False), (None, False)])
def test_card_number_validation(num, ok):
    assert (ps.clean_card_number(num) is not None) == ok


def test_expiry_validation_boundaries():
    now = utcnow()
    this = f"{now.month:02d}/{now.year % 100:02d}"
    last = (now.replace(day=1) - timedelta(days=1))
    assert ps.expiry_ok(this) and ps.expiry_ok("12/99")
    assert not ps.expiry_ok(f"{last.month:02d}/{last.year % 100:02d}")
    for bad in ("13/30", "00/30", "1/30", "12-30", "12/2030", "", None, "ab/cd"):
        assert not ps.expiry_ok(bad), bad


@pytest.mark.parametrize("kind,data,outcome", [
    ("card", {"card_number": PAN_OK}, "success"), ("card", {"card_number": PAN_DECLINED}, "failed"),
    ("card", {"card_number": PAN_FUNDS}, "failed"), ("card", {"card_number": PAN_PENDING}, "pending"),
    ("card", {"card_number": "5555555555554444"}, "success"),
    ("upi", {"upi_id": "bella@okbank"}, "success"), ("upi", {"upi_id": "fail.me@okbank"}, "failed"),
    ("upi", {"upi_id": "Pending@okbank"}, "pending"),
    ("wallet", {"provider": "Demo Wallet", "mobile": "9876543210"}, "success"),
    ("wallet", {"provider": "Demo Wallet", "mobile": "9876540000"}, "failed"),
    ("wallet", {"provider": "Test Pay", "mobile": "9876541111"}, "pending"),
])
def test_gateway_outcomes(kind, data, outcome):
    assert ps.simulate_gateway(kind, data)[0] == outcome


def test_references_are_masked():
    assert ps.simulate_gateway("card", {"card_number": PAN_OK})[2] == "Card **** 4242"
    assert ps.simulate_gateway("upi", {"upi_id": "bellabuyer@okbank"})[2] == "UPI be***@okbank"
    assert ps.simulate_gateway("wallet", {"provider": "Test Pay", "mobile": "9876543210"})[2] == "Test Pay ****3210"
    with pytest.raises(PaymentError):
        ps.simulate_gateway("crypto", {})


# ---- the pay flow -----------------------------------------------------------------
def test_payment_starts_awaiting(app, setup):
    a, c = setup
    p = fresh(a)
    assert p.payment_status == "pending" and p.payment_method is None and p.attempts == 0
    assert p.awaiting_payment and not p.processing and p.amount == Decimal("500")
    page = c.get(f"/payments/{a.id}").data.decode()
    assert "₹500.00" in page and "Red Lamp" in page and "simulated" in page and "Cryptocurrency (not configured)" in page


@pytest.mark.parametrize("kind,data,ref", [
    ("card", card(), "Card **** 4242"),
    ("upi", {"upi_id": "bella@okbank"}, "UPI be***@okbank"),
    ("wallet", {"provider": "Demo Wallet", "mobile": "9876543210"}, "Demo Wallet ****3210"),
])
def test_successful_payment_each_method(app, setup, users, kind, data, ref):
    a, c = setup
    with mail.record_messages() as outbox:
        r = pay(c, a, kind, data)
    assert r.status_code == 302 and r.location.endswith(f"/payments/{a.id}")
    p = fresh(a)
    assert (p.payment_status, p.payment_method, p.method_detail) == ("successful", "simulated", kind)
    assert p.reference == ref and p.gateway_ref.startswith("SIM-") and p.payment_date and p.attempts == 1
    assert p.settle_at is None and p.failure_reason is None
    assert "Payment successful" in titles(users["buyer"]) and "Payment received" in titles(users["seller"])
    assert sorted(m.subject for m in outbox) == ["[ChainBid] Payment received", "[ChainBid] Payment successful"]
    page = c.get(f"/payments/{a.id}").data.decode()
    assert "Payment complete" in page and 'name="card_number"' not in page


def test_amount_and_status_come_from_the_server_not_the_form(app, setup):
    a, c = setup
    # extra fields claiming success and a tiny amount, sent with a card that is declined
    pay(c, a, "card", {**card(PAN_DECLINED), "amount": "1", "payment_status": "successful", "buyer_id": "99"})
    p = fresh(a)
    assert p.payment_status == "failed" and p.amount == Decimal("500") and p.buyer_id != 99
    pay(c, a, "card", {**card(), "amount": "1"})
    assert fresh(a).amount == Decimal("500") and fresh(a).payment_status == "successful"


def test_card_details_are_never_stored_or_echoed(app, setup, users):
    a, c = setup
    # a form error must not send the card number or CVV back to the browser
    bad = pay(c, a, "card", card(expiry="01/20", cvv="987"))
    html = bad.data.decode()
    # (the field's placeholder legitimately shows a sample number, so look at submitted values only)
    assert bad.status_code == 400 and PAN_OK not in html and 'value="4242' not in html and 'value="987"' not in html
    pay(c, a, "card", card(cvv="987"))
    p = fresh(a)
    # every text field that could carry card data (not the random gateway ref or timestamps, which can
    # contain any digits by chance)
    texts = [p.reference, p.method_detail, p.failure_reason or "", p.payment_method] +             [f"{n.title} {n.message} {n.url}" for n in Notification.query]
    dump = " | ".join(texts)
    assert p.reference == "Card **** 4242"
    assert PAN_OK not in dump and "4242 4242" not in dump and "987" not in dump.replace("500.00", "")
    cols = [col.name for col in Payment.__table__.columns]
    assert not any(x in " ".join(cols) for x in ("pan", "cvv", "card_number"))


def test_declined_then_retry_succeeds(app, setup, users):
    a, c = setup
    pay(c, a, "card", card(PAN_DECLINED))
    p = fresh(a)
    assert p.payment_status == "failed" and "declined" in p.failure_reason and p.attempts == 1
    assert p.awaiting_payment and p.payment_date is None and "Payment failed" in titles(users["buyer"])
    assert "Last attempt failed" in c.get(f"/payments/{a.id}").data.decode()
    pay(c, a, "card", card(PAN_FUNDS))
    assert "Insufficient funds" in fresh(a).failure_reason and fresh(a).attempts == 2
    pay(c, a, "upi", {"upi_id": "bella@okbank"})
    p = fresh(a)
    assert (p.payment_status, p.attempts, p.method_detail, p.failure_reason) == ("successful", 3, "upi", None)
    assert titles(users["seller"]).count("Payment received") == 1  # only the successful attempt tells the seller


def test_pending_payment_blocks_resubmission_then_settles(app, setup, users):
    a, c = setup
    pay(c, a, "card", card(PAN_PENDING))
    p = fresh(a)
    assert p.payment_status == "pending" and p.processing and p.settle_at and p.payment_date is None
    assert "Payment processing" in titles(users["buyer"])
    page = c.get(f"/payments/{a.id}").data.decode()
    assert "being processed" in page and 'name="card_number"' not in page and 'data-processing="true"' in page

    pay(c, a, "upi", {"upi_id": "bella@okbank"})  # a second attempt is refused while processing
    p = fresh(a)
    assert p.attempts == 1 and p.method_detail == "card" and p.payment_status == "pending"

    due = p.settle_at
    assert ps.settle_due(now=due - timedelta(seconds=1)) == 0
    with mail.record_messages() as outbox:
        assert ps.settle_due(now=due + timedelta(seconds=1)) == 1
        assert ps.settle_due(now=due + timedelta(seconds=2)) == 0  # settles once
    p = fresh(a)
    assert p.payment_status == "successful" and p.payment_date and p.settle_at is None
    assert len(outbox) == 2 and "Payment received" in titles(users["seller"])


def test_status_endpoint_settles_due_payments(app, setup):
    a, c = setup
    pay(c, a, "wallet", {"provider": "Demo Wallet", "mobile": "9876541111"})
    first = c.get(f"/payments/{a.id}/status").json
    assert (first["status"], first["processing"], first["method"]) == ("pending", True, "simulated")
    fresh(a).settle_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    done = c.get(f"/payments/{a.id}/status").json
    assert (done["status"], done["processing"]) == ("successful", False)


def test_maintenance_settles_pending_payments(app, setup):
    a, c = setup
    pay(c, a, "upi", {"upi_id": "pending@okbank"})
    svc.run_maintenance(utcnow() + timedelta(minutes=5))
    assert fresh(a).payment_status == "successful"


def test_cannot_pay_twice(app, setup, users):
    a, c = setup
    pay(c, a, "card", card())
    before = (fresh(a).attempts, len(Notification.query.all()))
    with mail.record_messages() as outbox:
        r = pay(c, a, "card", card("5555555555554444"))
    assert r.status_code == 302 and outbox == []
    assert (fresh(a).attempts, len(Notification.query.all())) == before
    assert fresh(a).reference == "Card **** 4242"


@pytest.mark.parametrize("kind,data", [
    ("card", card(PAN_OK[:-1] + "1")), ("card", card(card_holder="")), ("card", card(expiry="13/30")),
    ("card", card(cvv="12")), ("card", card(cvv="abcd")), ("upi", {"upi_id": "nobank"}), ("upi", {"upi_id": "@bank"}),
    ("upi", {"upi_id": "a b@bank"}), ("wallet", {"provider": "Demo Wallet", "mobile": "123"}),
    ("wallet", {"provider": "Evil Wallet", "mobile": "9876543210"}), ("wallet", {"provider": "Demo Wallet", "mobile": "98765x3210"}),
])
def test_invalid_input_changes_nothing(app, setup, kind, data):
    a, c = setup
    r = pay(c, a, kind, data)
    p = fresh(a)
    assert r.status_code == 400 and p.attempts == 0 and p.payment_method is None and p.payment_status == "pending"


# ---- access control ---------------------------------------------------------------
def test_payment_pages_need_a_buyer_login(app, setup):
    a, _ = setup
    anon = app.test_client()
    g.pop("_login_user", None)
    for path in (f"/payments/{a.id}", f"/payments/{a.id}/status"):
        assert anon.get(path).status_code == 302
    assert anon.post(f"/payments/{a.id}/pay/card", data=card()).status_code == 302
    for role in ("seller", "admin"):
        cx = client_for(app, f"{role}@t.test")
        assert cx.get(f"/payments/{a.id}").status_code == 403
        assert pay(cx, a, "card", card()).status_code == 403
    assert fresh(a).attempts == 0


def test_only_the_winner_can_see_or_pay(app, setup):
    a, _ = setup
    make_user("other@t.test")
    other = client_for(app, "other@t.test")
    assert other.get(f"/payments/{a.id}").status_code == 404
    assert other.get(f"/payments/{a.id}/status").status_code == 404
    assert pay(other, a, "card", card()).status_code == 404
    assert fresh(a).attempts == 0 and fresh(a).payment_status == "pending"


def test_unknown_auction_and_kind(app, setup):
    a, c = setup
    assert c.get("/payments/9999").status_code == 404
    assert pay(c, a, "crypto", card()).status_code == 404
    assert pay(c, a, "cheque", card()).status_code == 404
    assert c.get(f"/payments/{a.id}/pay/card").status_code == 405


def test_auction_without_payment_is_404(app, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "Live one", 10)  # still running: no winner, no payment
    assert client_for(app, "buyer@t.test").get(f"/payments/{a.id}").status_code == 404


def test_payment_requires_csrf_token_when_enabled():
    class Strict(TestConfig):
        WTF_CSRF_ENABLED = True

    app = create_app(Strict)
    with app.app_context():
        db.create_all()
        assert app.test_client().post("/payments/1/pay/card", data=card()).status_code == 400
        db.drop_all()


# ---- pages and admin numbers ----------------------------------------------------------
def test_won_page_actions_follow_payment_state(app, setup):
    a, c = setup
    d = c.get("/buyer/won").data.decode()
    assert "Pay now" in d and f"/payments/{a.id}" in d
    pay(c, a, "card", card(PAN_PENDING))
    d = c.get("/buyer/won").data.decode()
    assert "Processing" in d and "Pay now" not in d
    ps.settle_due(now=utcnow() + timedelta(minutes=5))
    d = c.get("/buyer/won").data.decode()
    assert "Successful" in d and "Pay now" not in d and "Details" in d


def test_won_notifications_link_to_the_pay_page(app, setup, users):
    a, _ = setup
    urls = {n.title: n.url for n in Notification.query.filter_by(user_id=users["buyer"].id)}
    assert urls["Auction won"] == urls["Payment pending"] == f"/payments/{a.id}"


def test_seller_sees_payment_status(app, setup):
    a, c = setup
    seller = client_for(app, "seller@t.test")
    assert "Pending" in seller.get(f"/seller/products/{a.product_id}").data.decode()
    pay(client_for(app, "buyer@t.test"), a, "card", card())
    assert "Successful" in client_for(app, "seller@t.test").get(f"/seller/products/{a.product_id}").data.decode()


def test_admin_dashboard_shows_pending_and_revenue(app, setup):
    a, c = setup
    admin = client_for(app, "admin@t.test")
    d = admin.get("/admin/").data.decode()
    assert "Pending payments" in d and "₹0.00" in d
    pay(client_for(app, "buyer@t.test"), a, "card", card())
    d = client_for(app, "admin@t.test").get("/admin/").data.decode()
    assert "₹500.00" in d
    assert ps.pending_total() == 0 and ps.revenue_total() == Decimal("500")


# ---- concurrency ----------------------------------------------------------------------
def test_simultaneous_submissions_pay_exactly_once(tmp_path):
    class FileConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'pay.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 30}}

    app = create_app(FileConfig)
    with app.app_context():
        db.create_all()
        seller, buyer = make_user("seller@t.test", "seller"), make_user("buyer@t.test")
        cat = Category(name="Books")
        db.session.add(cat)
        db.session.commit()
        a = make_auction(seller, cat, "Race", 100)
        svc.place_bid(a.id, buyer, "300")
        svc.close_auction(a.id, now=a.end_time + timedelta(seconds=1))
        aid, bid_ = a.id, buyer.id

    n = 8
    barrier = threading.Barrier(n)
    outcomes, errors = [], []

    def worker():
        with app.app_context():
            barrier.wait()
            buyer = db.session.get(User, bid_)
            try:
                p = ps.pay_simulated(aid, buyer, "card", {"card_number": PAN_OK, "card_holder": "x", "expiry": "", "cvv": ""})
                outcomes.append(p.payment_status)
            except PaymentError as e:
                outcomes.append(e.status)
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

    ts = [threading.Thread(target=worker) for _ in range(n)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    assert not errors, errors
    assert outcomes.count("successful") == 1 and outcomes.count(409) == n - 1
    with app.app_context():
        p = Payment.query.one()
        assert p.attempts == 1 and p.payment_status == "successful"
        assert Notification.query.filter_by(title="Payment received").count() == 1
        db.session.remove()
        db.drop_all()
