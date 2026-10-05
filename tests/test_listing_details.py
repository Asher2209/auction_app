"""More detail when listing an item: condition, location, a longer description, and each category's own set of questions."""
import re

import pytest
from flask import g

from app.extensions import db
from app.models import Category, CategoryQuestion, Product, ProductAnswer
from app.services import catalog_questions as qs

from .test_accessibility import audit
from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)
from .test_legal import anon
from .test_payments import client_for
from .test_seller import answer_data, form_data, post_new


def questions(name):
    return qs.questions_for(Category.query.filter_by(name=name).one().id)


def by_label(name):
    return {q.label: q for q in questions(name)}


# ---- the question sets ----------------------------------------------------------------------------------------------
def test_each_starter_category_has_its_own_tailored_set(app, cats):  # noqa: F811
    assert set(qs.DEFAULTS) == {"Books", "Collectibles", "Electronics", "Fashion", "Home & Garden", "Sports"}
    label_sets = {}
    for name, specs in qs.DEFAULTS.items():
        assert len(specs) >= 6 and any(s["required"] for s in specs), name
        labels = [s["label"] for s in specs]
        assert len(set(labels)) == len(labels), name  # no repeated question
        for s in specs:
            assert s["kind"] in qs.KINDS
            assert s["kind"] != "choice" or len(s["choices"]) >= 2, (name, s["label"])
        label_sets[name] = set(labels)
    assert "Author" in label_sets["Books"] and "Model" in label_sets["Electronics"] and "Size" in label_sets["Fashion"]
    assert "Which sport is it for?" in label_sets["Sports"] and "Dimensions" in label_sets["Home & Garden"]
    assert "Year or era" in label_sets["Collectibles"]
    names = list(label_sets)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert label_sets[a] != label_sets[b]
            assert len(label_sets[a] & label_sets[b]) <= len(label_sets[a]) // 2, (a, b)  # genuinely different, not copies


def test_a_category_gets_its_set_once_and_unknown_categories_get_the_generic_one(app):
    db.session.add_all([Category(name="Books"), Category(name="Vintage Cars")])
    db.session.commit()
    qs.ensure_all()
    books, cars = (Category.query.filter_by(name=n).one() for n in ("Books", "Vintage Cars"))
    assert [q.label for q in books.questions][:2] == ["Author", "Publisher"]
    assert [q.label for q in cars.questions] == [s["label"] for s in qs.GENERIC]
    n = CategoryQuestion.query.count()
    qs.ensure_all()
    qs.ensure_all()
    assert CategoryQuestion.query.count() == n  # idempotent


def test_question_keys_are_unique_within_a_category(app, cats):  # noqa: F811
    cat = Category.query.filter_by(name="Books").one()
    qs.ensure_default_questions(cat)
    a = qs.make_question(cat, qs.Q("Author"), 99)
    cat.questions.append(a)
    db.session.commit()
    keys = [q.key for q in cat.questions]
    assert len(set(keys)) == len(keys) and "author_2" in keys


# ---- reading answers ---------------------------------------------------------------------------------------------------
class FakeQ:
    def __init__(self, id, kind="text", required=False, choices=""):
        self.id, self.kind, self.required, self.choices = id, kind, required, choices

    @property
    def choice_list(self):
        return [c for c in self.choices.splitlines() if c]


@pytest.mark.parametrize("kind,raw,ok,stored", [
    ("text", "Hello", True, "Hello"), ("number", "2019", True, "2019"), ("number", "1,200.50", True, "1200.5"), ("number", "abc", False, None),
    ("number", "NaN", False, None), ("number", "Infinity", False, None), ("number", "1e999", False, None), ("number", "-5", True, "-5"),
    ("choice", "Hardcover", True, "Hardcover"), ("choice", "Leather", False, None), ("yesno", "yes", True, "Yes"), ("yesno", "NO", True, "No"),
    ("yesno", "maybe", False, None), ("text", "x" * 201, False, None), ("longtext", "y" * 1000, True, "y" * 1000), ("longtext", "y" * 1001, False, None),
])
def test_each_answer_type_is_validated(kind, raw, ok, stored):
    q = FakeQ(1, kind, choices="Hardcover\nPaperback")
    answers, errors = qs.parse_answers({"q_1": raw}, [q])
    assert (not errors) == ok
    if ok:
        assert answers == {1: stored}


