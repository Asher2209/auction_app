import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from flask import g

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import Category, Feedback, Notification, Product, Review, User, utcnow
from app.services import auction_service as svc
from app.services import review_service as rs
from app.services.review_service import ReviewError

from .conftest import login, make_user
from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)
from .test_payments import card, client_for, pay, titles, won


def rows(**kw):
    return Review.query.filter_by(**kw).all()


def paid(app, users, cats, amount="500", title="Red Lamp"):  # noqa: F811
    """A closed auction won AND paid by the buyer. Returns (auction, buyer client)."""
    a = make_auction(users["seller"], cats["Books"], title, 100)
    svc.place_bid(a.id, users["buyer"], amount)
    svc.close_auction(a.id, now=a.end_time + timedelta(seconds=1))
    c = client_for(app, "buyer@t.test")
    pay(c, a, "card", card())
    return a, c


def review(c, a, rating="5", comment="Great item", **extra):
    return c.post(f"/reviews/{a.id}", data={"rating": rating, "comment": comment, **extra})


def detail(c, a):
    return c.get(f"/auctions/{a.id}").data.decode()


# ---- who may review --------------------------------------------------------------------
def test_paying_buyer_can_review_once_and_it_shows_on_the_page(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    assert 'name="rating"' in detail(c, a) and "Verified purchase" in detail(c, a)
    r = review(c, a, "4", "Works well, fast delivery")
    assert r.status_code == 302 and r.location.endswith(f"/auctions/{a.id}#reviews")
    rv = Review.query.one()
    assert (rv.buyer_id, rv.product_id, rv.rating, rv.comment) == (users["buyer"].id, a.product_id, 4, "Works well, fast delivery")
    html = detail(client_for(app, "buyer@t.test"), a)
    assert "Works well, fast delivery" in html and "4.0 / 5" in html and "1 review" in html and "Edit your review" in html


def test_unpaid_buyers_cannot_review(app, users, cats):  # noqa: F811
    a = won(users, cats)  # won but not paid
    c = client_for(app, "buyer@t.test")
    assert 'name="rating"' not in detail(c, a)
    for payload in ("card-declined", "pending"):
        if payload == "card-declined":
            pay(c, a, "card", card("4000000000000002"))
        else:
            pay(c, a, "card", card("4000000000003220"))
        assert review(c, a).status_code == 302 and Review.query.count() == 0
    assert Review.query.count() == 0


def test_only_the_paying_buyer_can_review_not_other_buyers_sellers_or_admins(app, users, cats):  # noqa: F811
    a, _ = paid(app, users, cats)
    make_user("other@t.test")
    other = client_for(app, "other@t.test")
    assert 'name="rating"' not in detail(other, a)
    review(other, a)
    assert Review.query.count() == 0
    for role in ("seller", "admin"):
        assert review(client_for(app, f"{role}@t.test"), a).status_code == 403
    g.pop("_login_user", None)
    assert review(app.test_client(), a).status_code == 302  # anonymous: sent to log in
    assert Review.query.count() == 0


def test_service_refuses_non_buyers_directly(app, users, cats):  # noqa: F811
    a, _ = paid(app, users, cats)
    for who in ("seller", "admin"):
        with pytest.raises(ReviewError) as e:
            rs.save_review(users[who], a.id, "5", "x")
        assert e.value.status == 403


# ---- validation ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["0", "6", "-1", "abc", "3.5", "", "  ", "٣", "1e0", "03", "+4", "5 5", None])
def test_invalid_ratings_are_rejected(app, users, cats, bad):  # noqa: F811
    a, c = paid(app, users, cats)
    data = {"comment": "x"} if bad is None else {"rating": bad, "comment": "x"}
    c.post(f"/reviews/{a.id}", data=data)
    assert Review.query.count() == 0


def test_every_valid_rating_is_accepted(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    for n in "12345":
        review(c, a, n)
        assert Review.query.one().rating == int(n)


def test_comment_rules(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a, "5", "y" * 1001)
    assert Review.query.count() == 0  # too long
    review(c, a, "5", "y" * 1000)
    assert len(Review.query.one().comment) == 1000  # exactly the limit is fine
    review(c, a, "5", "   \n  ")
    assert Review.query.one().comment is None  # whitespace-only means no comment
    review(c, a, "5", "  hello  \r\nworld ")
    assert Review.query.one().comment == "hello  \nworld"


def test_comments_are_escaped_everywhere(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a, "5", "<script>alert(1)</script> & <b>bold</b>")
    for html in (detail(client_for(app, "buyer@t.test"), a), client_for(app, "seller@t.test").get(f"/seller/products/{a.product_id}").data.decode(),
                 client_for(app, "admin@t.test").get("/admin/reviews").data.decode()):
        assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html and "<b>bold</b>" not in html


# ---- editing, deleting, uniqueness ------------------------------------------------------------
def test_reviewing_again_updates_the_same_review(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a, "2", "meh")
    first = Review.query.one()
    assert first.updated_at is None
    review(c, a, "5", "actually great")
    rv = Review.query.one()
    assert rv.id == first.id and (rv.rating, rv.comment) == (5, "actually great") and rv.updated_at
    assert "(edited)" in detail(client_for(app, "buyer@t.test"), a)
    assert titles(users["seller"]).count("New review") == 1  # edits do not notify again


def test_seller_is_told_about_a_new_review(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a, "4")
    n = Notification.query.filter_by(user_id=users["seller"].id, title="New review").one()
    assert "Red Lamp" in n.message and n.url == f"/seller/products/{a.product_id}"


def test_buyer_can_delete_their_own_review_and_write_a_new_one(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a, "1", "bad")
    assert c.post(f"/reviews/{a.id}/delete").status_code == 302
    assert Review.query.count() == 0
    review(c, a, "5", "second try")
    assert Review.query.one().comment == "second try"


def test_deleting_when_there_is_no_review_is_harmless(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    assert c.post(f"/reviews/{a.id}/delete").status_code == 302 and Review.query.count() == 0


def test_cannot_delete_or_touch_someone_elses_review(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a, "5", "mine")
    make_user("other@t.test")
    other = client_for(app, "other@t.test")
    other.post(f"/reviews/{a.id}/delete")
    review(other, a, "1", "hijack")
    rv = Review.query.one()
    assert rv.buyer_id == users["buyer"].id and rv.comment == "mine" and rv.rating == 5


def test_review_endpoints_need_post_and_csrf(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    assert c.get(f"/reviews/{a.id}").status_code == 405 and c.get(f"/reviews/{a.id}/delete").status_code == 405


def test_review_requires_csrf_token_when_enabled():
    class Strict(TestConfig):
        WTF_CSRF_ENABLED = True

    app = create_app(Strict)
    with app.app_context():
        db.create_all()
        assert app.test_client().post("/reviews/1", data={"rating": "5"}).status_code == 400
        db.drop_all()


# ---- statistics -----------------------------------------------------------------------------------
def make_reviews(app, users, cats, ratings, hidden=()):  # noqa: F811
    """One product, one review per rating from different buyers (inserted directly)."""
    a = make_auction(users["seller"], cats["Books"], "Stat Item", 100)
    for i, r in enumerate(ratings):
        b = make_user(f"rv{i}@t.test")
        db.session.add(Review(product_id=a.product_id, buyer_id=b.id, rating=r, is_hidden=i in hidden))
    db.session.commit()
    return a


def test_average_and_count(app, users, cats):  # noqa: F811
    a = make_reviews(app, users, cats, [5, 4, 4])
    assert rs.stats_for_products([a.product_id]) == {a.product_id: (4.3, 3)}
    assert rs.stats_for_products([]) == {} and rs.stats_for_products([99999]) == {}


def test_hidden_reviews_do_not_count_anywhere(app, users, cats):  # noqa: F811
    a = make_reviews(app, users, cats, [5, 1, 1], hidden=(1, 2))
    assert rs.stats_for_products([a.product_id]) == {a.product_id: (5.0, 1)}
    assert len(rs.visible_reviews(a.product_id)) == 1
    assert rs.seller_stats(users["seller"].id) == (5.0, 1)


def test_seller_average_spans_all_their_products(app, users, cats):  # noqa: F811
    make_reviews(app, users, cats, [5, 5])
    b = make_auction(users["seller"], cats["Sports"], "Other item", 10)
    db.session.add(Review(product_id=b.product_id, buyer_id=make_user("z@t.test").id, rating=2))
    db.session.commit()
    assert rs.seller_stats(users["seller"].id) == (4.0, 3)
    assert rs.seller_stats(users["buyer"].id) is None


@pytest.mark.parametrize("value,expected", [(5, "★" * 5), (0, "☆" * 5), (3, "★" * 3 + "☆" * 2),
                                            (4.4, "★" * 4 + "☆"), (4.6, "★" * 5), (9, "★" * 5), (-2, "☆" * 5)])
def test_stars_filter(app, value, expected):
    assert app.jinja_env.filters["stars"](value) == expected


# ---- where reviews appear ------------------------------------------------------------------------
def test_public_page_shows_masked_reviewers_and_no_private_data(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a, "5", "Lovely")
    g.pop("_login_user", None)
    html = detail(app.test_client(), a)
    assert "Lovely" in html and "b***" in html and "Verified purchase" in html and "5.0 / 5" in html
    assert "buyer@t.test" not in html and 'name="rating"' not in html  # anonymous visitors cannot review
    assert "Seller average: 5.0 / 5 (1)" in html


def test_ratings_appear_on_cards(app, users, cats):  # noqa: F811
    a = make_reviews(app, users, cats, [4, 5])
    g.pop("_login_user", None)
    anon = app.test_client()
    for path in ("/", "/auctions/"):
        html = anon.get(path).data.decode()
        assert "&#9733;</span> 4.5 <span" in html and "(2)" in html, path
    b = client_for(app, "buyer@t.test")
    b.post(f"/buyer/watchlist/{a.id}/toggle")
    assert "4.5" in b.get("/buyer/watchlist").data.decode()


def test_seller_sees_reviews_with_names_and_only_their_own(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a, "4", "Nice")
    other_seller = make_user("seller2@t.test", "seller")
    x = make_auction(other_seller, cats["Books"], "Foreign", 50)
    db.session.add(Review(product_id=x.product_id, buyer_id=users["buyer"].id, rating=1, comment="not yours to see"))
    db.session.commit()
    s = client_for(app, "seller@t.test")
    page = s.get("/seller/reviews").data.decode()
    assert "Nice" in page and "buyer" in page and "Red Lamp" in page and "not yours to see" not in page and "4.0 / 5" in page
    detail_page = s.get(f"/seller/products/{a.product_id}").data.decode()
    assert "Nice" in detail_page and "4.0 / 5 (1)" in detail_page
    assert s.get("/seller/reviews").status_code == 200
    for role in ("buyer", "admin"):
        assert client_for(app, f"{role}@t.test").get("/seller/reviews").status_code == 403


def test_review_button_on_the_won_page(app, users, cats):  # noqa: F811
    a = won(users, cats)
    c = client_for(app, "buyer@t.test")
    assert f"/auctions/{a.id}#reviews" not in c.get("/buyer/won").data.decode()
    pay(c, a, "card", card())
    assert f"/auctions/{a.id}#reviews" in c.get("/buyer/won").data.decode()


# ---- moderation ------------------------------------------------------------------------------------------
def hide(admin, rv, reason="Contains abuse"):
    return admin.post(f"/admin/reviews/{rv.id}/hide", data={"reason": reason})


def test_admin_hides_a_review_and_everything_follows(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a, "1", "Terrible seller, total scam")
    rv = Review.query.one()
    admin = client_for(app, "admin@t.test")
    assert hide(admin, rv).status_code == 302
    db.session.refresh(rv)
    assert rv.is_hidden and rv.hidden_reason == "Contains abuse"
    assert "Review hidden" in titles(users["buyer"])
    g.pop("_login_user", None)
    public = detail(app.test_client(), a)
    assert "total scam" not in public and "No reviews yet." in public and "Seller average" not in public
    assert "total scam" not in client_for(app, "seller@t.test").get("/seller/reviews").data.decode()
    assert rs.stats_for_products([a.product_id]) == {}
    author = detail(client_for(app, "buyer@t.test"), a)
    assert "hidden by a moderator: Contains abuse" in author and 'name="rating"' not in author


def test_a_hidden_review_cannot_be_edited_deleted_or_replaced_by_its_author(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a, "1", "bad words")
    hide(client_for(app, "admin@t.test"), Review.query.one())
    c = client_for(app, "buyer@t.test")
    review(c, a, "5", "all fine now")
    c.post(f"/reviews/{a.id}/delete")
    rv = Review.query.one()
    assert (rv.rating, rv.comment, rv.is_hidden) == (1, "bad words", True)
    with pytest.raises(ReviewError):
        rs.save_review(users["buyer"], a.id, "5", "x")


def test_hide_needs_a_reason(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a)
    admin = client_for(app, "admin@t.test")
    for reason in ("", "no", "   "):
        hide(admin, Review.query.one(), reason)
    assert Review.query.one().is_hidden is False


def test_restore_and_delete(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a, "5", "fine")
    rv = Review.query.one()
    admin = client_for(app, "admin@t.test")
    hide(admin, rv)
    admin.post(f"/admin/reviews/{rv.id}/unhide")
    db.session.refresh(rv)
    assert rv.is_hidden is False and rv.hidden_reason is None and "Review restored" in titles(users["buyer"])
    assert rs.stats_for_products([a.product_id])[a.product_id] == (5.0, 1)
    admin.post(f"/admin/reviews/{rv.id}/delete")
    assert Review.query.count() == 0


def test_admin_review_list_filters_and_search(app, users, cats):  # noqa: F811
    a = make_reviews(app, users, cats, [5, 1, 3], hidden=(1,))
    Review.query.filter_by(rating=3).one().comment = "needle in haystack"
    db.session.commit()
    admin = client_for(app, "admin@t.test")
    def count(qs):
        return admin.get("/admin/reviews" + qs).data.decode().count('class="card mb-2')
    assert count("") == 3 and count("?status=hidden") == 1 and count("?status=visible") == 2
    assert count("?q=needle") == 1 and count("?q=rv0@") == 1 and count("?q=Stat+Item") == 3
    assert count("?q=%25") == 0 and count("?status=bogus") == 3 and count("?page=99") == 0
    assert admin.get("/admin/reviews?q=' OR 1=1 --").status_code == 200


def test_only_admins_can_moderate(app, users, cats):  # noqa: F811
    a, c = paid(app, users, cats)
    review(c, a)
    rv = Review.query.one()
    for role in ("buyer", "seller"):
        cl = client_for(app, f"{role}@t.test")
        assert cl.get("/admin/reviews").status_code == 403
        for path in (f"hide", f"unhide", f"delete"):
            assert cl.post(f"/admin/reviews/{rv.id}/{path}", data={"reason": "xxxxxx"}).status_code == 403
    g.pop("_login_user", None)
    anon = app.test_client()
    assert anon.get("/admin/reviews").status_code == 302 and anon.post(f"/admin/reviews/{rv.id}/hide").status_code == 302
    assert Review.query.one().is_hidden is False
    admin = client_for(app, "admin@t.test")
    for path in ("hide", "unhide", "delete"):
        assert admin.post(f"/admin/reviews/9999/{path}", data={"reason": "xxxxxx"}).status_code == 404


# ---- concurrency ------------------------------------------------------------------------------------------------
def test_simultaneous_submissions_make_exactly_one_review(tmp_path):
    class FileConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'rv.db'}"
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
        from app.services import payment_service as ps
        ps.pay_simulated(a.id, buyer, "card", {"card_number": "4242424242424242", "card_holder": "x", "expiry": "", "cvv": ""})
        aid, buyer_id = a.id, buyer.id

    n = 6
    barrier = threading.Barrier(n)
    errors = []

    def worker(i):
        with app.app_context():
            barrier.wait()
            try:
                rs.save_review(db.session.get(User, buyer_id), aid, str(1 + i % 5), f"attempt {i}")
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    assert not errors, errors
    with app.app_context():
        assert Review.query.count() == 1
        assert Notification.query.filter_by(title="New review").count() == 1  # only the creator notifies
        db.session.remove()
        db.drop_all()


# ---- site feedback ---------------------------------------------------------------------------------------
def send_feedback(c, msg="The browse page is great but search could be faster."):
    return c.post("/feedback", data={"message": msg})


def test_feedback_is_stored_and_acknowledged(app, users):
    c = client_for(app, "buyer@t.test")
    assert c.get("/feedback").status_code == 200
    r = send_feedback(c)
    assert r.status_code == 302
    f = Feedback.query.one()
    assert f.user_id == users["buyer"].id and f.message.startswith("The browse page") and f.created_at
    assert b"feedback was sent" in c.get("/feedback").data


@pytest.mark.parametrize("msg", ["", "   ", "short", "x" * 1001])
def test_bad_feedback_is_rejected(app, users, msg):
    send_feedback(client_for(app, "buyer@t.test"), msg)
    assert Feedback.query.count() == 0


def test_feedback_limit_per_day(app, users):
    c = client_for(app, "buyer@t.test")
    for i in range(10):
        send_feedback(c, f"Feedback number {i} with enough text")
    assert Feedback.query.count() == 10
    r = send_feedback(c, "The eleventh message should be refused")
    assert r.status_code == 200 and b"a lot of feedback today" in r.data and Feedback.query.count() == 10
    # entries older than 24h stop counting
    for f in Feedback.query.all():
        f.created_at = utcnow() - timedelta(hours=25)
    db.session.commit()
    send_feedback(c, "Now it is fine again, after a day")
    assert Feedback.query.count() == 11


def test_feedback_is_per_user(app, users):
    for i in range(10):
        db.session.add(Feedback(user_id=users["seller"].id, message=f"spam {i} spam spam"))
    db.session.commit()
    send_feedback(client_for(app, "buyer@t.test"))
    assert Feedback.query.filter_by(user_id=users["buyer"].id).count() == 1


def test_feedback_needs_login_and_works_for_every_role(app, users):
    g.pop("_login_user", None)
    anon = app.test_client()
    assert anon.get("/feedback").status_code == 302 and send_feedback(anon).status_code == 302
    for role in ("buyer", "seller", "admin"):
        assert send_feedback(client_for(app, f"{role}@t.test")).status_code == 302
    assert Feedback.query.count() == 3
    assert "Send feedback" in client_for(app, "buyer@t.test").get("/").data.decode()
    g.pop("_login_user", None)
    assert "Send feedback" not in app.test_client().get("/").data.decode()


def test_admin_manages_feedback(app, users):
    send_feedback(client_for(app, "buyer@t.test"), "<script>alert(1)</script> please add dark mode")
    send_feedback(client_for(app, "seller@t.test"), "Seller wants bulk upload of images")
    admin = client_for(app, "admin@t.test")
    html = admin.get("/admin/feedback").data.decode()
    assert "dark mode" in html and "bulk upload" in html and "buyer@t.test" in html
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "bulk upload" in admin.get("/admin/feedback?q=BULK").data.decode() and "dark mode" not in admin.get("/admin/feedback?q=bulk").data.decode()
    assert "dark mode" not in admin.get("/admin/feedback?q=%25").data.decode()
    f = Feedback.query.first()
    assert admin.post(f"/admin/feedback/{f.id}/delete").status_code == 302 and Feedback.query.count() == 1
    assert admin.post("/admin/feedback/9999/delete").status_code == 404
    assert admin.get("/admin/feedback?page=99").status_code == 200


def test_only_admins_see_feedback(app, users):
    send_feedback(client_for(app, "buyer@t.test"))
    fid = Feedback.query.one().id
    for role in ("buyer", "seller"):
        cl = client_for(app, f"{role}@t.test")
        assert cl.get("/admin/feedback").status_code == 403 and cl.post(f"/admin/feedback/{fid}/delete").status_code == 403
    g.pop("_login_user", None)
    assert app.test_client().get("/admin/feedback").status_code == 302
    assert Feedback.query.count() == 1
