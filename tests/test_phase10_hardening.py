"""Phase 10: closing the gaps Phase 9 found.

  Approval needs a complete checklist ....... approval_*      (a verification is a review, not a button)
  Reject for good (no resubmission) ......... resubmission_*  (the reject form's choice is now stored and enforced)
  No inline scripts, no unused CDN assets ... csp_*, shop_*, card_page_*, card_form_*
  The seller's estimate is labelled as such . estimate_*
  Schema change has a migration ............. migration_*
"""
import importlib.util
import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.extensions import db
from app.models import CardVerificationChecklist, CardVerificationHistory, CollectibleCard
from app.services import card_status_service as status
from app.services import verification_checklist_service as checklist

from .test_listing_validation import CHECKS, cat, card_type, complete_checklist, seller  # noqa: F401 (fixtures)
from .test_phase1_card_identity import card_form, static_dir  # noqa: F401 (fixture)
from .test_phase9_scenarios import submitted_card, switch

ROOT = Path(__file__).resolve().parent.parent
LABELS = checklist.REQUIRED


def new_card(client, card_type, **over):
    card = submitted_card(client, card_type, **over)
    return card, card.product.collectible_verification.id


def decide(client, vid, action, **data):
    switch(client, "admin@t.test")
    return client.post(f"/admin/cards/verify/{vid}/{action}", data=data, follow_redirects=True)


def state(card):
    db.session.expire_all()
    return card.product.collectible_verification.verification_status


# =================================== approval needs a complete checklist =====================================================
def test_approval_is_refused_until_a_checklist_is_saved(client, users, cat, card_type, static_dir):
    card, vid = new_card(client, card_type)
    page = decide(client, vid, "approve", approval_notes="Looks fine")
    assert "checklist has not been completed" in page.get_data(as_text=True)
    assert state(card) == "pending" and card.blockchain_asset is None and CardVerificationHistory.query.count() == 0
    assert card.product.approval_status == "pending"


@pytest.mark.parametrize("result", ["needs_review", "failed"])
@pytest.mark.parametrize("check", sorted(LABELS))
def test_approval_needs_every_check_to_pass(client, users, cat, card_type, static_dir, check, result):
    card, vid = new_card(client, card_type)
    switch(client, "admin@t.test")
    complete_checklist(client, vid, **{check: result})
    page = decide(client, vid, "approve").get_data(as_text=True)
    assert f"{LABELS[check]}: {checklist.RESULT_WORDS[result]}." in page
    assert state(card) == "under_review" and card.product.approval_status == "pending"
    complete_checklist(client, vid)  # the admin corrects the review
    decide(client, vid, "approve")
    assert state(card) == "verified" and card.product.approval_status == "approved"


def test_a_graded_card_also_needs_its_grading_certificate_checked(client, users, cat, card_type, static_dir):
    card, vid = new_card(client, card_type, is_graded="y", grading_company="PSA", grade="PSA 9", certification_number="12345678")
    switch(client, "admin@t.test")
    complete_checklist(client, vid, grading_checked="")
    assert "Grading certificate: not checked." in decide(client, vid, "approve").get_data(as_text=True)
    assert state(card) == "under_review"
    complete_checklist(client, vid, grading_checked="failed")
    assert "Grading certificate: failed." in decide(client, vid, "approve").get_data(as_text=True)
    complete_checklist(client, vid, grading_checked="verified")
    decide(client, vid, "approve")
    assert state(card) == "verified"


def test_the_review_page_explains_what_blocks_approval_and_unlocks_when_complete(client, users, cat, card_type, static_dir):
    card, vid = new_card(client, card_type)
    switch(client, "admin@t.test")
    page = client.get(f"/admin/cards/verify/{vid}").get_data(as_text=True)
    assert 'id="approval-blockers"' in page and "checklist has not been completed" in page
    assert re.search(r"<button[^>]*btn-success[^>]*\sdisabled", page)
    complete_checklist(client, vid)
    page = client.get(f"/admin/cards/verify/{vid}").get_data(as_text=True)
    assert 'id="approval-blockers"' not in page and not re.search(r"<button[^>]*btn-success[^>]*\sdisabled", page)
    decide(client, vid, "approve")
    page = client.get(f"/admin/cards/verify/{vid}").get_data(as_text=True)  # decided: nothing left to approve
    assert 'id="approval-blockers"' not in page and re.search(r"<button[^>]*btn-success[^>]*\sdisabled", page)


def test_approving_twice_changes_nothing_the_second_time(client, users, cat, card_type, static_dir):
    card, vid = new_card(client, card_type)
    switch(client, "admin@t.test")
    complete_checklist(client, vid)
    decide(client, vid, "approve")
    rows = CardVerificationHistory.query.count()
    assert "already platform verified" in decide(client, vid, "approve").get_data(as_text=True)
    assert CardVerificationHistory.query.count() == rows == 1 and state(card) == "verified"