def test_required_optional_and_foreign_fields():
    required, optional = FakeQ(1, required=True), FakeQ(2)
    answers, errors = qs.parse_answers({"q_1": "  ", "q_2": ""}, [required, optional])
    assert errors == {1: "Please answer this question."} and answers == {}
    answers, errors = qs.parse_answers({"q_1": " kept ", "q_99": "someone else's question", "q_abc": "x"}, [required, optional])
    assert answers == {1: "kept"} and errors == {}  # blank optional is skipped; unknown fields never get in


# ---- the listing form ----------------------------------------------------------------------------------------------------
def make_listing(client, cat, **over):
    r = post_new(client, cat, **over)
    assert r.status_code == 302, r.data[:400]
    return Product.query.order_by(Product.id.desc()).first()


def test_a_listing_stores_condition_location_extras_and_its_category_answers(app, users, cats):  # noqa: F811
    c = client_for(app, "seller@t.test")
    books = by_label("Books")
    p = make_listing(c, cats["Books"], condition="like_new", pickup_location="  Pune, Maharashtra ", whats_included="Dust jacket and a bookmark",
                     known_issues="Small crease on page 3", **{f"q_{books['Author'].id}": "R. K. Narayan", f"q_{books['Format'].id}": "Hardcover",
                                                              f"q_{books['Year published'].id}": "1958"})
    assert (p.condition, p.pickup_location, p.whats_included, p.known_issues) == ("like_new", "Pune, Maharashtra", "Dust jacket and a bookmark", "Small crease on page 3")
    got = {a.label: a.value for a in p.answers}
    assert got["Author"] == "R. K. Narayan" and got["Format"] == "Hardcover" and got["Year published"] == "1958"
    assert [a.position for a in p.answers] == sorted(a.position for a in p.answers)
    page = c.get(f"/seller/products/{p.id}").data.decode()
    for text in ("Condition", "Like new", "Author", "R. K. Narayan", "Item location", "Pune, Maharashtra", "Dust jacket and a bookmark", "Small crease on page 3"):
        assert text in page


def test_optional_extras_are_stored_as_null_when_left_blank(app, users, cats):  # noqa: F811
    p = make_listing(client_for(app, "seller@t.test"), cats["Sports"], whats_included="  ", known_issues="")
    assert p.whats_included is None and p.known_issues is None


def test_missing_required_answers_stop_the_listing_and_keep_what_was_typed(app, users, cats):  # noqa: F811
    c = client_for(app, "seller@t.test")
    sports = by_label("Sports")
    data = form_data(cats["Sports"], title="Cricket bat")
    del data[f"q_{sports['Which sport is it for?'].id}"]
    data[f"q_{sports['Brand'].id}"] = "Kookaburra"
    r = c.post("/seller/products/new", data=data, content_type="multipart/form-data")
    html = r.data.decode()
    assert r.status_code == 200 and Product.query.count() == 0
    assert "Please answer this question." in html and "still need an answer" in html
    assert 'value="Kookaburra"' in html and 'value="Cricket bat"' in html  # nothing the seller typed is lost
    assert audit(html).problems == []


def test_answers_to_another_categorys_questions_are_ignored(app, users, cats):  # noqa: F811
    c = client_for(app, "seller@t.test")
    foreign = {f"q_{q.id}": "Should not be stored" for q in questions("Electronics")}
    p = make_listing(c, cats["Books"], **foreign)
    assert all(a.value != "Should not be stored" for a in p.answers)
    assert {a.label for a in p.answers} <= {q.label for q in questions("Books")}


@pytest.mark.parametrize("over,message", [
    ({"condition": ""}, "Choose the item"), ({"condition": "mint"}, "valid choice"), ({"pickup_location": ""}, "required"),
    ({"pickup_location": "x" * 121}, "cannot be longer"), ({"description": "Too short to help anyone."}, "at least 30 characters"),
    ({"whats_included": "x" * 501}, "cannot be longer"), ({"known_issues": "x" * 1001}, "cannot be longer"),
])
def test_the_new_common_fields_are_validated(app, users, cats, over, message):  # noqa: F811
    r = post_new(client_for(app, "seller@t.test"), cats["Books"], **over)
    assert r.status_code == 200 and message.encode() in r.data and Product.query.count() == 0


def test_the_form_page_offers_every_categorys_set_and_stays_accessible(app, users, cats):  # noqa: F811
    html = client_for(app, "seller@t.test").get("/seller/products/new").data.decode()
    ids = re.findall(r'data-category-set="(\d+)"', html)
    assert sorted(ids) == sorted(str(c.id) for c in Category.query.all())
    assert "js/product-form.js" in html and 'name="condition"' in html and 'name="pickup_location"' in html
    assert "Detailed description" in html and "At least 30 characters" in html
    assert audit(html).problems == []


