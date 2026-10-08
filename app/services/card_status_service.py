"""The lifecycle state of a card, derived from the records that already exist (so it can never drift out of sync).

SUBMITTED_FOR_VERIFICATION -> UNDER_ADMIN_REVIEW -> (MORE_INFORMATION_REQUIRED | REJECTED) -> VERIFIED
-> BLOCKCHAIN_REGISTERED (token minted) -> APPROVED_FOR_AUCTION -> ACTIVE_AUCTION -> AUCTION_ENDED
-> PAYMENT_PENDING -> SOLD (paid) -> TRANSFERRED (the token has moved to the buyer and MySQL agrees).
"""

LABELS = {
    "SUBMITTED_FOR_VERIFICATION": "Submitted for verification",
    "UNDER_ADMIN_REVIEW": "Under admin review",
    "MORE_INFORMATION_REQUIRED": "More information required",
    "REJECTED": "Rejected",
    "VERIFIED": "Platform verified",
    "BLOCKCHAIN_REGISTERED": "Blockchain registered",
    "APPROVED_FOR_AUCTION": "Approved for auction",
    "ACTIVE_AUCTION": "In an auction",
    "AUCTION_ENDED": "Auction ended",
    "PAYMENT_PENDING": "Payment pending",
    "SOLD": "Sold",
    "TRANSFERRED": "Ownership transferred",
}

_BEFORE_VERIFICATION = {
    "pending": "SUBMITTED_FOR_VERIFICATION", "submitted": "SUBMITTED_FOR_VERIFICATION",
    "under_review": "UNDER_ADMIN_REVIEW", "more_info_needed": "MORE_INFORMATION_REQUIRED", "rejected": "REJECTED",
}


def lifecycle_code(card):
    product = card.product
    verification = product.collectible_verification
    status = verification.verification_status if verification else "pending"
    if status != "verified":
        return _BEFORE_VERIFICATION.get(status, "SUBMITTED_FOR_VERIFICATION")

    asset = card.blockchain_asset
    if asset is not None and asset.status == "transferred":
        return "TRANSFERRED"
    auction = product.auction
    if auction is not None:
        if auction.status in ("scheduled", "active"):
            return "ACTIVE_AUCTION"
        payment = auction.payment if auction.status == "closed" else None
        if payment is None:
            return "AUCTION_ENDED"  # no bids, or cancelled
        return "SOLD" if payment.payment_status == "successful" else "PAYMENT_PENDING"
    if asset is not None and asset.status == "minted":
        return "APPROVED_FOR_AUCTION" if product.approval_status == "approved" else "BLOCKCHAIN_REGISTERED"
    return "VERIFIED"


def lifecycle(card):
    code = lifecycle_code(card)
    return {"code": code, "label": LABELS[code]}


def edit_blocker(card):
    """Why the seller cannot edit this card right now, or None when they can.

    One rule for the edit route and for every page that offers the Edit button, so they cannot disagree.
    """
    product = card.product
    verification = product.collectible_verification
    status = verification.verification_status if verification else "pending"
    if status == "verified":
        return "You cannot edit a verified card listing."
    if product.auction is not None and product.auction.status in ("active", "closed"):
        return "You cannot edit a card once the auction has started."
    if status == "rejected" and verification is not None and not verification.resubmission_allowed:
        return "This card was rejected and the reviewer did not allow it to be resubmitted."
    return None
