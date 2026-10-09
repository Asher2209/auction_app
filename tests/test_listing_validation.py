from datetime import timedelta
from decimal import Decimal

import pytest
from web3.exceptions import ContractLogicError

from app.extensions import db
from app.models import (Auction, BlockchainAsset, CardType, Category, CollectibleCard, CollectibleVerification,
                        Product, ProductImage, Winner, utcnow)
from app.services import auction_validation_service as avs

from .conftest import login

WALLET_A = "0x" + "a1" * 20
WALLET_B = "0x" + "b2" * 20
CONTRACT = "0x" + "c3" * 20

CHECKS = ("card_identity", "set_checked", "card_number", "manufacturer", "images_reviewed", "condition_reviewed",
          "seller_info_reviewed", "counterfeit_check")


def complete_checklist(client, verification_id, **results):
    """The admin records the review: every check passes, grading included, unless a result is overridden (name=result).

    Pass grading_checked="" to leave the grading certificate unchecked. It only matters for a graded card.
    """
    data = {f"{check}_result": "verified" for check in (*CHECKS, "grading_checked")}
    data.update({f"{name}_result": value for name, value in results.items()})
    return client.post(f"/admin/cards/verify/{verification_id}/checklist", data=data)


class FakeChain:
    """Stands in for Web3: ownerOf(token).call() returns the owner, or raises the given error."""

    def __init__(self, owner=None, error=None):
        self.owner, self.error = owner, error
        self.eth = self
        self.functions = self

    def contract(self, address, abi):
        return self

    def ownerOf(self, token_id):
        return self

    def call(self):
        if self.error:
            raise self.error
        return self.owner


@pytest.fixture
def seller(users):
    users["seller"].link_wallet(WALLET_A)
    db.session.commit()
    return users["seller"]


@pytest.fixture
def card_type(app):
    t = CardType(name="Pokemon", slug="pokemon")
    db.session.add(t)
    db.session.commit()
    return t


@pytest.fixture
def cat(app):
    c = Category(name="Cards")
    db.session.add(c)
    db.session.commit()
    return c


_n = 0


def make_card(seller, cat, card_type, *, verified=True, asset=True, owner=WALLET_A, status="draft", token_id=None,
              grader="PSA", cert="12345678", auction_status=None, winner=None):
    """A card product with optional verification, blockchain asset and auction."""
    global _n
    _n += 1
    start = utcnow() + timedelta(hours=1)
    product = Product(seller_id=seller.id, category_id=cat.id, title=f"Charizard {_n}", description="d" * 12,
                      starting_price=Decimal("100"), auction_start=start, auction_end=start + timedelta(days=1))
    product.images.append(ProductImage(path="products/x.png"))
    db.session.add(product)
    db.session.commit()
    card = CollectibleCard(product_id=product.id, card_type_id=card_type.id, card_name=product.title,
                           condition="Near Mint", platform_card_id=f"CARD-{_n:06d}",
                           is_graded=bool(cert), grading_company=grader, certification_number=cert)
    db.session.add(card)
    db.session.commit()
    db.session.add(CollectibleVerification(product_id=product.id, collectible_card_id=card.id,
                                           collectible_type="trading_card",
                                           verification_status="verified" if verified else "pending"))
    if asset:
        db.session.add(BlockchainAsset(collectible_card_id=card.id, owner_wallet=owner, contract_address=CONTRACT,
                                       status=status, token_id=token_id))
    db.session.commit()
    if auction_status:
        a = Auction(product_id=product.id, start_time=start, end_time=start + timedelta(days=1),
                    original_end_time=start + timedelta(days=1), current_bid=Decimal("100"), status=auction_status)
        db.session.add(a)
        db.session.commit()
        if winner:
            db.session.add(Winner(auction_id=a.id, buyer_id=winner.id, winning_amount=Decimal("100")))
            db.session.commit()
    return product


def codes(product):
    return avs.check_listing(product).codes()


# ---- baseline ---------------------------------------------------------------
def test_verified_registered_card_owned_by_seller_is_listable(seller, cat, card_type):
    p = make_card(seller, cat, card_type)
    check = avs.assert_listable(p)
    assert check.ok
    assert [w.code for w in check.warnings] == ["TOKEN_NOT_MINTED"]  # not minted yet: allowed, but flagged


