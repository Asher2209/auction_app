"""Per-category questions for a listing, and the answers sellers give.

Every category has its own main set of questions (stored in `category_questions`, editable by an administrator).
A category that has none yet gets a default set the first time it is needed: the six starter categories get tailored sets,
any other category gets a short generic one. A product keeps its answers together with a copy of each question's wording,
so editing or deleting a question later never rewrites an old listing.
"""
import re
from decimal import Decimal, InvalidOperation

from ..extensions import db
from ..models import Category, CategoryQuestion, ProductAnswer

KINDS = ("text", "longtext", "number", "choice", "yesno")
KIND_LABELS = {"text": "Short text", "longtext": "Long text", "number": "Number", "choice": "Pick one", "yesno": "Yes / No"}
LIMITS = {"text": 200, "longtext": 1000, "number": 30, "choice": 200, "yesno": 3}


def Q(label, kind="text", required=False, choices=None, help=""):  # noqa: A002
    return {"label": label, "kind": kind, "required": required, "choices": choices or [], "help": help}


YEARS = "e.g. 2019"
DEFAULTS = {
    "Books": [
        Q("Author", required=True), Q("Publisher"), Q("Year published", "number", help=YEARS),
        Q("Edition", help="e.g. first edition, 3rd revised"), Q("ISBN", help="10 or 13 digits, if it has one"),
        Q("Format", "choice", True, ["Hardcover", "Paperback", "Other"]), Q("Language", required=True),
        Q("Signed by the author?", "yesno"), Q("Highlighting or writing inside?", "yesno", True),
    ],
    "Collectibles": [
        Q("What kind of item is it?", required=True, help="e.g. coin, stamp, figurine, comic"),
        Q("Maker or brand"), Q("Year or era", required=True, help="e.g. 1950s, or 1987"), Q("Country or place of origin"),
        Q("Certificate or proof of authenticity?", "yesno", True), Q("Edition or rarity", help="e.g. limited, 120 of 500"),
        Q("Size and weight", help="e.g. 12 cm tall, 340 g"), Q("Any restoration or repair?", "yesno", True),
    ],
    "Electronics": [
        Q("Brand", required=True), Q("Model", required=True), Q("Year of purchase", "number", help=YEARS),
        Q("Warranty left", "choice", True, ["None", "Under 6 months", "6 to 12 months", "Over 12 months"]),
        Q("Works fully?", "yesno", True), Q("Main specifications", "longtext", help="e.g. storage, memory, screen size, battery"),
        Q("Original box and charger included?", "yesno", True), Q("Ever repaired or opened?", "yesno", True),
    ],
    "Fashion": [
        Q("Brand", required=True), Q("Type of item", required=True, help="e.g. jacket, saree, sneakers"),
        Q("Size", required=True, help="Label size and, if you know it, measurements"), Q("Made for", "choice", True, ["Women", "Men", "Unisex", "Kids"]),
        Q("Colour", required=True), Q("Material"), Q("Times worn", "choice", True, ["Never", "A few times", "Often"]),
        Q("Original tags still attached?", "yesno"),
    ],
    "Home & Garden": [
        Q("What kind of item is it?", required=True), Q("Brand or maker"), Q("Material"),
        Q("Dimensions", required=True, help="Length x width x height"), Q("Colour"),
        Q("Assembly required?", "yesno", True), Q("Power source", "choice", False, ["Not powered", "Mains electric", "Battery", "Manual"]),
        Q("Age of the item", help="e.g. 2 years"),
    ],
    "Sports": [
        Q("Which sport is it for?", required=True), Q("Brand", required=True), Q("Size, weight or specification", required=True),
        Q("How long was it used?", "choice", True, ["Never used", "Under a year", "1 to 3 years", "Over 3 years"]),
        Q("Suitable for", "choice", True, ["Beginner", "Intermediate", "Professional"]), Q("Any damage or heavy wear?", "yesno", True),
    ],
}
GENERIC = [
    Q("What kind of item is it?", required=True), Q("Brand or maker"), Q("Age of the item", help="e.g. 2 years, or the year it was made"),
    Q("Size or dimensions"), Q("Anything a buyer should know about its history?", "longtext"),
]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "q"


def unique_key(category, label):
    taken = {q.key for q in category.questions}
    base = slug(label)
    key, n = base, 2
    while key in taken:
        key, n = f"{base[:36]}_{n}", n + 1
    return key


def make_question(category, spec, position):
    return CategoryQuestion(category_id=category.id, key=unique_key(category, spec["label"]), label=spec["label"], kind=spec["kind"],
                            choices="\n".join(spec["choices"]) if spec["choices"] else None, required=bool(spec["required"]),
                            help=spec["help"] or None, position=position)


def ensure_default_questions(category):
    """Give a category its starter questions if it has none. Returns True if it added any."""
    if category.questions:
        return False
    for position, spec in enumerate(DEFAULTS.get(category.name, GENERIC), 1):
        category.questions.append(make_question(category, spec, position))
    return True


def ensure_all():
    changed = False
    for category in Category.query.all():
        changed |= ensure_default_questions(category)
    if changed:
        db.session.commit()


def question_sets():
    """{category_id: [CategoryQuestion, ...]} for every category (the product form shows the chosen category's set)."""
    ensure_all()
    return {c.id: list(c.questions) for c in Category.query.order_by(Category.name)}


def questions_for(category_id):
    category = db.session.get(Category, category_id) if category_id else None
    if category is None:
        return []
    if ensure_default_questions(category):
        db.session.commit()
    return list(category.questions)


def parse_answers(form, questions):
    """Read `q_<id>` fields for exactly these questions. Returns ({question_id: value}, {question_id: message}).
    Fields for any other question (another category's, or made up) are ignored."""
    answers, errors = {}, {}
    for q in questions:
        raw = (form.get(f"q_{q.id}") or "").strip()
        if not raw:
            if q.required:
                errors[q.id] = "Please answer this question."
            continue
        if len(raw) > LIMITS[q.kind]:
            errors[q.id] = f"Please keep this under {LIMITS[q.kind]} characters."
        elif q.kind == "number":
            try:
                value = Decimal(raw.replace(",", ""))
                if not value.is_finite() or abs(value) > Decimal("1e12"):
                    raise InvalidOperation
                answers[q.id] = format(value.normalize(), "f")
            except InvalidOperation:
                errors[q.id] = "Enter a number."
        elif q.kind == "choice":
            if raw in q.choice_list:
                answers[q.id] = raw
            else:
                errors[q.id] = "Pick one of the listed options."
        elif q.kind == "yesno":
            if raw.lower() in ("yes", "no"):
                answers[q.id] = raw.capitalize()
            else:
                errors[q.id] = "Answer Yes or No."
        else:
            answers[q.id] = raw
    return answers, errors


def store_answers(product, questions, answers):
    """Replace the product's answers with these (questions the seller left blank are simply not stored)."""
    product.answers = [ProductAnswer(question_id=q.id, label=q.label, value=answers[q.id], position=q.position)
                       for q in questions if q.id in answers]


def current_values(product):
    return {a.question_id: a.value for a in product.answers if a.question_id}
