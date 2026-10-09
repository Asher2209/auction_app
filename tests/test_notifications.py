import logging
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from flask import g

from app.blueprints.auth.tokens import user_from_reset_token
from app.extensions import db, mail, socketio
from app.models import Auction, Notification, Product, Watchlist, utcnow
from app.services import auction_service as svc
from app.services import notifications as notes_svc
from app.services.mailer import send_email

from .conftest import login, make_user
from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)
from .test_listing_validation import card_type, complete_checklist, make_card  # noqa: F401  (card_type is a fixture)


def client_for(app, email):
    g.pop("_login_user", None)
    c = app.test_client()
    login(c, email)
    g.pop("_login_user", None)
    return c


def rows(user, title=None):
    q = Notification.query.filter_by(user_id=user.id)
    return [n for n in q if title is None or n.title == title]


@pytest.fixture
def auction(users, cats):  # noqa: F811
    return make_auction(users["seller"], cats["Books"], "Red Lamp", 100)


def received(sc):
    return [e["args"][0] for e in sc.get_received() if e["name"] == "notification"]


# ---- staging, commit and rollback -------------------------------------------
def test_notify_stores_row_with_link_and_is_unread(users):
    notes_svc.notify(users["buyer"].id, "Hello", "World", url="/auctions/1")
    db.session.commit()
    n = rows(users["buyer"])[0]
    assert (n.title, n.message, n.url, n.is_read) == ("Hello", "World", "/auctions/1", False)


def test_nothing_is_delivered_on_rollback(app, users):
    with mail.record_messages() as outbox:
        notes_svc.notify(users["buyer"].id, "Ghost", "never happened", email=True)
        db.session.rollback()
        db.session.commit()
    assert rows(users["buyer"]) == [] and outbox == []


def test_title_is_truncated_to_column_size(users):
    notes_svc.notify(users["buyer"].id, "x" * 400, "m")
    db.session.commit()
    assert len(rows(users["buyer"])[0].title) == 150


# ---- live push -------------------------------------------------------------------
def test_signed_in_user_gets_live_notification_others_do_not(app, auction, users):
    buyer_client = client_for(app, "buyer@t.test")
    mine = socketio.test_client(app, flask_test_client=buyer_client)
    g.pop("_login_user", None)
    other = socketio.test_client(app, flask_test_client=client_for(app, "admin@t.test"))
    anon = socketio.test_client(app)
    mine.get_received(), other.get_received(), anon.get_received()

    notes_svc.notify(users["buyer"].id, "Ping", "for the buyer only", url="/buyer/")
    db.session.commit()
    got = received(mine)
    assert got == [{"title": "Ping", "message": "for the buyer only", "url": "/buyer/"}]
    assert received(other) == [] and received(anon) == []


def test_bid_events_notify_live(app, auction, users):
    b2 = make_user("b2@t.test")
    first = socketio.test_client(app, flask_test_client=client_for(app, "buyer@t.test"))
    first.get_received()
    svc.place_bid(auction.id, users["buyer"], "120")
    svc.place_bid(auction.id, b2, "150")
    titles = [n["title"] for n in received(first)]
    assert titles == ["Bid accepted", "You have been outbid"]


# ---- email -------------------------------------------------------------------------
def test_outbid_sends_email_but_bid_accepted_does_not(app, auction, users):
    b2 = make_user("b2@t.test")
    with mail.record_messages() as outbox:
        svc.place_bid(auction.id, users["buyer"], "120")
        assert outbox == []  # routine confirmations stay in-app
        svc.place_bid(auction.id, b2, "150")
    assert len(outbox) == 1
    m = outbox[0]
    assert m.recipients == ["buyer@t.test"] and m.subject == "[ChainBid] You have been outbid"
    assert f"http://127.0.0.1:5000/auctions/{auction.id}" in m.body and "₹150.00" in m.body


def test_winner_and_seller_emails_on_close(app, auction, users):
    svc.place_bid(auction.id, users["buyer"], "120")
    with mail.record_messages() as outbox:
        svc.close_auction(auction.id, now=auction.end_time + timedelta(seconds=1))
    by_rcpt = {m.recipients[0]: m.subject for m in outbox}
    assert by_rcpt["buyer@t.test"] == "[ChainBid] Auction won"
    assert by_rcpt["seller@t.test"] == "[ChainBid] Winner selected"
    assert len(outbox) == 2  # "Payment pending" and "Auction completed" are in-app only


def test_admin_decisions_email_the_seller(app, users, cats, card_type):  # noqa: F811
    p = make_card(users["seller"], cats["Books"], card_type, verified=False, asset=False)
    v = p.collectible_verification
    admin = client_for(app, "admin@t.test")
    complete_checklist(admin, v.id)
    with mail.record_messages() as outbox:
        admin.post(f"/admin/cards/verify/{v.id}/approve", data={"approval_notes": "ok"})
    assert [m.subject for m in outbox] == ["[ChainBid] Card approved"]
    assert f"/seller/cards/{p.collectible_card.id}" in outbox[0].body


