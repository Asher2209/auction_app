"""Phase 4: the CollectibleCardToken contract and the verified, MetaMask-signed minting flow (real EVM, no mocks)."""
import json
from pathlib import Path

import pytest
from web3 import EthereumTesterProvider, Web3

from app.extensions import db
from app.models import BlockchainAsset
from app.services import blockchain_minting_service as bm

from .test_listing_validation import cat, card_type, make_card, seller  # noqa: F401 (fixtures)

ARTIFACT = json.loads((Path(__file__).resolve().parent.parent / "contracts" / "build" / "CollectibleCardToken.json").read_text())


class Chain:
    def __init__(self, app):
        self.w3 = Web3(EthereumTesterProvider())
        self.admin, self.seller_wallet, self.stranger = self.w3.eth.accounts[:3]
        self.address = self.deploy()
        self.contract = self.w3.eth.contract(address=self.address, abi=ARTIFACT["abi"])
        app.extensions["web3"] = self.w3
        app.config.update(CHAIN_ID=self.w3.eth.chain_id, CHAIN_NAME="Local", CONFIRMATIONS_REQUIRED=1,
                          COLLECTIBLE_CONTRACT_ADDRESS=self.address)

    def deploy(self):
        factory = self.w3.eth.contract(abi=ARTIFACT["abi"], bytecode=ARTIFACT["bytecode"])
        return self.w3.eth.wait_for_transaction_receipt(
            factory.constructor(self.admin).transact({"from": self.admin})).contractAddress

    def send(self, tx):
        """What MetaMask does after the admin approves: sign and broadcast the prepared transaction."""
        return Web3.to_hex(self.w3.eth.send_transaction({
            "from": tx["from"], "to": tx["to"], "data": tx["data"], "value": int(tx["value"], 16)}))


@pytest.fixture
def chain(app):
    return Chain(app)


def verified_asset(seller, cat, card_type, chain, **kw):
    seller.link_wallet(chain.seller_wallet)
    db.session.commit()
    p = make_card(seller, cat, card_type, owner=chain.seller_wallet, **kw)
    asset = p.collectible_card.blockchain_asset
    asset.contract_address = chain.address
    db.session.commit()
    return asset


def mint_through_flow(asset, chain):
    prep = bm.initiate_mint(asset, chain.admin)
    bm.submit_mint(asset, chain.send(prep["tx"]))
    return bm.confirm_mint(asset)


# ---- the fingerprint recorded on-chain ----------------------------------------------------------
def test_verification_hash_is_stable_and_tracks_identity_fields(seller, cat, card_type, chain):
    card = verified_asset(seller, cat, card_type, chain).collectible_card
    first = bm.verification_hash(card)
    assert first == bm.verification_hash(card) and len(first) == 66
    card.condition_notes = "scuffed corner"  # not an identity field
    assert bm.verification_hash(card) == first
    card.certification_number = "99999999"  # an identity field
    assert bm.verification_hash(card) != first


def test_platform_numeric_id(seller, cat, card_type, chain):
    card = verified_asset(seller, cat, card_type, chain).collectible_card
    assert bm.platform_numeric_id(card) == int(card.platform_card_id.split("-")[1])
    card.platform_card_id = "CARD-000000"
    with pytest.raises(bm.MintError):
        bm.platform_numeric_id(card)


