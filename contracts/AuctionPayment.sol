// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title AuctionPayment
/// @notice Pays the seller of a won auction in ETH and records the payment as an event.
/// @dev Deliberately tiny. The contract never holds funds: everything sent is forwarded to the
///      seller in the same transaction. One payment per auction id is allowed, so the same
///      auction can never be paid twice. For an academic project on a TEST network only.
contract AuctionPayment {
    /// @notice Emitted for every successful payment. The web application verifies this event.
    event PaymentMade(
        uint256 indexed auctionId,
        address indexed buyer,
        address indexed seller,
        uint256 amount
    );

    /// @notice auctionId => already paid
    mapping(uint256 => bool) public paid;

    error NothingSent();
    error InvalidSeller();
    error AlreadyPaid(uint256 auctionId);
    error TransferFailed();

    function pay(uint256 auctionId, address payable seller) external payable {
        if (msg.value == 0) revert NothingSent();
        if (seller == address(0)) revert InvalidSeller();
        if (paid[auctionId]) revert AlreadyPaid(auctionId);

        // Effects before interaction (checks-effects-interactions), so a re-entering seller cannot pay twice.
        paid[auctionId] = true;

        (bool ok, ) = seller.call{value: msg.value}("");
        if (!ok) revert TransferFailed();

        emit PaymentMade(auctionId, msg.sender, seller, msg.value);
    }
}