def test_inactive_user_gets_no_email(app, users):
    users["buyer"].is_active_user = False
    db.session.commit()
    with mail.record_messages() as outbox:
        notes_svc.notify(users["buyer"].id, "Hi", "m", email=True)
        db.session.commit()
    assert outbox == [] and len(rows(users["buyer"])) == 1  # still stored in-app


def test_mail_failure_never_breaks_the_action(app, auction, users, monkeypatch, caplog):
    def boom(msg):
        raise ConnectionError("smtp down")

    monkeypatch.setattr(mail, "send", boom)
    b2 = make_user("b2@t.test")
    svc.place_bid(auction.id, users["buyer"], "120")
    with caplog.at_level(logging.ERROR):
        svc.place_bid(auction.id, b2, "150")  # triggers the outbid email
    db.session.refresh(auction)
    assert auction.current_bid == Decimal("150") and "Email delivery failed" in caplog.text


def test_dev_mode_logs_email_instead_of_sending(app, caplog):
    app.testing = False  # a non-test run with no MAIL_SERVER configured
    try:
        with mail.record_messages() as outbox, caplog.at_level(logging.INFO):
            send_email("x@t.test", "Subject line", "Body text")
    finally:
        app.testing = True
    assert outbox == [] and "[dev email]" in caplog.text and "Body text" in caplog.text


def test_email_without_recipient_is_skipped(app):
    with mail.record_messages() as outbox:
        send_email(None, "s", "b")
        send_email("", "s", "b")
    assert outbox == []


def test_email_subject_cannot_be_used_for_header_injection(app):
    from flask_mail import BadHeaderError
    with pytest.raises(BadHeaderError):
        with mail.record_messages():
            from flask_mail import Message
            mail.send(Message(subject="Hi\nBcc: evil@x.test", recipients=["a@t.test"], body="x"))


# ---- password reset by email -------------------------------------------------------
def test_forgot_password_emails_a_working_link(client, users):
    with mail.record_messages() as outbox:
        client.post("/auth/forgot-password", data={"email": "buyer@t.test"})
    assert len(outbox) == 1 and outbox[0].recipients == ["buyer@t.test"]
    link = re.search(r"http://\S+/auth/reset-password/\S+", outbox[0].body).group(0)
    token = link.rsplit("/", 1)[1]
    assert user_from_reset_token(token).id == users["buyer"].id
    assert client.get(f"/auth/reset-password/{token}").status_code == 200


def test_forgot_password_sends_nothing_for_unknown_or_inactive(client, users):
    users["seller"].is_active_user = False
    db.session.commit()
    with mail.record_messages() as outbox:
        a = client.post("/auth/forgot-password", data={"email": "ghost@t.test"}, follow_redirects=True)
        b = client.post("/auth/forgot-password", data={"email": "seller@t.test"}, follow_redirects=True)
        c = client.post("/auth/forgot-password", data={"email": "buyer@t.test"}, follow_redirects=True)
    assert len(outbox) == 1
    msg = b"If that email is registered"
    assert msg in a.data and msg in b.data and msg in c.data


# ---- ending soon ------------------------------------------------------------------
def minutes_before_end(auction, minutes):
    return auction.end_time - timedelta(minutes=minutes)


def test_ending_soon_notifies_seller_bidders_and_watchers_once(app, auction, users):
    watcher = make_user("w@t.test")
    db.session.add(Watchlist(user_id=watcher.id, product_id=auction.product_id))
    db.session.commit()
    svc.place_bid(auction.id, users["buyer"], "120")
    now = minutes_before_end(auction, 8)
    with mail.record_messages() as outbox:
        assert svc.notify_ending_soon(now) == 1
        assert svc.notify_ending_soon(now) == 0  # not repeated
        svc.run_maintenance(now + timedelta(minutes=1))  # nor on later ticks
    for u in (users["seller"], users["buyer"], watcher):
        assert len(rows(u, "Auction ending soon")) == 1, u.email
    assert "ends in about 8 minute(s)" in rows(watcher, "Auction ending soon")[0].message
    assert sorted(m.recipients[0] for m in outbox) == ["buyer@t.test", "seller@t.test", "w@t.test"]
    db.session.refresh(auction)
    assert auction.ending_notified is True


def test_ending_soon_not_sent_too_early_or_after_the_end_or_when_closed(app, auction, users):
    assert svc.notify_ending_soon(minutes_before_end(auction, 30)) == 0
    assert svc.notify_ending_soon(auction.end_time + timedelta(seconds=1)) == 0
    assert rows(users["seller"], "Auction ending soon") == []
    closed = make_auction(users["seller"], Product.query.first().category, "Done", 10, status="closed", hours_left=0)
    assert svc.notify_ending_soon(closed.end_time - timedelta(minutes=1)) == 0


def test_ending_soon_only_for_interested_users(app, auction, users):
    stranger = make_user("s@t.test")
    svc.notify_ending_soon(minutes_before_end(auction, 5))
    assert rows(stranger) == [] and rows(users["buyer"]) == []
    assert len(rows(users["seller"], "Auction ending soon")) == 1