def test_the_browser_script_shows_only_the_chosen_categorys_questions():
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "product-form.js").read_text(encoding="utf-8")
    assert "data-category-set" in js and "disabled" in js and "hidden" in js and "innerHTML" not in js


# ---- editing -----------------------------------------------------------------------------------------------------------------
def test_the_edit_form_is_prefilled_and_changing_category_replaces_the_answers(app, users, cats):  # noqa: F811
    c = client_for(app, "seller@t.test")
    books = by_label("Books")
    p = make_listing(c, cats["Books"], **{f"q_{books['Author'].id}": "Anita Desai"})
    html = c.get(f"/seller/products/{p.id}/edit").data.decode()
    assert 'value="Anita Desai"' in html and 'value="Pune"' in html and 'value="Good, lightly used"' not in html
    assert re.search(r'<option selected value="good">', html)
    # move it to Sports: the Books answers go, the Sports ones come in
    sports = by_label("Sports")
    data = form_data(cats["Sports"], title="Now a bat", **{f"q_{sports['Brand'].id}": "SG"})
    r = c.post(f"/seller/products/{p.id}/edit", data=data, content_type="multipart/form-data")
    assert r.status_code == 302
    db.session.expire_all()
    labels = {a.label: a.value for a in db.session.get(Product, p.id).answers}
    assert "Author" not in labels and labels["Brand"] == "SG"


def test_editing_keeps_the_same_answers_when_nothing_changes(app, users, cats):  # noqa: F811
    c = client_for(app, "seller@t.test")
    books = by_label("Books")
    p = make_listing(c, cats["Books"], **{f"q_{books['Author'].id}": "Anita Desai"})
    before = {a.label: a.value for a in p.answers}
    data = form_data(cats["Books"], **{f"q_{books['Author'].id}": "Anita Desai"})
    c.post(f"/seller/products/{p.id}/edit", data=data, content_type="multipart/form-data")
    db.session.expire_all()
    assert {a.label: a.value for a in db.session.get(Product, p.id).answers} == before


# ---- what buyers see ------------------------------------------------------------------------------------------------------------
def test_buyers_see_the_details_and_how_the_blockchain_is_used(app, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "Lamp", 100)
    p = a.product
    p.condition, p.pickup_location, p.whats_included, p.known_issues = "fair", "Chennai", "Charger", "Scratch on the back"
    p.answers.append(ProductAnswer(label="Author", value="Someone", position=1))
    db.session.commit()
    html = client_for(app, "buyer@t.test").get(f"/auctions/{a.id}").data.decode()
    for text in ("Item details", "Fair, visible wear", "Author", "Someone", "Item location", "Chennai", "Charger", "Known issues", "Scratch on the back"):
        assert text in html
    assert "The item itself is not on the blockchain" in html and "one thing: the payment" in html and "never holds funds" in html
    assert audit(html).problems == []


def test_old_listings_without_the_new_fields_still_display(app, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "Old listing", 100)
    assert a.product.condition is None
    html = anon(app).get(f"/auctions/{a.id}").data.decode()
    assert "Old listing" in html and "Item details" not in html


def test_answers_are_escaped_everywhere_they_are_shown(app, users, cats):  # noqa: F811
    c = client_for(app, "seller@t.test")
    books = by_label("Books")
    evil = "<script>alert(1)</script>"
    p = make_listing(c, cats["Books"], whats_included=evil, known_issues=evil, pickup_location=evil, **{f"q_{books['Author'].id}": evil})
    for path in (f"/seller/products/{p.id}", f"/seller/products/{p.id}/edit"):
        g.pop("_login_user", None)
        html = client_for(app, "seller@t.test").get(path).data.decode()
        assert evil not in html and "&lt;script&gt;" in html