def test_product_without_card_is_not_checked(users, cat):
    p = Product(seller_id=users["seller"].id, category_id=cat.id, title="Book", description="d" * 12,
                starting_price=Decimal("5"), auction_start=utcnow(), auction_end=utcnow() + timedelta(days=1))
    db.session.add(p)
    db.session.commit()
    assert avs.check_listing(p).ok


# ---- verification and identity ----------------------------------------------
def test_unverified_card_is_blocked(seller, cat, card_type):
    assert codes(make_card(seller, cat, card_type, verified=False)) == {"VERIFIED"}


def test_card_without_blockchain_identity_is_blocked(seller, cat, card_type):
    assert "NO_BLOCKCHAIN_IDENTITY" in codes(make_card(seller, cat, card_type, asset=False))


# ---- ownership ---------------------------------------------------------------
def test_wrong_wallet_is_blocked(seller, cat, card_type):
    seller.link_wallet(WALLET_B)  # proven, but not the wallet the card is registered to
    db.session.commit()
    assert codes(make_card(seller, cat, card_type, owner=WALLET_A)) == {"SELLER_NOT_OWNER"}


def test_wrong_owner_is_blocked(seller, cat, card_type):
    assert codes(make_card(seller, cat, card_type, owner=WALLET_B)) == {"SELLER_NOT_OWNER"}


def test_wallet_comparison_ignores_case(seller, cat, card_type):
    assert avs.check_listing(make_card(seller, cat, card_type, owner=WALLET_A.upper().replace("0X", "0x"))).ok


def test_seller_without_wallet_is_blocked(seller, cat, card_type):
    seller.wallet_address = None
    db.session.commit()
    assert codes(make_card(seller, cat, card_type)) == {"SELLER_WALLET_MISSING"}


# ---- duplicates and sold cards ------------------------------------------------
@pytest.mark.parametrize("status", ["scheduled", "active"])
def test_card_already_in_live_auction_is_blocked(seller, cat, card_type, status):
    assert "DUPLICATE_ACTIVE_AUCTION" in codes(make_card(seller, cat, card_type, auction_status=status))


def test_sold_card_is_blocked(seller, users, cat, card_type):
    p = make_card(seller, cat, card_type, auction_status="closed", winner=users["buyer"])
    assert "ALREADY_SOLD" in codes(p)


def test_unsold_closed_auction_cannot_be_reused(seller, cat, card_type):
    assert "AUCTION_ALREADY_EXISTS" in codes(make_card(seller, cat, card_type, auction_status="closed"))


def test_transferred_token_is_blocked(seller, cat, card_type):
    assert "ALREADY_SOLD" in codes(make_card(seller, cat, card_type, status="transferred", token_id=7))


def test_same_certificate_in_live_auction_blocks_second_record(seller, cat, card_type):
    make_card(seller, cat, card_type, auction_status="active", cert="777")
    second = make_card(seller, cat, card_type, cert="777")
    assert "DUPLICATE_ACTIVE_AUCTION" in codes(second)


def test_certificate_match_is_normalised(seller, cat, card_type):
    make_card(seller, cat, card_type, auction_status="active", cert=" ab-1 ", grader="psa")
    assert "DUPLICATE_ACTIVE_AUCTION" in codes(make_card(seller, cat, card_type, cert="AB-1", grader=" PSA"))


def test_same_certificate_not_live_is_only_a_warning(seller, cat, card_type):
    make_card(seller, cat, card_type, cert="888")
    check = avs.check_listing(make_card(seller, cat, card_type, cert="888"))
    assert check.ok and "POTENTIAL_DUPLICATE" in {w.code for w in check.warnings}


def test_same_number_from_different_grader_is_not_a_duplicate(seller, cat, card_type):
    make_card(seller, cat, card_type, auction_status="active", cert="999", grader="PSA")
    assert avs.check_listing(make_card(seller, cat, card_type, cert="999", grader="BGS")).ok


def test_ungraded_cards_are_not_matched_on_certificate(seller, cat, card_type):
    make_card(seller, cat, card_type, auction_status="active", cert=None, grader=None)
    assert avs.check_listing(make_card(seller, cat, card_type, cert=None, grader=None)).ok


# ---- on-chain ownership --------------------------------------------------------
def minted(seller, cat, card_type):
    return make_card(seller, cat, card_type, status="minted", token_id=1847)