@pytest.mark.parametrize("decision", ["verified", "rejected"])
def test_a_decided_cards_checklist_cannot_be_rewritten_to_reopen_it(client, users, cat, card_type, static_dir, decision):
    card, vid = new_card(client, card_type)
    switch(client, "admin@t.test")
    complete_checklist(client, vid)
    if decision == "verified":
        decide(client, vid, "approve")
    else:
        decide(client, vid, "reject", rejection_reason="Other reason", rejection_details="Not acceptable to the platform.")
    before = sorted((c.check_type, c.result) for c in CardVerificationChecklist.query.all())
    page = complete_checklist(client, vid, counterfeit_check="failed")
    assert page.status_code == 302
    assert "already been decided" in client.get(page.headers["Location"]).get_data(as_text=True)
    assert state(card) == decision and sorted((c.check_type, c.result) for c in CardVerificationChecklist.query.all()) == before


def test_editing_a_card_throws_away_the_checks_made_on_the_old_details(client, users, cat, card_type, static_dir):
    card, vid = new_card(client, card_type)
    switch(client, "admin@t.test")
    complete_checklist(client, vid)
    decide(client, vid, "more-info", info_request="Clarify condition", message="Please clarify the condition.")
    switch(client, "seller@t.test")
    r = client.post(f"/seller/cards/{card.id}/edit", content_type="multipart/form-data", data=card_form(card_type, card_name="Charizard v2"))
    assert r.status_code == 302 and state(card) == "pending"
    assert CardVerificationChecklist.query.count() == 0
    entry = CardVerificationHistory.query.order_by(CardVerificationHistory.id.desc()).first()
    assert (entry.previous_status, entry.new_status, entry.changed_by) == ("more_info_needed", "pending", users["seller"].id)
    assert "Seller edited the card" in entry.change_reason
    assert "checklist has not been completed" in decide(client, vid, "approve").get_data(as_text=True)
    assert state(card) == "pending"


# =================================== a rejection can be final =================================================================
REJECT = {"rejection_reason": "Suspected counterfeit", "rejection_details": "The print quality does not match the set."}


def edit_attempt(client, card, card_type, **over):
    return client.post(f"/seller/cards/{card.id}/edit", content_type="multipart/form-data", data=card_form(card_type, **over))


def test_resubmission_a_final_rejection_cannot_be_edited_or_resubmitted(client, users, cat, card_type, static_dir):
    card, vid = new_card(client, card_type)
    decide(client, vid, "reject", **REJECT)  # the box "allow resubmission" is not ticked
    db.session.expire_all()
    v = card.product.collectible_verification
    assert v.verification_status == "rejected" and v.resubmission_allowed is False
    assert status.edit_blocker(card) == "This card was rejected and the reviewer did not allow it to be resubmitted."
    switch(client, "seller@t.test")
    for attempt in (client.get(f"/seller/cards/{card.id}/edit"), edit_attempt(client, card, card_type, card_name="Charizard fixed")):
        assert attempt.status_code == 302 and attempt.headers["Location"].endswith(f"/seller/cards/{card.id}")
    detail = client.get(f"/seller/cards/{card.id}").get_data(as_text=True)
    assert "did not allow this card to be resubmitted" in detail and f"/seller/cards/{card.id}/edit" not in detail
    assert f"/seller/cards/{card.id}/edit" not in client.get("/seller/collectibles").get_data(as_text=True)
    db.session.expire_all()
    assert card.card_name == "Charizard" and state(card) == "rejected" and card.product.approval_status == "rejected"


def test_resubmission_an_open_rejection_can_be_corrected_and_sent_again(client, users, cat, card_type, static_dir):
    card, vid = new_card(client, card_type)
    decide(client, vid, "reject", allow_resubmit="y", **REJECT)
    db.session.expire_all()
    assert card.product.collectible_verification.resubmission_allowed is True and status.edit_blocker(card) is None
    switch(client, "seller@t.test")
    detail = client.get(f"/seller/cards/{card.id}").get_data(as_text=True)
    assert "send it for verification again" in detail and f"/seller/cards/{card.id}/edit" in detail
    assert f"/seller/cards/{card.id}/edit" in client.get("/seller/collectibles").get_data(as_text=True)
    assert edit_attempt(client, card, card_type, card_name="Charizard fixed").status_code == 302
    db.session.expire_all()
    assert (card.card_name, state(card), card.product.collectible_verification.submission_count) == ("Charizard fixed", "pending", 2)


def test_resubmission_new_cards_default_to_allowed(client, users, cat, card_type, static_dir):
    card, _ = new_card(client, card_type)
    assert card.product.collectible_verification.resubmission_allowed is True and status.edit_blocker(card) is None


