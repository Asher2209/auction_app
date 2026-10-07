"""What a buyer owns or is buying: cards won in auctions, and tokens held by the buyer's wallet.

Ownership is reported from the records the platform keeps in step with the chain (BlockchainAsset and BlockchainTransfer),
and each row says plainly whether the card is the buyer's on-chain, still being paid for, or paid without a token transfer.
"""
from sqlalchemy import func

from ..models import BlockchainAsset, Winner
from . import ownership_transfer_service as ots

OWNED, MOVED, PAID, PENDING = "OWNED", "MOVED", "PAID", "PENDING"
LABELS = {
    OWNED: ("Yours on the blockchain", "success"),
    MOVED: ("Token is now in another wallet", "secondary"),
    PAID: ("Paid. No token transfer recorded", "warning"),
    PENDING: ("Payment pending", "warning"),
}


def _same(a, b):
    return bool(a and b and a.lower() == b.lower())


def _row(user, card, auction=None, payment=None, price=None):
    asset = card.blockchain_asset
    transfer = ots.transfer_for_payment(payment) if payment is not None else None
    if payment is not None and payment.payment_status != "successful":
        code = PENDING
    elif _same(asset.owner_wallet if asset else None, user.wallet_address) and (transfer or auction is None):
        code = OWNED
    elif transfer is not None:
        code = MOVED
    else:
        code = PAID
    label, badge = LABELS[code]
    return {"card": card, "auction": auction, "payment": payment, "asset": asset, "transfer": transfer, "price": price,
            "code": code, "label": label, "badge": badge,
            "invoice": payment.invoice if payment is not None and payment.payment_status == "successful" else None}


def buyer_cards(user):
    """Rows for the cards this buyer won, then any other token their wallet holds."""
    rows = {}
    wins = Winner.query.filter_by(buyer_id=user.id).order_by(Winner.winning_time.desc()).all()
    for win in wins:
        card = win.auction.product.collectible_card
        if card is not None:
            rows[card.id] = _row(user, card, win.auction, win.auction.payment, win.winning_amount)
    if user.wallet_address:
        held = (BlockchainAsset.query
                .filter(func.lower(BlockchainAsset.owner_wallet) == user.wallet_address.lower(),
                        BlockchainAsset.status.in_(("minted", "transferred"))).all())
        for asset in held:
            if asset.collectible_card_id not in rows:
                rows[asset.collectible_card_id] = _row(user, asset.collectible_card)
    return list(rows.values())
