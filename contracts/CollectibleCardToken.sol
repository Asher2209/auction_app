// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title CollectibleCardToken
 * @notice One token per platform-verified physical trading card.
 * @dev The token is a digital identity and ownership record. It does not prove the physical card is
 *      genuine: that is the platform's verification, whose hash is recorded at mint time.
 *      Only the owner (the platform admin's wallet, signing through MetaMask) can mint, and a platform
 *      card ID can be minted once. Transfers use the standard ERC-721 functions, so only the current
 *      owner (or an address they approved) can move a token.
 */
contract CollectibleCardToken is ERC721, Ownable {
    uint256 private _nextTokenId = 1;

    mapping(uint256 platformId => uint256 tokenId) public tokenIdOfPlatformId;
    mapping(uint256 tokenId => uint256 platformId) public platformIdOf;
    mapping(uint256 tokenId => bytes32 hash) public verificationHashOf;

    event CardMinted(uint256 indexed tokenId, uint256 indexed platformId, address indexed owner, bytes32 verificationHash);

    error InvalidPlatformId();
    error PlatformIdAlreadyRegistered(uint256 platformId, uint256 tokenId);

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

    function nextTokenId() external view returns (uint256) {
        return _nextTokenId;
    }
}
