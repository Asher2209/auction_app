"""Server-side gate that decides whether a collectible card may go to auction.

A card product may only be listed when all of these hold:
  VERIFIED                  the platform verified the card
  NO_BLOCKCHAIN_IDENTITY    the card has a registered blockchain identity (BlockchainAsset)
  DUPLICATE_ACTIVE_AUCTION  neither this card nor another record of the same physical card
                            (same grader + certification number) is in a scheduled/active auction
  ALREADY_SOLD / AUCTION_ALREADY_EXISTS  this card has not already been auctioned
  SELLER_WALLET_MISSING / SELLER_NOT_OWNER  the seller's wallet is the registered owner
  TOKEN_NOT_MINTED / OWNERSHIP_SYNC_ERROR / CHAIN_UNVERIFIABLE  on-chain state agrees with MySQL

Shared certification numbers with a card that is not in an active auction are only warnings
("potential duplicate"): the platform cannot prove from records alone that two entries are the same
physical card, so an admin decides. Products without a collectible card are not affected.
"""
from dataclasses import dataclass, field

from flask import current_app
from sqlalchemy import func

from ..extensions import db
from ..models import Auction, CollectibleCard, Winner
from . import blockchain_ownership_service as ownership

LIVE_STATUSES = ("scheduled", "active")


@dataclass(frozen=True)
class Issue:
    code: str
    message: str


@dataclass
class ListingCheck:
    violations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.violations

    def block(self, code, message):
        self.violations.append(Issue(code, message))

    def warn(self, code, message):
        self.warnings.append(Issue(code, message))

    def codes(self):
        return {i.code for i in self.violations}


class ListingBlocked(Exception):
    def __init__(self, check):
        super().__init__("; ".join(i.message for i in check.violations))
        self.check = check


def _norm(value):
    return (value or "").strip().upper()


def _same_certificate_cards(card):
    company, number = _norm(card.grading_company), _norm(card.certification_number)
    if not (company and number):
        return []
    return (CollectibleCard.query
            .filter(CollectibleCard.id != card.id,
                    func.upper(func.trim(CollectibleCard.grading_company)) == company,
                    func.upper(func.trim(CollectibleCard.certification_number)) == number)
            .all())


def find_duplicate_signals(card, check=None):
    """Cross-record duplicate detection by grader + certification number."""
    check = check or ListingCheck()
    for other in _same_certificate_cards(card):
        auction = other.product.auction
        label = f"{card.grading_company} certification {card.certification_number}"
        if auction is not None and auction.status in LIVE_STATUSES:
            check.block("DUPLICATE_ACTIVE_AUCTION",
                        f"The same physical card ({label}) is already in an active auction ({other.platform_card_id}).")
        else:
            check.warn("POTENTIAL_DUPLICATE",
                       f"{other.platform_card_id} is registered with the same {label}. Admin review required.")
    return check


def _check_own_auction(product, check):
    auction = product.auction
    if auction is None:
        return
    if auction.status in LIVE_STATUSES:
        check.block("DUPLICATE_ACTIVE_AUCTION", "This card is already in an active auction.")
    elif auction.status == "closed" and db.session.query(Winner.id).filter_by(auction_id=auction.id).first():
        check.block("ALREADY_SOLD", "This card has already been sold.")
    else:
        check.block("AUCTION_ALREADY_EXISTS", "This card already has an auction that cannot be reused.")


def check_listing(product):
    """Run every listing rule and return a ListingCheck with all violations and warnings."""
    check = ListingCheck()
    card = product.collectible_card
    if card is None:
        return check

    verification = product.collectible_verification
    if verification is None or verification.verification_status != "verified":
        check.block("VERIFIED", "The card has not been platform verified.")

    _check_own_auction(product, check)
    find_duplicate_signals(card, check)

    asset = card.blockchain_asset
    if asset is None:
        check.block("NO_BLOCKCHAIN_IDENTITY", "The card has no blockchain identity yet.")
        return check

    if asset.status in ("transferring", "transferred"):
        check.block("ALREADY_SOLD", "Ownership of this card has already been transferred.")

    seller_wallet = product.seller.wallet_address
    if not seller_wallet:
        check.block("SELLER_WALLET_MISSING", "The seller has not connected a wallet.")
    elif not product.seller.has_verified_wallet:
        check.block("SELLER_WALLET_UNVERIFIED", "The seller has not verified their wallet. Verify it on the profile page.")
    elif seller_wallet.lower() != (asset.owner_wallet or "").lower():
        check.block("SELLER_NOT_OWNER", "The seller's wallet is not the registered owner of this card.")

    strict = current_app.config["LISTING_REQUIRES_MINTED_TOKEN"]
    minted = asset.status == "minted" and asset.token_id is not None
    if not minted:
        message = "The card's blockchain token has not been minted yet."
        if strict:
            check.block("TOKEN_NOT_MINTED", message)
        else:
            check.warn("TOKEN_NOT_MINTED", message)
        return check

    sync = ownership.check_ownership_sync(asset)
    if sync.status == ownership.SYNC_ERROR:
        check.block("OWNERSHIP_SYNC_ERROR", f"OWNERSHIP SYNC ERROR: {sync.reason}")
    elif sync.status == ownership.UNVERIFIED and strict:
        check.block("CHAIN_UNVERIFIABLE", f"Ownership could not be verified on-chain: {sync.reason}")
    return check


def assert_listable(product):
    """Raise ListingBlocked unless the product may be listed. Call this before creating any Auction."""
    check = check_listing(product)
    if not check.ok:
        raise ListingBlocked(check)
    return check
