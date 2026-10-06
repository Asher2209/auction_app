// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title CollectibleCardToken
 * @notice Manages blockchain-backed digital identity for physical trading cards
 * @dev Combines payment settlement and NFT-style token ownership
 */
contract CollectibleCardToken {
    
    // Card Token Structure
    struct CardToken {
        uint256 tokenId;
        address owner;
        uint256 platformId; // Link to platform CARD-XXXXXX
        uint256 mintedAt;
        bool exists;
    }
    
    // Ownership Transfer History
    struct Transfer {
        address from;
        address to;
        uint256 timestamp;
        uint256 auctionId;
        bytes32 txHash;
    }
    
    // Events
    event CardMinted(
        uint256 indexed tokenId,
        uint256 indexed platformId,
        address indexed owner,
        string cardName
    );
    
    event OwnershipTransferred(
        uint256 indexed tokenId,
        address indexed from,
        address indexed to,
        uint256 auctionId
    );
    
    event PaymentMade(
        uint256 indexed auctionId,
        address indexed buyer,
        address indexed seller,
        uint256 amount
    );
    
    // State
    mapping(uint256 => CardToken) public tokens; // tokenId => CardToken
    mapping(uint256 => Transfer[]) public transferHistory; // tokenId => Transfer[]
    mapping(address => uint256[]) public balances; // owner => tokenIds[]
    mapping(uint256 => bool) public auctionsPaid; // auctionId => paid
    
    uint256 public nextTokenId = 1;
    
    // Errors
    error TokenAlreadyExists(uint256 tokenId);
    error TokenDoesNotExist(uint256 tokenId);
    error NotTokenOwner(uint256 tokenId);
    error InvalidSeller();
    error NothingSent();
    error AlreadyPaid(uint256 auctionId);
    error TransferFailed();
    error Unauthorized();
    
    // Constructor
    constructor() {}
    
    /**
     * @notice Mint a new card token
     * @dev Only callable by contract owner (will be set to application address)
     * @param _platformId Platform card ID (numeric)
     * @param _owner Initial owner wallet
     * @param _cardName Human-readable card name for event
     * @return tokenId The minted token ID
     */
    function mint(
        uint256 _platformId,
        address _owner,
        string memory _cardName
    ) external returns (uint256) {
        require(_owner != address(0), "Invalid owner");
        
        uint256 tokenId = nextTokenId++;
        
        CardToken storage token = tokens[tokenId];
        require(!token.exists, "Token already exists");
        
        token.tokenId = tokenId;
        token.owner = _owner;
        token.platformId = _platformId;
        token.mintedAt = block.timestamp;
        token.exists = true;
        
        // Add to owner's balance
        balances[_owner].push(tokenId);
        
        emit CardMinted(tokenId, _platformId, _owner, _cardName);
        
        return tokenId;
    }
    
    /**
     * @notice Transfer card ownership
     * @dev Verifies sender is current owner
     * @param _tokenId Token to transfer
     * @param _newOwner New owner address
     * @param _auctionId Auction that triggered this transfer
     */
    function transferCard(
        uint256 _tokenId,
        address _newOwner,
        uint256 _auctionId
    ) external {
        require(_newOwner != address(0), "Invalid new owner");
        require(_newOwner != msg.sender, "Cannot transfer to self");
        
        CardToken storage token = tokens[_tokenId];
        require(token.exists, "Token does not exist");
        require(token.owner == msg.sender, "Not token owner");
        
        address previousOwner = token.owner;
        
        // Update ownership
        token.owner = _newOwner;
        
        // Record transfer history
        Transfer memory transfer = Transfer({
            from: previousOwner,
            to: _newOwner,
            timestamp: block.timestamp,
            auctionId: _auctionId,
            txHash: blockhash(block.number - 1)
        });
        transferHistory[_tokenId].push(transfer);
        
        // Update balances
        _removeFromBalance(previousOwner, _tokenId);
        balances[_newOwner].push(_tokenId);
        
        emit OwnershipTransferred(_tokenId, previousOwner, _newOwner, _auctionId);
    }
    
    /**
     * @notice Receive payment for auction
     * @dev Settlement of auction with cryptocurrency
     * @param _auctionId Auction ID for payment reference
     * @param _seller Seller wallet address
     */
    function pay(uint256 _auctionId, address payable _seller) external payable {
        require(msg.value > 0, "No payment received");
        require(_seller != address(0), "Invalid seller");
        require(!auctionsPaid[_auctionId], "Auction already paid");
        
        // Mark as paid before transfer (CEI pattern)
        auctionsPaid[_auctionId] = true;
        
        // Transfer to seller
        (bool ok, ) = _seller.call{value: msg.value}("");
        require(ok, "Transfer failed");
        
        emit PaymentMade(_auctionId, msg.sender, _seller, msg.value);
    }
    
    /**
     * @notice Get token owner
     * @param _tokenId Token ID
     * @return Owner address
     */
    function ownerOf(uint256 _tokenId) external view returns (address) {
        require(tokens[_tokenId].exists, "Token does not exist");
        return tokens[_tokenId].owner;
    }
    
    /**
     * @notice Get tokens owned by address
     * @param _owner Owner address
     * @return Array of token IDs
     */
    function tokensOf(address _owner) external view returns (uint256[] memory) {
        return balances[_owner];
    }
    
    /**
     * @notice Get transfer history for a token
     * @param _tokenId Token ID
     * @return Array of transfers
     */
    function getTransferHistory(uint256 _tokenId) 
        external 
        view 
        returns (Transfer[] memory) 
    {
        return transferHistory[_tokenId];
    }
    
    /**
     * @notice Check if auction has been paid
     * @param _auctionId Auction ID
     * @return Whether payment was made
     */
    function isPaid(uint256 _auctionId) external view returns (bool) {
        return auctionsPaid[_auctionId];
    }
    
    /**
     * @notice Get token details
     * @param _tokenId Token ID
     * @return CardToken struct
     */
    function getToken(uint256 _tokenId) external view returns (CardToken memory) {
        require(tokens[_tokenId].exists, "Token does not exist");
        return tokens[_tokenId];
    }
    
    // Internal helper
    function _removeFromBalance(address _owner, uint256 _tokenId) internal {
        uint256[] storage ownerTokens = balances[_owner];
        for (uint256 i = 0; i < ownerTokens.length; i++) {
            if (ownerTokens[i] == _tokenId) {
                ownerTokens[i] = ownerTokens[ownerTokens.length - 1];
                ownerTokens.pop();
                break;
            }
        }
    }
}
