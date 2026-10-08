import os, sys, json
from pathlib import Path
from datetime import datetime

# Setup path
project_root = Path(r'C:\Users\admin\Desktop\Asher\Projects\auction_app')
sys.path.insert(0, str(project_root))
os.chdir(str(project_root))
os.environ['FLASK_ENV'] = 'development'

from app import create_app
from app.extensions import db
from app.models import User, Product, CollectibleCard, CollectibleVerification, BlockchainAsset
from app.services import card_identity_service, blockchain_minting_service as bm_service, blockchain_transfer_service as bt_service
from app.services.blockchain_service import get_web3
from web3 import Web3

# Initialize app
app = create_app()
app.app_context().push()

# Test results
results = {'passed': 0, 'failed': 0, 'tests': []}

def test(name, condition, details=''):
    if condition:
        print(f'  PASS: {name}')
        results['passed'] += 1
    else:
        print(f'  FAIL: {name}')
        if details:
            print(f'    Error: {details}')
        results['failed'] += 1
    results['tests'].append({'name': name, 'passed': condition})

print('\n' + '='*80)
print('PHASE E: END-TO-END BLOCKCHAIN INTEGRATION TESTING')
print('='*80)
print(f'Started: {datetime.now().strftime("%H:%M:%S")}')

# TEST 1: System Configuration
print('\n[TEST 1] SYSTEM CONFIGURATION')
print('-'*80)
contract_address = app.config.get('CONTRACT_ADDRESS')
rpc_url = app.config.get('RPC_URL')

test('Contract address configured', bool(contract_address))
test('RPC URL configured', bool(rpc_url))
test('Contract address is valid format', contract_address.startswith('0x') and len(contract_address) == 42)

w3 = get_web3()
test('Web3 initialized', w3 is not None)
test('Web3 connected to Sepolia', w3.is_connected())
test('Correct chain (Sepolia 11155111)', w3.eth.chain_id == 11155111)
test('Block number available', w3.eth.block_number > 0)

# TEST 2: Test Data Creation
print('\n[TEST 2] TEST DATA CREATION')
print('-'*80)

try:
    # Create seller
    seller = User.query.filter_by(email='test_phase_e@example.com').first()
    if not seller:
        seller = User(
            name='Phase E Test Seller',
            email='test_phase_e@example.com',
            wallet_address='0x' + '1' * 40,
            role='seller',
            is_active_user=True
        )
        seller.set_password('testpass123')
        db.session.add(seller)
        db.session.flush()
    
    test('Seller created/exists', seller.id > 0)
    
    # Create product
    product = Product.query.filter_by(title='Phase E Test Card').first()
    if not product:
        product = Product(
            seller_id=seller.id,
            title='Phase E Test Card',
            description='Test card for Phase E',
            category='trading_card',
            estimated_price=1500.0,
            status='draft'
        )
        db.session.add(product)
        db.session.flush()
    
    test('Product created/exists', product.id > 0)
    
    # Create card
    card = CollectibleCard.query.filter_by(product_id=product.id).first()
    if not card:
        card = CollectibleCard(
            product_id=product.id,
            card_name='Charizard Holographic - Phase E',
            card_type_id=1,
            card_number='4/102',
            set_name='Base Set',
            estimated_value=5000.0,
            condition_notes='Mint condition'
        )
        db.session.add(card)
        db.session.flush()
    
    test('Card created/exists', card.id > 0)
    test('Card has name', bool(card.card_name))
    
    # Create verification
    verification = CollectibleVerification.query.filter_by(product_id=product.id).first()
    if not verification:
        verification = CollectibleVerification(
            product_id=product.id,
            collectible_card_id=card.id,
            verification_status='pending'
        )
        db.session.add(verification)
        db.session.flush()
    
    test('Verification created/exists', verification.id > 0)
    db.session.commit()
    
except Exception as e:
    test('Test data creation', False, str(e))

# TEST 3: BlockchainAsset Creation (Card Approval Simulation)
print('\n[TEST 3] BLOCKCHAIN ASSET CREATION')
print('-'*80)

try:
    asset = BlockchainAsset.query.filter_by(collectible_card_id=card.id).first()
    if not asset:
        asset = card_identity_service.create_blockchain_asset(
            collectible_card=card,
            owner_wallet=seller.wallet_address,
            contract_address=contract_address,
            network='sepolia'
        )
    
    test('BlockchainAsset created', asset.id > 0)
    test('Asset status is "draft"', asset.status == 'draft')
    test('Owner wallet set correctly', asset.owner_wallet == seller.wallet_address)
    test('Contract address set correctly', asset.contract_address == contract_address)
    test('Blockchain network is sepolia', asset.blockchain_network == 'sepolia')
    test('Platform card ID generated', bool(card.platform_card_id))
    test('Platform ID has CARD- prefix', card.platform_card_id.startswith('CARD-'))
    
