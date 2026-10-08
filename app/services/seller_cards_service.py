"""The seller's card inventory: one row per card, grouped by lifecycle, with the facts a seller acts on."""
from ..models import CollectibleCard, Product
from . import card_status_service as status

GROUPS = (
    ("all", "All cards", None),
    ("awaiting", "Awaiting verification", {"SUBMITTED_FOR_VERIFICATION", "UNDER_ADMIN_REVIEW"}),
    ("more_info", "More information required", {"MORE_INFORMATION_REQUIRED"}),
    ("verified", "Verified", {"VERIFIED", "BLOCKCHAIN_REGISTERED", "APPROVED_FOR_AUCTION"}),
    ("rejected", "Rejected", {"REJECTED"}),
    ("auction", "Active auctions", {"ACTIVE_AUCTION"}),
    ("completed", "Completed auctions", {"AUCTION_ENDED", "PAYMENT_PENDING"}),
    ("sold", "Sold", {"SOLD", "TRANSFERRED"}),
)
GROUP_KEYS = {key for key, _, _ in GROUPS}
LEGACY_GROUPS = {"pending": "awaiting"}  # links from the earlier dashboard
SORTS = {"newest": "Newest", "oldest": "Oldest", "name": "Name"}
EDITABLE = {"SUBMITTED_FOR_VERIFICATION", "UNDER_ADMIN_REVIEW", "MORE_INFORMATION_REQUIRED", "REJECTED"}
LISTABLE = {"VERIFIED", "BLOCKCHAIN_REGISTERED", "APPROVED_FOR_AUCTION"}
BADGES = {  # lifecycle code -> Bootstrap colour
    "SUBMITTED_FOR_VERIFICATION": "warning", "UNDER_ADMIN_REVIEW": "info", "MORE_INFORMATION_REQUIRED": "warning",
    "REJECTED": "danger", "VERIFIED": "success", "BLOCKCHAIN_REGISTERED": "success", "APPROVED_FOR_AUCTION": "success",
    "ACTIVE_AUCTION": "info", "AUCTION_ENDED": "secondary", "PAYMENT_PENDING": "warning", "SOLD": "success",
    "TRANSFERRED": "success",
}


def blockchain_label(asset):
    if asset is None:
        return "Not registered"
    if asset.status == "transferred":
        return f"Token #{asset.token_id} transferred"
    if asset.status == "minted":
        return f"Token #{asset.token_id}"
    return "Minting" if asset.status == "minting" else "Awaiting minting"


def _row(card):
    product = card.product
    lifecycle = status.lifecycle(card)
    auction = product.auction
    payment = auction.payment if auction is not None else None
    verification = product.collectible_verification
    return {
        "card": card, "product": product, "lifecycle": lifecycle, "badge": BADGES[lifecycle["code"]],
        "verification": (verification.verification_status if verification else "pending").replace("_", " "),
        "blockchain": blockchain_label(card.blockchain_asset), "auction": auction,
        "bids": len(auction.bids) if auction is not None else 0,
        "can_edit": lifecycle["code"] in EDITABLE and auction is None and status.edit_blocker(card) is None,
        "can_list": lifecycle["code"] in LISTABLE and auction is None,
        "can_authorize": lifecycle["code"] == "PAYMENT_PENDING" and payment is not None and payment.awaiting_payment,
    }


def seller_cards(user, group="all", sort="newest"):
    """{rows, tabs: [(key, label, count)], group, sort} for one seller."""
    group = LEGACY_GROUPS.get(group, group)
    group = group if group in GROUP_KEYS else "all"
    sort = sort if sort in SORTS else "newest"
    cards = (CollectibleCard.query.join(Product).filter(Product.seller_id == user.id)
             .order_by(CollectibleCard.created_at.desc(), CollectibleCard.id.desc()).all())
    rows = [_row(c) for c in cards]
    tabs = [(key, label, len(rows) if codes is None else sum(1 for r in rows if r["lifecycle"]["code"] in codes))
            for key, label, codes in GROUPS]
    wanted = next(codes for key, _, codes in GROUPS if key == group)
    shown = rows if wanted is None else [r for r in rows if r["lifecycle"]["code"] in wanted]
    if sort == "oldest":
        shown = list(reversed(shown))
    elif sort == "name":
        shown = sorted(shown, key=lambda r: r["card"].card_name.lower())
    return {"rows": shown, "tabs": tabs, "group": group, "sort": sort}
