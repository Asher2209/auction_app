// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title CollectibleCardToken
 * @notice One token per platform-verified physical trading card, with atomic settlement of auction sales.
 * @dev The token is a digital identity and ownership record. It does not prove the physical card is
 *      genuine: that is the platform's verification, whose hash is recorded at mint time.
 *
 *      Minting: only the owner (the platform admin wallet, signing through MetaMask) can mint, and a
 *      platform card ID can be minted once.
 *
 *      Selling: once an auction has ended, the token's owner calls authorizeSale with the winning wallet
 *      and the exact price. The winner's settle() then pays the seller and receives the token in ONE
 *      transaction: either both happen or the whole transaction reverts and nobody loses anything.
 *      The price and buyer are fixed on-chain by the owner, so nobody can take the token for less.
 */
contract CollectibleCardToken is ERC721, Ownable, ReentrancyGuard {
    struct Sale {
        address seller;
        address buyer;
        uint256 price;
        uint256 auctionId;
    }

    uint256 private _nextTokenId = 1;

    mapping(uint256 platformId => uint256 tokenId) public tokenIdOfPlatformId;
    mapping(uint256 tokenId => uint256 platformId) public platformIdOf;
    mapping(uint256 tokenId => bytes32 hash) public verificationHashOf;
    mapping(uint256 tokenId => Sale) public sales;
    mapping(uint256 auctionId => bool settled) public auctionSettled;

    event CardMinted(uint256 indexed tokenId, uint256 indexed platformId, address indexed owner, bytes32 verificationHash);
    event SaleAuthorized(uint256 indexed tokenId, uint256 indexed auctionId, address indexed seller, address buyer, uint256 price);
    event SaleCancelled(uint256 indexed tokenId, uint256 indexed auctionId);
    event CardSold(uint256 indexed auctionId, uint256 indexed tokenId, address indexed buyer, address seller, uint256 amount);

    error InvalidPlatformId();
    error PlatformIdAlreadyRegistered(uint256 platformId, uint256 tokenId);
    error NotTokenOwner(uint256 tokenId);
    error InvalidBuyer();
    error InvalidPrice();
    error AuctionAlreadySettled(uint256 auctionId);
    error NoSale(uint256 tokenId);
    error WrongAuction(uint256 expected, uint256 given);
    error NotTheBuyer();
    error WrongPayment(uint256 expected, uint256 sent);
    error SellerNoLongerOwns(uint256 tokenId);
    error TransferFailed();

    constructor(address platformAdmin) ERC721("ChainBid Collectible Card", "CARD") Ownable(platformAdmin) {}

    /**
     * @param to Initial owner: the seller's wallet.
     * @param platformId Numeric part of the platform card ID (CARD-000123 -> 123).
     * @param verificationHash keccak256 of the verified card record held off-chain.
     */
    function mint(address to, uint256 platformId, bytes32 verificationHash) external onlyOwner returns (uint256 tokenId) {
        if (platformId == 0) revert InvalidPlatformId();
        uint256 existing = tokenIdOfPlatformId[platformId];
        if (existing != 0) revert PlatformIdAlreadyRegistered(platformId, existing);

        tokenId = _nextTokenId++;
        tokenIdOfPlatformId[platformId] = tokenId;
        platformIdOf[tokenId] = platformId;
        verificationHashOf[tokenId] = verificationHash;
        _mint(to, tokenId);

        emit CardMinted(tokenId, platformId, to, verificationHash);
    }

    /// @notice The token's owner fixes the buyer and exact price for an ended auction and lets this
    ///         contract move this one token when that buyer pays. Calling again replaces the terms.
    function authorizeSale(uint256 tokenId, uint256 auctionId, address buyer, uint256 price) external {
        address seller = ownerOf(tokenId);
        if (msg.sender != seller) revert NotTokenOwner(tokenId);
        if (buyer == address(0) || buyer == seller) revert InvalidBuyer();
        if (price == 0) revert InvalidPrice();
        if (auctionSettled[auctionId]) revert AuctionAlreadySettled(auctionId);

        sales[tokenId] = Sale(seller, buyer, price, auctionId);
        _approve(address(this), tokenId, seller);
        emit SaleAuthorized(tokenId, auctionId, seller, buyer, price);
    }

    /// @notice The seller withdraws a sale authorization (and the approval that came with it).
    function cancelSale(uint256 tokenId) external {
        Sale memory sale = sales[tokenId];
        if (sale.seller == address(0)) revert NoSale(tokenId);
        if (msg.sender != sale.seller) revert NotTokenOwner(tokenId);

        delete sales[tokenId];
        if (_ownerOf(tokenId) == sale.seller) _approve(address(0), tokenId, address(0));
        emit SaleCancelled(tokenId, sale.auctionId);
    }

    /// @notice The authorized buyer pays the exact price and receives the token, atomically.
    function settle(uint256 auctionId, uint256 tokenId) external payable nonReentrant {
        Sale memory sale = sales[tokenId];
        if (sale.seller == address(0)) revert NoSale(tokenId);
        if (sale.auctionId != auctionId) revert WrongAuction(sale.auctionId, auctionId);
        if (auctionSettled[auctionId]) revert AuctionAlreadySettled(auctionId);
        if (msg.sender != sale.buyer) revert NotTheBuyer();
        if (msg.value != sale.price) revert WrongPayment(sale.price, msg.value);
        if (ownerOf(tokenId) != sale.seller) revert SellerNoLongerOwns(tokenId);

        // Effects before interactions, so nothing can re-enter and settle twice.
        auctionSettled[auctionId] = true;
        delete sales[tokenId];
        _transfer(sale.seller, sale.buyer, tokenId);

        (bool ok, ) = payable(sale.seller).call{value: msg.value}("");
        if (!ok) revert TransferFailed();

        emit CardSold(auctionId, tokenId, sale.buyer, sale.seller, msg.value);
    }

    function nextTokenId() external view returns (uint256) {
        return _nextTokenId;
    }
}