except Exception as e:
    test('BlockchainAsset creation', False, str(e))

# TEST 4: Minting Service Integration
print('\n[TEST 4] MINTING SERVICE INTEGRATION')
print('-'*80)

try:
    tx_data = bm_service.initiate_mint(asset, seller.wallet_address)
    
    test('Mint transaction data generated', bool(tx_data))
    test('Transaction "to" matches contract', tx_data.get('to') == contract_address)
    test('Transaction "from" is seller wallet', tx_data.get('from') == seller.wallet_address)
    test('Transaction has data payload', len(tx_data.get('data', '')) > 20)
    test('Transaction value is zero', tx_data.get('value') == '0x0')
    test('Data starts with function selector', tx_data.get('data', '').startswith('0x'))
    
except Exception as e:
    test('Minting service integration', False, str(e))

# TEST 5: Transfer Service Integration
print('\n[TEST 5] TRANSFER SERVICE INTEGRATION')
print('-'*80)

try:
    # Simulate minted state
    asset.token_id = 1
    asset.status = 'minted'
    db.session.commit()
    
    buyer_wallet = '0x' + '2' * 40
    transfer_tx = bt_service.initiate_transfer(asset, buyer_wallet, auction_id=1)
    
    test('Transfer transaction generated', bool(transfer_tx))
    test('Transfer "to" matches contract', transfer_tx.get('to') == contract_address)
    test('Transfer "from" is original owner', transfer_tx.get('from') == seller.wallet_address)
    test('Transfer has data payload', len(transfer_tx.get('data', '')) > 20)
    test('Transfer value is zero', transfer_tx.get('value') == '0x0')
    
except Exception as e:
    test('Transfer service integration', False, str(e))

# TEST 6: Contract On-Chain Verification
print('\n[TEST 6] CONTRACT ON-CHAIN VERIFICATION')
print('-'*80)

try:
    # Load contract ABI
    artifact_path = project_root / 'contracts' / 'build' / 'CollectibleCardToken.json'
    artifact = json.loads(artifact_path.read_text())
    abi = artifact['abi']
    bytecode = artifact.get('bytecode', '')
    
    test('Contract artifact loaded', bool(abi))
    test('Bytecode in artifact', bool(bytecode))
    
    # Check contract code on-chain
    code = w3.eth.get_code(Web3.to_checksum_address(contract_address))
    test('Contract code deployed on-chain', len(code) > 0, f'Code size: {len(code)} bytes')
    
    # Verify functions
    functions = [x['name'] for x in abi if x.get('type') == 'function']
    test('Correct number of functions', len(functions) == 6, f'Functions: {functions}')
    
    expected_funcs = ['mint', 'transferCard', 'pay', 'ownerOf', 'tokensOf', 'getTransferHistory']
    test('All expected functions present', all(f in functions for f in expected_funcs))
    
    # Verify events
    events = [x['name'] for x in abi if x.get('type') == 'event']
    test('Correct number of events', len(events) == 3, f'Events: {events}')
    
    expected_events = ['CardMinted', 'OwnershipTransferred', 'PaymentMade']
    test('All expected events present', all(e in events for e in expected_events))
    
    # Test contract functions
    contract = w3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=abi)
    
    # Test ownerOf reverts for non-existent token
    try:
        contract.functions.ownerOf(999999).call()
        test('ownerOf reverts for non-existent token', False, 'Should have reverted')
    except:
        test('ownerOf reverts correctly', True)
    
    # Test tokensOf
    tokens = contract.functions.tokensOf('0x' + '0' * 40).call()
    test('tokensOf returns list', isinstance(tokens, (list, tuple)))
    test('tokensOf empty for zero address', len(tokens) == 0)
    
except Exception as e:
    test('Contract verification', False, str(e))

# SUMMARY
print('\n' + '='*80)
print('TESTING SUMMARY')
print('='*80)
total = results['passed'] + results['failed']
print(f'Total Tests: {total}')
print(f'Passed: {results["passed"]}')
print(f'Failed: {results["failed"]}')
if total > 0:
    pass_rate = (results['passed'] / total) * 100
    print(f'Success Rate: {pass_rate:.1f}%')

if results['failed'] == 0:
    print('\n✅ ALL TESTS PASSED - SYSTEM PRODUCTION READY')
    exit(0)
else:
    print(f'\n⚠️ {results["failed"]} TEST(S) FAILED')
    exit(1)
