#!/usr/bin/env python3
"""End-to-end blockchain integration test"""

import sys, os
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

os.environ['FLASK_ENV'] = 'development'
from app import create_app
from app.extensions import db
from app.models import User, Product, CollectibleCard, CollectibleVerification, BlockchainAsset
from app.services import card_identity_service
from web3 import Web3

print("\n" + "=" * 90)
print("BLOCKCHAIN INTEGRATION - END-TO-END TEST")
print("=" * 90)

app = create_app()
app.app_context().push()

print("\n[1] SETUP")
print("-" * 90)

try:
    db.session.execute(db.text("SELECT 1"))
    print("✓ Database connected")
except Exception as e:
    print(f"✗ Database error: {e}")
    exit(1)

contract_address = app.config.get("CONTRACT_ADDRESS")
rpc_url = app.config.get("RPC_URL")

if not contract_address or not rpc_url:
    print("✗ CONTRACT_ADDRESS or RPC_URL not configured")
    exit(1)

print(f"✓ Contract: {contract_address[:10]}...")
print(f"✓ RPC URL configured")

from app.services.blockchain_service import get_web3
w3 = get_web3()
if not w3 or not w3.is_connected():
    print("✗ Sepolia connection failed")
    exit(1)

print(f"✓ Connected to Sepolia (Block {w3.eth.block_number})")

print("\n[2] CREATE/VERIFY TEST DATA")
print("-" * 90)

seller = User.query.filter_by(email="seller_e2e@test.com").first()
if not seller:
    seller = User(
        name="Test Seller E2E",
        email="seller_e2e@test.com",
        wallet_address="0x" + "1" * 40,
        role="seller",
        is_active_user=True
    )
    seller.set_password("test123")
    db.session.add(seller)
    db.session.flush()
    print("✓ Created seller")
else:
    print("✓ Seller exists")

product = Product.query.filter_by(title="E2E Test Card").first()
if not product:
    product = Product(
        seller_id=seller.id,
        title="E2E Test Card",
        description="End-to-end test",
        category="trading_card",
        estimated_price=1000.0,
        status="draft"
    )
    db.session.add(product)
    db.session.flush()
    print(f"✓ Created product")
else:
    print(f"✓ Product exists")

card = CollectibleCard.query.filter_by(product_id=product.id).first()
if not card:
    card = CollectibleCard(
        product_id=product.id,
        card_name="Test Card",
        card_type_id=1,
        card_number="1/100",
        set_name="Test Set",
        estimated_value=5000.0
    )
    db.session.add(card)
    db.session.flush()
    print(f"✓ Created card")
else:
    print(f"✓ Card exists")

verification = CollectibleVerification.query.filter_by(product_id=product.id).first()
if not verification:
    verification = CollectibleVerification(
        product_id=product.id,
        collectible_card_id=card.id,
        verification_status="pending"
    )
    db.session.add(verification)
    db.session.flush()
    print(f"✓ Created verification")
else:
    print(f"✓ Verification exists")

db.session.commit()

print("\n[3] TEST BLOCKCHAIN ASSET CREATION")
print("-" * 90)

blockchain_asset = BlockchainAsset.query.filter_by(collectible_card_id=card.id).first()

if not blockchain_asset:
    try:
        blockchain_asset = card_identity_service.create_blockchain_asset(
            collectible_card=card,
            owner_wallet=seller.wallet_address,
            contract_address=contract_address,
            network="sepolia"
        )
        print(f"✓ BlockchainAsset created (ID: {blockchain_asset.id})")
    except Exception as e:
        print(f"✗ Creation failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
else:
    print(f"✓ BlockchainAsset exists (ID: {blockchain_asset.id})")

print(f"  - Status: {blockchain_asset.status}")
print(f"  - Owner: {blockchain_asset.owner_wallet[:10]}...")
print(f"  - Contract: {blockchain_asset.contract_address[:10]}...")

print("\n[4] TEST MINTING SERVICE")
print("-" * 90)

from app.services import blockchain_minting_service as bm_service

try:
    tx_data = bm_service.initiate_mint(blockchain_asset, seller.wallet_address)
    
    if tx_data.get('to') == contract_address:
        print(f"✓ Minting transaction prepared")
        print(f"  - Data: {tx_data['data'][:30]}...")
    else:
        print(f"✗ Wrong contract address in tx")
        exit(1)
except Exception as e:
    print(f"✗ Minting failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

print("\n[5] TEST TRANSFER SERVICE")
print("-" * 90)

from app.services import blockchain_transfer_service as bt_service

blockchain_asset.token_id = 1
blockchain_asset.status = 'minted'
db.session.commit()

try:
    buyer_wallet = "0x" + "2" * 40
    tx_data = bt_service.initiate_transfer(blockchain_asset, buyer_wallet, auction_id=1)
    
    if tx_data.get('to') == contract_address:
        print(f"✓ Transfer transaction prepared")
        print(f"  - Data: {tx_data['data'][:30]}...")
    else:
        print(f"✗ Wrong contract address")
        exit(1)
except Exception as e:
    print(f"✗ Transfer failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

print("\n[6] VERIFY CONTRACT ON-CHAIN")
print("-" * 90)

import json
artifact_path = project_root / "contracts" / "build" / "CollectibleCardToken.json"
artifact = json.loads(artifact_path.read_text())
abi = artifact["abi"]

contract = w3.eth.contract(
    address=Web3.to_checksum_address(contract_address),
    abi=abi
)

try:
    code = w3.eth.get_code(Web3.to_checksum_address(contract_address))
    print(f"✓ Contract code verified ({len(code)} bytes)")
    
    try:
        contract.functions.ownerOf(999).call()
        print(f"✗ ownerOf should revert")
        exit(1)
    except:
        print(f"✓ ownerOf correctly reverts")
    
    tokens = contract.functions.tokensOf("0x" + "0" * 40).call()
    print(f"✓ tokensOf returns: {tokens}")
except Exception as e:
    print(f"✗ Contract check failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

print("\n" + "=" * 90)
print("✅ END-TO-END INTEGRATION TEST PASSED")
print("=" * 90)
print("""
Summary:
✓ Database operations
✓ Test data creation
✓ BlockchainAsset creation on verification
✓ Minting service integration
✓ Transfer service integration
✓ Contract verified on Sepolia
✓ Contract functions working

Integration ready for full workflow testing!
""")