def test_onchain_owner_matching_passes_in_strict_mode(app, seller, cat, card_type):
    app.config["LISTING_REQUIRES_MINTED_TOKEN"] = True
    app.extensions["web3"] = FakeChain(owner=WALLET_A)
    assert avs.check_listing(minted(seller, cat, card_type)).ok


def test_onchain_owner_mismatch_is_blocked_even_when_not_strict(app, seller, cat, card_type):
    app.extensions["web3"] = FakeChain(owner=WALLET_B)
    assert codes(minted(seller, cat, card_type)) == {"OWNERSHIP_SYNC_ERROR"}


def test_missing_token_on_chain_is_a_sync_error(app, seller, cat, card_type):
    app.extensions["web3"] = FakeChain(error=ContractLogicError("nonexistent token"))
    assert codes(minted(seller, cat, card_type)) == {"OWNERSHIP_SYNC_ERROR"}


def test_unreachable_chain_fails_closed_in_strict_mode(app, seller, cat, card_type):
    app.config["LISTING_REQUIRES_MINTED_TOKEN"] = True
    app.extensions["web3"] = FakeChain(error=ConnectionError("rpc down"))
    assert codes(minted(seller, cat, card_type)) == {"CHAIN_UNVERIFIABLE"}


def test_unreachable_chain_is_tolerated_when_not_strict(app, seller, cat, card_type):
    app.extensions["web3"] = FakeChain(error=ConnectionError("rpc down"))
    assert avs.check_listing(minted(seller, cat, card_type)).ok


def test_unminted_token_is_blocked_in_strict_mode(app, seller, cat, card_type):
    app.config["LISTING_REQUIRES_MINTED_TOKEN"] = True
    assert codes(make_card(seller, cat, card_type)) == {"TOKEN_NOT_MINTED"}


def test_sync_error_does_not_modify_the_database_owner(app, seller, cat, card_type):
    app.extensions["web3"] = FakeChain(owner=WALLET_B)
    p = minted(seller, cat, card_type)
    avs.check_listing(p)
    assert p.collectible_card.blockchain_asset.owner_wallet == WALLET_A


def test_assert_listable_raises_with_every_violation(seller, cat, card_type):
    p = make_card(seller, cat, card_type, verified=False, owner=WALLET_B)
    with pytest.raises(avs.ListingBlocked) as e:
        avs.assert_listable(p)
    assert e.value.check.codes() == {"VERIFIED", "SELLER_NOT_OWNER"}


# ---- enforcement in the routes ---------------------------------------------------
def test_admin_cannot_create_auction_for_unlistable_card(client, users, seller, cat, card_type):
    p = make_card(seller, cat, card_type, verified=False)
    login(client, "admin@t.test")
    assert client.post(f"/admin/products/{p.id}/approve").status_code == 404  # the generic approval path is retired
    assert Auction.query.filter_by(product_id=p.id).count() == 0
    assert db.session.get(Product, p.id).approval_status == "pending"


def test_approving_a_card_registers_its_blockchain_identity(app, client, users, seller, cat, card_type):
    app.config["COLLECTIBLE_CONTRACT_ADDRESS"] = CONTRACT
    p = make_card(seller, cat, card_type, asset=False, verified=False)
    v = p.collectible_verification
    login(client, "admin@t.test")
    complete_checklist(client, v.id)
    client.post(f"/admin/cards/verify/{v.id}/approve", data={"approval_notes": "ok"})
    v = db.session.get(CollectibleVerification, v.id)
    asset = p.collectible_card.blockchain_asset
    assert v.verification_status == "verified" and v.verified_by == users["admin"].id
    assert asset.owner_wallet == WALLET_A and asset.status == "draft"


def test_approving_a_card_without_seller_wallet_creates_no_asset(app, client, users, cat, card_type):
    app.config["COLLECTIBLE_CONTRACT_ADDRESS"] = CONTRACT
    p = make_card(users["seller"], cat, card_type, asset=False, verified=False)
    login(client, "admin@t.test")
    complete_checklist(client, p.collectible_verification.id)
    client.post(f"/admin/cards/verify/{p.collectible_verification.id}/approve", data={})
    db.session.expire_all()
    assert p.collectible_verification.verification_status == "verified"  # approved, but nothing to register without a wallet
    assert BlockchainAsset.query.count() == 0