def test_the_edit_rule_follows_the_state_of_the_card(client, users, cat, card_type, static_dir):
    card, vid = new_card(client, card_type)
    assert status.edit_blocker(card) is None  # waiting for review
    switch(client, "admin@t.test")
    complete_checklist(client, vid)
    assert status.edit_blocker(card) is None  # under review
    decide(client, vid, "approve")
    db.session.expire_all()
    assert status.edit_blocker(card) == "You cannot edit a verified card listing."


# =================================== no inline scripts, no unused third-party assets ==========================================
def test_csp_no_unused_third_party_assets_are_loaded(client):
    page = client.get("/")
    html = page.get_data(as_text=True)
    assert "lucide" not in html.lower() and "fonts.googleapis.com" not in html
    csp = page.headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in dict(d.strip().split(" ", 1) for d in csp.split(";"))["script-src"] and "googleapis" not in csp
    assert "window.fetch" not in client.get("/static/js/modern-effects.js").get_data(as_text=True)


def test_shop_filters_work_from_data_attributes_and_point_at_the_real_page(client, users, cat, card_type):
    html = client.get("/shop").get_data(as_text=True)
    assert 'data-shop-url="/shop"' in html and "/browse?" not in html and "onchange" not in html
    for name in ("category", "card_type", "sort"):
        assert f'data-shop-filter="{name}"' in html
    assert "js/shop-filters.js" in html
    script = client.get("/static/js/shop-filters.js").get_data(as_text=True)
    assert "data-shop-filter" in script and "shopUrl" in script
    assert client.get("/shop?category=cards&card_type=pokemon&sort=price_low").status_code == 200


def test_card_page_thumbnails_switch_the_main_image_without_inline_code(client, users, cat, card_type, static_dir):
    card, _ = new_card(client, card_type)
    card.product.approval_status = "approved"
    db.session.commit()
    client.post("/auth/logout")
    html = client.get(f"/cards/{card.id}").get_data(as_text=True)
    assert 'id="gallery-main"' in html and 'id="gallery-thumbs"' in html and "onclick" not in html
    assert len(re.findall(r"<button[^>]*data-gallery-src=", html)) == len(card.images) >= 2
    assert "js/card-gallery.js" in html
    assert "data-autosubmit" in client.get("/cards/search?q=Char").get_data(as_text=True)


def test_card_form_still_reveals_its_grading_and_type_sections_from_a_file(client, users, cat, card_type):
    switch(client, "seller@t.test")
    html = client.get("/seller/cards/new").get_data(as_text=True)
    assert "js/card-form-toggles.js" in html and not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    for element in ("is_graded", "card_type_id", "grading-fields", "cert-fields", "pokemon-fields", "football-fields"):
        assert f'id="{element}"' in html, element  # the file looks these up by id
    js = client.get("/static/js/card-form-toggles.js").get_data(as_text=True)
    assert all(f'"{element}"' in js for element in ("is_graded", "card_type_id", "grading-fields", "pokemon-fields", "football-fields"))


# =================================== the estimate is the seller, and says so ==================================================
def test_estimate_the_form_and_the_public_pages_agree_it_is_public_and_the_sellers(client, users, cat, card_type, static_dir):
    card, _ = new_card(client, card_type, estimated_value="1500")
    card.product.approval_status = "approved"
    db.session.commit()
    switch(client, "seller@t.test")
    form = client.get("/seller/cards/new").get_data(as_text=True)
    assert "not public" not in form and "Shown publicly as your own estimate" in form
    client.post("/auth/logout")
    for path in ("/shop", "/cards/browse", f"/cards/{card.id}", "/cards/search?q=Char"):
        html = client.get(path).get_data(as_text=True)
        assert "Seller\x27s estimate" in html and "Est. Value" not in html and "Estimated Value" not in html, path


# =================================== the schema change has a migration ========================================================
MIGRATION = ROOT / "migrations" / "versions" / "g17resubmission01_resubmission_allowed.py"


def test_migration_there_is_exactly_one_head_and_it_includes_this_one():
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    (head,) = script.get_heads()
    assert "g17resubmission01" in {rev.revision for rev in script.iterate_revisions(head, "base")}


def test_migration_adds_the_column_as_true_for_existing_rows_and_removes_it_again():
    spec = importlib.util.spec_from_file_location("g17", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE collectible_verifications (id INTEGER PRIMARY KEY, verification_status VARCHAR(50))"))
        conn.execute(sa.text("INSERT INTO collectible_verifications (verification_status) VALUES ('rejected')"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        assert conn.execute(sa.text("SELECT resubmission_allowed FROM collectible_verifications")).scalar() in (1, True)
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        assert "resubmission_allowed" not in [c["name"] for c in sa.inspect(conn).get_columns("collectible_verifications")]