# ---- preparing a mint ------------------------------------------------------------------------------
def test_prepare_builds_a_transaction_for_the_admin_wallet(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    prep = bm.initiate_mint(asset, chain.admin)
    assert prep["tx"]["from"] == chain.admin and prep["tx"]["to"] == chain.address and prep["tx"]["value"] == "0x0"
    assert asset.metadata_hash == prep["verification_hash"] == bm.verification_hash(asset.collectible_card)


def test_only_the_contract_owner_wallet_can_prepare_a_mint(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    for wallet in (chain.stranger, chain.seller_wallet):
        with pytest.raises(bm.MintError) as e:
            bm.initiate_mint(asset, wallet)
        assert e.value.status == 403


def test_unverified_card_cannot_be_minted(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain, verified=False)
    with pytest.raises(bm.MintError, match="verified"):
        bm.initiate_mint(asset, chain.admin)


def test_only_draft_assets_can_be_prepared(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain, status="minted", token_id=5)
    with pytest.raises(bm.MintError) as e:
        bm.initiate_mint(asset, chain.admin)
    assert e.value.status == 409


def test_bad_wallet_text_is_refused(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    for bad in ("", None, "not-a-wallet", "0x" + "ab" * 32):
        with pytest.raises(bm.MintError):
            bm.initiate_mint(asset, bad)


def test_prepare_without_a_blockchain_is_a_503(app, seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    del app.extensions["web3"]
    app.config["RPC_URL"] = None
    with pytest.raises(bm.MintError) as e:
        bm.initiate_mint(asset, chain.admin)
    assert e.value.status == 503


def test_a_card_already_on_chain_cannot_be_prepared_again(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    chain.contract.functions.mint(chain.seller_wallet, bm.platform_numeric_id(asset.collectible_card),
                                  b"\x00" * 32).transact({"from": chain.admin})
    with pytest.raises(bm.MintError) as e:
        bm.initiate_mint(asset, chain.admin)
    assert e.value.status == 409


# ---- the happy path -------------------------------------------------------------------------------
def test_full_mint_records_the_real_token_from_the_chain(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    result = mint_through_flow(asset, chain)
    assert result["status"] == "confirmed"
    assert asset.status == "minted" and asset.token_id == 1 and asset.mint_block_number
    assert chain.contract.functions.ownerOf(asset.token_id).call() == chain.seller_wallet
    assert chain.contract.functions.platformIdOf(asset.token_id).call() == bm.platform_numeric_id(asset.collectible_card)
    assert asset.token_uri.endswith(f"/collectibles/card-verification/{asset.collectible_card.platform_card_id}")


def test_token_ids_come_from_the_contract_not_from_the_database_id(seller, cat, card_type, chain):
    first = verified_asset(seller, cat, card_type, chain)
    second = verified_asset(seller, cat, card_type, chain)
    mint_through_flow(second, chain)  # minted first, so the contract numbers it 1
    mint_through_flow(first, chain)
    assert (second.token_id, first.token_id) == (1, 2)
    assert first.token_id != first.id + 1000


def test_confirm_waits_for_the_required_confirmations(app, seller, cat, card_type, chain):
    app.config["CONFIRMATIONS_REQUIRED"] = 3
    asset = verified_asset(seller, cat, card_type, chain)
    prep = bm.initiate_mint(asset, chain.admin)
    bm.submit_mint(asset, chain.send(prep["tx"]))
    pending = bm.confirm_mint(asset)
    assert pending["status"] == "pending" and asset.status == "minting" and asset.token_id is None
    chain.w3.provider.ethereum_tester.mine_blocks(2)
    assert bm.confirm_mint(asset)["status"] == "confirmed" and asset.status == "minted"


def test_confirming_twice_changes_nothing(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    mint_through_flow(asset, chain)
    again = bm.confirm_mint(asset)
    assert again["status"] == "confirmed" and again["token_id"] == asset.token_id == 1


# ---- a transaction hash is never trusted -----------------------------------------------------------
def submit_and_confirm(asset, tx_hash):
    bm.submit_mint(asset, tx_hash)
    return bm.confirm_mint(asset)


def test_an_unrelated_transaction_cannot_mint(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    plain = Web3.to_hex(chain.w3.eth.send_transaction({"from": chain.stranger, "to": chain.admin, "value": 1}))
    result = submit_and_confirm(asset, plain)
    assert result["status"] == "failed"
    assert asset.status == "draft" and asset.token_id is None and asset.mint_transaction_hash is None


def test_a_mint_of_another_card_cannot_be_reused(seller, cat, card_type, chain):
    mine, other = (verified_asset(seller, cat, card_type, chain) for _ in range(2))
    other_hash = chain.send(bm.initiate_mint(other, chain.admin)["tx"])
    result = submit_and_confirm(mine, other_hash)
    assert result["status"] == "failed" and "different platform card" in result["reason"]
    assert mine.status == "draft" and mine.token_id is None


def test_a_mint_to_a_different_owner_is_rejected(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    bm.initiate_mint(asset, chain.admin)  # records the expected hash
    rogue = chain.contract.functions.mint(chain.stranger, bm.platform_numeric_id(asset.collectible_card),
                                          bytes.fromhex(asset.metadata_hash[2:])).transact({"from": chain.admin})
    result = submit_and_confirm(asset, Web3.to_hex(rogue))
    assert result["status"] == "failed" and "different wallet" in result["reason"]


def test_a_mint_with_a_different_verification_hash_is_rejected(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    bm.initiate_mint(asset, chain.admin)
    forged = chain.contract.functions.mint(chain.seller_wallet, bm.platform_numeric_id(asset.collectible_card),
                                           b"\x07" * 32).transact({"from": chain.admin})
    result = submit_and_confirm(asset, Web3.to_hex(forged))
    assert result["status"] == "failed" and "verification hash" in result["reason"]


def test_a_mint_on_a_different_contract_is_rejected(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    prep = bm.initiate_mint(asset, chain.admin)
    impostor = Chain.deploy(chain)
    tx = dict(prep["tx"], to=impostor)
    result = submit_and_confirm(asset, chain.send(tx))
    assert result["status"] == "failed" and "not sent to the card token contract" in result["reason"]


def test_the_same_transaction_cannot_be_attached_to_two_assets(seller, cat, card_type, chain):
    first, second = (verified_asset(seller, cat, card_type, chain) for _ in range(2))
    tx_hash = chain.send(bm.initiate_mint(first, chain.admin)["tx"])
    bm.submit_mint(first, tx_hash)
    with pytest.raises(bm.MintError) as e:
        bm.submit_mint(second, tx_hash)
    assert e.value.status == 409
    db.session.refresh(second)
    assert second.status == "draft" and second.mint_transaction_hash is None


def test_malformed_hashes_are_refused(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    for bad in ("", None, "0x123", "zz" * 33, 5):
        with pytest.raises(bm.MintError):
            bm.submit_mint(asset, bad)
    assert asset.status == "draft"


def test_an_unmined_hash_stays_pending(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    bm.submit_mint(asset, "0x" + "ab" * 32)
    assert bm.confirm_mint(asset)["status"] == "pending" and asset.status == "minting"


def test_verify_never_writes_to_the_database(seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    prep = bm.initiate_mint(asset, chain.admin)
    bm.submit_mint(asset, chain.send(prep["tx"]))
    assert bm.verify_mint(asset)["status"] == "confirmed"
    db.session.refresh(asset)
    assert asset.status == "minting" and asset.token_id is None


def test_a_wrong_network_is_reported_not_treated_as_a_failed_mint(app, seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    bm.submit_mint(asset, chain.send(bm.initiate_mint(asset, chain.admin)["tx"]))
    app.config["CHAIN_ID"] = 1
    assert bm.confirm_mint(asset)["status"] == "error"
    assert asset.status == "minting"


# ---- the admin routes ---------------------------------------------------------------------------------
from .conftest import login  # noqa: E402


def as_admin(client):
    login(client, "admin@t.test")


def post_json(client, url, body=None):
    return client.post(url, json=body or {})


def test_token_pages_are_admin_only(client, users, seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    gets = ["/admin/tokens", f"/admin/tokens/{asset.id}"]
    posts = [f"/admin/tokens/{asset.id}/mint/prepare", f"/admin/tokens/{asset.id}/mint/submit",
             f"/admin/tokens/{asset.id}/verify"]
    for path in gets + posts:
        assert (client.get(path) if path in gets else client.post(path)).status_code == 302, path  # not logged in
    for role in ("buyer", "seller"):
        client.post("/auth/logout")
        login(client, f"{role}@t.test")
        for path in gets:
            assert client.get(path).status_code == 403, (role, path)
        for path in posts:
            assert client.post(path, json={}).status_code == 403, (role, path)
    assert BlockchainAsset.query.one().status == "draft"


def test_token_list_and_detail_pages_render_for_every_status(client, users, seller, cat, card_type, chain):
    draft = verified_asset(seller, cat, card_type, chain)
    minted = verified_asset(seller, cat, card_type, chain)
    mint_through_flow(minted, chain)
    minting = verified_asset(seller, cat, card_type, chain)
    bm.submit_mint(minting, "0x" + "cd" * 32)
    as_admin(client)
    listing = client.get("/admin/tokens").get_data(as_text=True)
    assert all(a.collectible_card.platform_card_id in listing for a in (draft, minted, minting))
    assert "Mint token" in client.get(f"/admin/tokens/{draft.id}").get_data(as_text=True)
    assert "Check the blockchain now" in client.get(f"/admin/tokens/{minting.id}").get_data(as_text=True)
    done = client.get(f"/admin/tokens/{minted.id}").get_data(as_text=True)
    assert "Minted. Token #1" in done and "Mint token" not in done
    assert client.get("/admin/tokens?status=minted").get_data(as_text=True).count("<tr>") == 2  # header + 1 row
    assert client.get("/admin/tokens?status=bogus").status_code == 200
    assert client.get("/admin/tokens/9999").status_code == 404


def test_detail_page_says_when_the_blockchain_is_not_configured(app, client, users, seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    del app.extensions["web3"]
    app.config["RPC_URL"] = None
    as_admin(client)
    html = client.get(f"/admin/tokens/{asset.id}").get_data(as_text=True)
    assert "blockchain is not configured" in html and "Mint token" not in html


def test_full_mint_through_the_routes(client, users, seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    as_admin(client)
    prep = post_json(client, f"/admin/tokens/{asset.id}/mint/prepare", {"wallet_address": chain.admin}).get_json()
    assert prep["ok"] and prep["tx"]["to"] == chain.address and prep["chain"]["id_hex"] == hex(chain.w3.eth.chain_id)
    sub = post_json(client, f"/admin/tokens/{asset.id}/mint/submit", {"tx_hash": chain.send(prep["tx"])}).get_json()
    assert sub == {"ok": True}
    result = post_json(client, f"/admin/tokens/{asset.id}/verify").get_json()
    assert result["ok"] and result["status"] == "confirmed" and result["token_id"] == 1
    db.session.refresh(asset)
    assert asset.status == "minted" and asset.token_id == 1


def test_prepare_route_refuses_the_wrong_wallet_and_junk(client, users, seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    as_admin(client)
    url = f"/admin/tokens/{asset.id}/mint/prepare"
    wrong = post_json(client, url, {"wallet_address": chain.stranger})
    assert wrong.status_code == 403 and wrong.get_json()["ok"] is False
    for body in ({}, {"wallet_address": 5}, {"wallet_address": ["x"]}):
        assert post_json(client, url, body).status_code == 400
    assert client.post(url, data="not json", content_type="text/plain").status_code == 400


def test_submit_and_verify_routes_reject_a_stranger_transaction(client, users, seller, cat, card_type, chain):
    asset = verified_asset(seller, cat, card_type, chain)
    as_admin(client)
    plain = Web3.to_hex(chain.w3.eth.send_transaction({"from": chain.stranger, "to": chain.admin, "value": 1}))
    assert post_json(client, f"/admin/tokens/{asset.id}/mint/submit", {"tx_hash": "nope"}).status_code == 400
    assert post_json(client, f"/admin/tokens/{asset.id}/mint/submit", {"tx_hash": plain}).status_code == 200
    result = post_json(client, f"/admin/tokens/{asset.id}/verify").get_json()
    assert result["status"] == "failed"
    db.session.refresh(asset)
    assert asset.status == "draft" and asset.token_id is None


def test_a_minted_card_passes_the_phase3_listing_gate_in_strict_mode(app, seller, cat, card_type, chain):
    from app.services import auction_validation_service as avs
    app.config["LISTING_REQUIRES_MINTED_TOKEN"] = True
    asset = verified_asset(seller, cat, card_type, chain)
    mint_through_flow(asset, chain)
    assert avs.check_listing(asset.collectible_card.product).ok  # real on-chain ownerOf agrees with MySQL


def test_a_token_moved_on_chain_trips_the_ownership_sync_check(app, seller, cat, card_type, chain):
    from app.services import auction_validation_service as avs
    asset = verified_asset(seller, cat, card_type, chain)
    mint_through_flow(asset, chain)
    chain.contract.functions.transferFrom(chain.seller_wallet, chain.stranger, asset.token_id).transact(
        {"from": chain.seller_wallet})
    check = avs.check_listing(asset.collectible_card.product)
    assert "OWNERSHIP_SYNC_ERROR" in check.codes()
    assert asset.owner_wallet == chain.seller_wallet  # MySQL is flagged, never silently overwritten


# ---- deployment script ----------------------------------------------------------------------------------
def test_deploy_script_deploys_a_token_contract_owned_by_the_admin_wallet(app, seller, cat, card_type, chain, monkeypatch):
    import importlib.util
    from eth_account import Account
    path = Path(__file__).resolve().parent.parent / "scripts" / "deploy_contract.py"
    spec = importlib.util.spec_from_file_location("deploy_contract", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    deployer = Account.create()
    chain.w3.eth.send_transaction({"from": chain.stranger, "to": deployer.address, "value": Web3.to_wei(1, "ether")})
    address, chain_id = script.deploy(chain.w3, deployer.key.hex(), script.TOKEN_ARTIFACT, (chain.admin,))
    deployed = chain.w3.eth.contract(address=address, abi=ARTIFACT["abi"])
    assert chain_id == chain.w3.eth.chain_id
    assert deployed.functions.owner().call() == chain.admin != deployer.address  # the deployer does not keep control
    assert deployed.functions.nextTokenId().call() == 1