def test_extension_does_not_trigger_a_second_ending_notice(app, auction, users):
    svc.place_bid(auction.id, users["buyer"], "120")
    svc.notify_ending_soon(minutes_before_end(auction, 9))
    svc.place_bid(auction.id, make_user("b2@t.test"), "130", now=auction.end_time - timedelta(seconds=20))  # extends
    svc.notify_ending_soon(auction.end_time - timedelta(minutes=1))
    assert len(rows(users["seller"], "Auction ending soon")) == 1


def test_ending_soon_runs_from_maintenance(app, auction, users):
    svc.run_maintenance(minutes_before_end(auction, 3))
    assert len(rows(users["seller"], "Auction ending soon")) == 1


# ---- notification pages ----------------------------------------------------------------
def test_notification_pages_require_login(client):
    assert client.get("/notifications/").status_code == 302
    for path in ("/notifications/read-all", "/notifications/1/read"):
        assert client.post(path).status_code == 302
    assert client.get("/notifications/1/go").status_code == 302


def test_list_shows_only_own_notifications_newest_first(app, users):
    notes_svc.notify(users["buyer"].id, "First one", "a")
    db.session.commit()
    notes_svc.notify(users["buyer"].id, "Second one", "b")
    notes_svc.notify(users["seller"].id, "Not yours", "c")
    db.session.commit()
    d = client_for(app, "buyer@t.test").get("/notifications/").data.decode()
    assert "Not yours" not in d and d.index("Second one") < d.index("First one")


def test_unread_badge_counts_and_clears(app, users):
    for i in range(3):
        notes_svc.notify(users["buyer"].id, f"N{i}", "m")
    db.session.commit()
    c = client_for(app, "buyer@t.test")
    d = c.get("/").data.decode()
    assert re.search(r'id="notif-badge"[^>]*>3<', d)
    c.post("/notifications/read-all")
    d = c.get("/").data.decode()
    assert 'id="notif-badge" class="badge rounded-pill text-bg-danger d-none"' in d
    g.pop("_login_user", None)  # (the fixture's long-lived app context would otherwise leak the buyer)
    assert 'id="notif-badge"' not in app.test_client().get("/").data.decode()  # anonymous: no bell


def test_unread_filter_and_mark_one_read(app, users):
    notes_svc.notify(users["buyer"].id, "Alpha", "a")
    notes_svc.notify(users["buyer"].id, "Beta", "b")
    db.session.commit()
    c = client_for(app, "buyer@t.test")
    alpha = rows(users["buyer"], "Alpha")[0]
    assert c.post(f"/notifications/{alpha.id}/read").status_code == 302
    d = c.get("/notifications/?filter=unread").data.decode()
    assert "Beta" in d and "Alpha" not in d
    assert "Alpha" in c.get("/notifications/").data.decode()


def test_cannot_touch_someone_elses_notification(app, users):
    notes_svc.notify(users["seller"].id, "Private", "m", url="/seller/")
    db.session.commit()
    n = rows(users["seller"])[0]
    c = client_for(app, "buyer@t.test")
    assert c.post(f"/notifications/{n.id}/read").status_code == 404
    assert c.get(f"/notifications/{n.id}/go").status_code == 404
    db.session.refresh(n)
    assert n.is_read is False
    c.post("/notifications/read-all")  # only affects own rows
    db.session.refresh(n)
    assert n.is_read is False


def test_go_marks_read_and_follows_only_in_site_links(app, users):
    notes_svc.notify(users["buyer"].id, "Local", "m", url="/auctions/")
    notes_svc.notify(users["buyer"].id, "Evil", "m", url="https://evil.example/x")
    notes_svc.notify(users["buyer"].id, "Evil2", "m", url="//evil.example/x")
    notes_svc.notify(users["buyer"].id, "NoLink", "m")
    db.session.commit()
    c = client_for(app, "buyer@t.test")
    loc = {n.title: c.get(f"/notifications/{n.id}/go").location for n in rows(users["buyer"])}
    assert loc["Local"].endswith("/auctions/")
    for t in ("Evil", "Evil2", "NoLink"):
        assert loc[t].endswith("/notifications/"), t
    assert all(n.is_read for n in rows(users["buyer"]))


def test_notification_text_is_escaped(app, users):
    notes_svc.notify(users["buyer"].id, "<b>x</b>", "<script>alert(1)</script>")
    db.session.commit()
    d = client_for(app, "buyer@t.test").get("/notifications/").data.decode()
    assert "<script>alert(1)</script>" not in d and "&lt;script&gt;" in d


def test_pagination(app, users):
    for i in range(25):
        notes_svc.notify(users["buyer"].id, f"Note {i:02d}", "m")
    db.session.commit()
    c = client_for(app, "buyer@t.test")
    assert c.get("/notifications/").data.decode().count("list-group-item d-flex") == 20
    assert c.get("/notifications/?page=2").data.decode().count("list-group-item d-flex") == 5
    assert c.get("/notifications/?page=99").status_code == 200


def test_every_role_can_use_notifications(app, users):
    for role in ("buyer", "seller", "admin"):
        assert client_for(app, f"{role}@t.test").get("/notifications/").status_code == 200
