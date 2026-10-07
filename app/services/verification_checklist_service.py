"""The admin checklist is what makes a platform verification a structured review rather than a button.

A card can only be approved when every required check is recorded as "verified" (and, for a graded card, the grading
certificate check too). The server enforces this: the page only explains it.
"""
from ..models import CardVerificationChecklist

# check_type -> label shown to the admin, in the order they appear on the review page
REQUIRED = {
    "card_identity": "Card identity",
    "set_checked": "Set / collection",
    "card_number": "Card number",
    "manufacturer": "Manufacturer",
    "images_reviewed": "Images",
    "condition_reviewed": "Condition",
    "seller_info_reviewed": "Seller information",
    "counterfeit_check": "Counterfeit risk",
}
GRADING = ("grading_checked", "Grading certificate")
RESULT_WORDS = {"needs_review": "needs review", "failed": "failed"}


def _required_for(card):
    checks = dict(REQUIRED)
    if card.is_graded:
        checks[GRADING[0]] = GRADING[1]
    return checks


def blockers(verification):
    """Plain-language reasons the card cannot be approved yet; an empty list means it can."""
    rows = {row.check_type: row for row in CardVerificationChecklist.query.filter_by(verification_id=verification.id)}
    if not rows:
        return ["The verification checklist has not been completed."]
    reasons = []
    for check_type, label in _required_for(verification.collectible_card).items():
        row = rows.get(check_type)
        if row is None:
            reasons.append(f"{label}: not checked.")
        elif row.result != "verified":
            reasons.append(f"{label}: {RESULT_WORDS.get(row.result, row.result or 'not checked')}.")
    return reasons


def clear(verification):
    """Forget the recorded checks, e.g. when the seller changes the card so they no longer describe what is on the page."""
    CardVerificationChecklist.query.filter_by(verification_id=verification.id).delete()