# ---- administrators manage each category's questions ------------------------------------------------------------------------------------
def test_an_admin_sees_a_categorys_questions_and_can_add_and_remove_them(app, users, cats):  # noqa: F811
    admin = client_for(app, "admin@t.test")
    cat = Category.query.filter_by(name="Books").one()
    page = admin.get(f"/admin/categories/{cat.id}/questions").data.decode()
    assert "Author" in page and "Format" in page and audit(page).problems == []
    n = len(cat.questions)
    r = admin.post(f"/admin/categories/{cat.id}/questions", data={"label": "Number of pages", "kind": "number", "required": "y", "help": "Roughly is fine"})
    assert r.status_code == 302
    db.session.expire_all()
    added = CategoryQuestion.query.filter_by(category_id=cat.id, label="Number of pages").one()
    assert (added.kind, added.required, added.help, added.key) == ("number", True, "Roughly is fine", "number_of_pages")
    assert added.position > max(q.position for q in cat.questions if q.id != added.id)
    assert len(Category.query.get(cat.id).questions) == n + 1
    # a seller now gets asked it
    html = client_for(app, "seller@t.test").get("/seller/products/new").data.decode()
    assert "Number of pages" in html


@pytest.mark.parametrize("data,message", [
    ({"label": "ab", "kind": "text"}, "between"), ({"label": "Cover type", "kind": "choice", "choices": "Only one"}, "at least two options"),
    ({"label": "Cover type", "kind": "choice", "choices": "A\nA"}, "different options"), ({"label": "Cover type", "kind": "banana"}, "valid choice"),
    ({"label": "Cover type", "kind": "choice", "choices": "\n".join(f"opt{i}" for i in range(13))}, "up to 12"),
])
def test_bad_questions_are_refused(app, users, cats, data, message):  # noqa: F811
    cat = Category.query.filter_by(name="Books").one()
    before = len(qs.questions_for(cat.id))
    r = client_for(app, "admin@t.test").post(f"/admin/categories/{cat.id}/questions", data=data)
    assert r.status_code == 200 and message.encode() in r.data
    assert len(qs.questions_for(cat.id)) == before


def test_removing_a_question_leaves_existing_listings_untouched(app, users, cats):  # noqa: F811
    c = client_for(app, "seller@t.test")
    books = by_label("Books")
    p = make_listing(c, cats["Books"], **{f"q_{books['Author'].id}": "Anita Desai"})
    cat = Category.query.filter_by(name="Books").one()
    r = client_for(app, "admin@t.test").post(f"/admin/categories/{cat.id}/questions/{books['Author'].id}/delete")
    assert r.status_code == 302
    db.session.expire_all()
    assert db.session.get(CategoryQuestion, books["Author"].id) is None
    answer = [a for a in db.session.get(Product, p.id).answers if a.label == "Author"][0]
    assert answer.value == "Anita Desai" and answer.question_id is None  # the listing keeps its own copy of the wording
    assert "Anita Desai" in client_for(app, "seller@t.test").get(f"/seller/products/{p.id}").data.decode()


def test_question_admin_routes_are_admin_only_and_not_guessable(app, users, cats):  # noqa: F811
    cat = Category.query.filter_by(name="Books").one()
    qid = questions("Books")[0].id
    for who in ("buyer@t.test", "seller@t.test"):
        c = client_for(app, who)
        assert c.get(f"/admin/categories/{cat.id}/questions").status_code in (302, 403)
        assert c.post(f"/admin/categories/{cat.id}/questions/{qid}/delete").status_code in (302, 403)
    assert anon(app).get(f"/admin/categories/{cat.id}/questions").status_code == 302
    admin = client_for(app, "admin@t.test")
    other = Category.query.filter_by(name="Sports").one()
    assert admin.post(f"/admin/categories/{other.id}/questions/{qid}/delete").status_code == 404  # a question of another category
    assert admin.get("/admin/categories/9999/questions").status_code == 404
    assert CategoryQuestion.query.get(qid) is not None


def test_a_new_category_starts_with_the_generic_questions_and_can_be_deleted_with_them(app, users):
    admin = client_for(app, "admin@t.test")
    admin.post("/admin/categories", data={"name": "Musical Instruments"})
    cat = Category.query.filter_by(name="Musical Instruments").one()
    assert [q.label for q in cat.questions] == [s["label"] for s in qs.GENERIC]
    assert admin.post(f"/admin/categories/{cat.id}/delete").status_code == 302
    db.session.expire_all()
    assert Category.query.filter_by(name="Musical Instruments").first() is None
    assert CategoryQuestion.query.filter_by(category_id=cat.id).count() == 0


def test_the_categories_page_links_to_each_categorys_questions(app, users, cats):  # noqa: F811
    html = client_for(app, "admin@t.test").get("/admin/categories").data.decode()
    assert html.count("/questions") >= len(Category.query.all())
    assert audit(html).problems == []
