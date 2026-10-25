# Phase A Setup Guide: Unique Card Identity & QR Codes

## Overview
Phase A implements the foundation for unique physical card identity:
- **Platform Card ID** (CARD-000001 format)
- **Blockchain Asset Model** for tracking token identity
- **QR Code Generation** linking to public verification page
- **Public Card Verification Page** accessible via QR scan

## Files Added

### Models
- `app/models/blockchain_assets.py` - BlockchainAsset and BlockchainTransfer models

### Services
- `app/services/qrcode_service.py` - QR code generation
- `app/services/card_identity_service.py` - Card identity and blockchain asset management

### Routes
- `app/blueprints/collectibles/routes.py` - Public card verification route

### Templates
- `app/templates/collectibles/card_verification.html` - Public card details page

### Migration
- `migrate_phase_a.py` - Database migration script

## Installation Steps

### 1. Install QRCode Dependency
```bash
pip install qrcode[pil]
```

### 2. Run Database Migration
The migration creates new tables and assigns platform card IDs:

```bash
python migrate_phase_a.py
```

This will:
- Create `blockchain_assets` table
- Create `blockchain_transfers` table
- Assign platform_card_id to existing CollectibleCard records
- Add `platform_card_id` column to collectible_cards table

### 3. Verify Installation
```bash
python -c "from app.models import BlockchainAsset, BlockchainTransfer; print('Models imported successfully')"
python -c "from app.services import qrcode_service, card_identity_service; print('Services imported successfully')"
```

## Database Schema Changes

### CollectibleCard Table (Modified)
- Added: `platform_card_id` VARCHAR(20) - UNIQUE, INDEXED

Example format: CARD-000001

### New Tables

#### blockchain_assets
```
id (PK)
collectible_card_id (FK) - UNIQUE
token_id (UNIQUE, INDEXED)
contract_address VARCHAR(42)
blockchain_network VARCHAR(30)
owner_wallet VARCHAR(42) - INDEXED
previous_owner VARCHAR(42)
metadata_hash VARCHAR(66)
token_uri VARCHAR(500)
mint_transaction_hash VARCHAR(66) - UNIQUE, INDEXED
mint_block_number
mint_date
status (draft/minting/minted/transferring/transferred)
created_at, updated_at
```

#### blockchain_transfers
```
id (PK)
blockchain_asset_id (FK)
from_wallet VARCHAR(42) - INDEXED
to_wallet VARCHAR(42) - INDEXED
auction_id (FK)
transaction_hash VARCHAR(66) - UNIQUE, INDEXED
block_number
chain_id
network VARCHAR(30)
status (pending/confirmed/failed)
failure_reason
requested_at, confirmed_at
```

## Integration Points

### Admin Verification Flow
When admin approves a card:
1. `assign_platform_card_id()` - Assigns CARD-XXXXXX format ID
2. `create_blockchain_asset()` - Creates blockchain asset record (status: draft)
3. Success message includes platform card ID

### Public Access
URL: `/collectible/verify/{platform_card_id}`

Example: `/collectible/verify/CARD-000001`

Shows:
- Card image
- Card details (set, number, condition, etc.)
- Verification status
- Blockchain identity (if minted)
- QR code linking to this page
- Seller information (public only)

## Key Services

### qrcode_service.py
```python
generate_platform_card_id(card_id) -> str
generate_qr_code_svg(platform_card_id) -> str
save_qr_code_to_file(platform_card_id, card_id) -> str
get_qr_code_html(platform_card_id) -> str
```

### card_identity_service.py
```python
assign_platform_card_id(collectible_card) -> str
create_blockchain_asset(...) -> BlockchainAsset
assign_token_id(blockchain_asset, token_id) -> None
mark_token_minted(blockchain_asset, tx_hash, block_number) -> None
check_card_already_listed(collectible_card) -> dict
validate_card_ownership(collectible_card, seller_wallet) -> dict
```

## Testing Phase A

### 1. Test Platform Card ID Assignment
```python
from app import create_app
from app.models import CollectibleCard
from app.services.card_identity_service import assign_platform_card_id

app = create_app()
with app.app_context():
    card = CollectibleCard.query.first()
    platform_id = assign_platform_card_id(card)
    print(f"Platform ID: {platform_id}")  # Should print: CARD-000001
```

### 2. Test Blockchain Asset Creation
```python
from app.services.card_identity_service import create_blockchain_asset

with app.app_context():
    card = CollectibleCard.query.first()
    asset = create_blockchain_asset(
        collectible_card=card,
        owner_wallet="0x1234567890123456789012345678901234567890",
        contract_address="0x1234567890123456789012345678901234567890"
    )
    print(f"Asset created: {asset.id}")
    print(f"Status: {asset.status}")  # Should print: draft
```

### 3. Test QR Code Generation
```python
from app.services.qrcode_service import generate_qr_code_svg

with app.app_context():
    svg = generate_qr_code_svg("CARD-000001")
    print(f"SVG length: {len(svg)}")  # Should be > 1000
    print(svg[:100])  # Should start with <svg
```

### 4. Test Public Card Page
1. Verify card through admin
2. Visit: `http://localhost:5000/collectible/verify/CARD-000001`
3. Should see:
   - Card name, image, details
   - Platform card ID
   - QR code
   - Blockchain identity (if created)

## Next Steps (Phase B)

Phase A foundation is complete. Phase B will add:
- Token minting workflow
- Smart contract integration for minting
- Ownership transfer on blockchain
- Confirmation handling

## Troubleshooting

### qrcode module not found
```bash
pip install qrcode[pil]
```

### Migration fails
```bash
# Check database connection
python -c "from app import create_app, db; app = create_app(); db.create_all()"
```

### Template not rendering
- Check `app/templates/collectibles/` directory exists
- Clear browser cache and restart Flask

## Files Summary

| File | Purpose |
|------|---------|
| blockchain_assets.py | Database models for blockchain identity |
| qrcode_service.py | QR code generation utilities |
| card_identity_service.py | Card identity management |
| collectibles/routes.py | Public card verification route |
| card_verification.html | Template for public page |
| migrate_phase_a.py | Database migration script |

---
**Phase A Status: COMPLETE**

Ready to proceed to Phase B (Token Minting)
