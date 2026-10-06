from ..extensions import db
from . import utcnow


class BlockchainAsset(db.Model):
    """Blockchain-backed digital identity for each verified physical trading card"""
    __tablename__ = 'blockchain_assets'

    id = db.Column(db.Integer, primary_key=True)
    
    # Link to the physical card
    collectible_card_id = db.Column(db.Integer, db.ForeignKey('collectible_cards.id'), unique=True, nullable=False)
    
    # Blockchain identity
    token_id = db.Column(db.Integer, unique=True, index=True)  # NFT-style token ID on blockchain
    contract_address = db.Column(db.String(42), nullable=False)  # EIP-55 checksummed Ethereum address
    blockchain_network = db.Column(db.String(30), nullable=False, default="sepolia")  # sepolia, mainnet, etc.
    
    # Ownership tracking
    owner_wallet = db.Column(db.String(42), nullable=False, index=True)  # EIP-55 checksummed, current owner
    previous_owner = db.Column(db.String(42))  # Track ownership history
    
    # Metadata and verification
    metadata_hash = db.Column(db.String(66))  # IPFS or hash of card metadata
    token_uri = db.Column(db.String(500))  # URI pointing to token metadata
    
    # Minting details (when token was created)
    mint_transaction_hash = db.Column(db.String(66), unique=True, index=True)  # Transaction hash when minted
    mint_block_number = db.Column(db.Integer)
    mint_date = db.Column(db.DateTime, default=utcnow)
    
    # Status: draft / minting / minted / transferring / transferred
    status = db.Column(db.String(20), nullable=False, default='draft')
    
    # Audit trail
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    
    # Relationships
    collectible_card = db.relationship('CollectibleCard', backref=db.backref('blockchain_asset', uselist=False))
    
    def __repr__(self):
        return f'<BlockchainAsset Card:{self.collectible_card_id} Token:{self.token_id} Owner:{self.owner_wallet[:6]}...>'


class BlockchainTransfer(db.Model):
    """Audit trail for blockchain-based ownership transfers"""
    __tablename__ = 'blockchain_transfers'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Link to the asset being transferred
    blockchain_asset_id = db.Column(db.Integer, db.ForeignKey('blockchain_assets.id'), nullable=False)
    
    # Ownership change
    from_wallet = db.Column(db.String(42), nullable=False, index=True)  # Previous owner
    to_wallet = db.Column(db.String(42), nullable=False, index=True)  # New owner
    
    # Auction details
    auction_id = db.Column(db.Integer, db.ForeignKey('auctions.id'))  # Which auction triggered this transfer
    
    # Blockchain details
    transaction_hash = db.Column(db.String(66), unique=True, index=True)  # Transfer transaction
    block_number = db.Column(db.Integer)
    chain_id = db.Column(db.Integer)
    network = db.Column(db.String(30), default="sepolia")
    
    # Status: pending / confirmed / failed
    status = db.Column(db.String(20), default='pending')
    failure_reason = db.Column(db.Text)
    
    # Timestamps
    requested_at = db.Column(db.DateTime, default=utcnow)
    confirmed_at = db.Column(db.DateTime)
    
    # Relationships
    blockchain_asset = db.relationship('BlockchainAsset', backref=db.backref('transfers', cascade='all, delete-orphan'))
    auction = db.relationship('Auction', backref='ownership_transfer')
    
    def __repr__(self):
        return f'<BlockchainTransfer {self.from_wallet[:6]}... -> {self.to_wallet[:6]}... Token:{self.blockchain_asset_id}>'
