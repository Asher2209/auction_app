"""A stand-in for a MetaMask smart account (EIP-7702), for tests on the in-process chain.

A smart account sends the wallet's call through other code: on Sepolia, tx.to is MetaMask's DelegationManager and the
target contract sees the account's own address as msg.sender. SmartAccount reproduces exactly that: the transaction
goes to SmartAccount (so tx.to is not our contract), and our contract sees SmartAccount's address as msg.sender, so
in these tests the SmartAccount's address plays the wallet. It can also forge look-alike events from its own address.
"""
from functools import lru_cache

import solcx
from web3 import Web3

SOURCE = """
pragma solidity ^0.8.24;
contract SmartAccount {
    event CardMinted(uint256 indexed tokenId, uint256 indexed platformId, address indexed owner, bytes32 verificationHash);
    event CardSold(uint256 indexed auctionId, uint256 indexed tokenId, address indexed buyer, address seller, uint256 amount);
    event Transfer(address indexed from, address indexed to, uint256 indexed tokenId);
    event PaymentMade(uint256 indexed auctionId, address indexed buyer, address indexed seller, uint256 amount);

    function execute(address target, bytes calldata data) external payable {
        (bool ok, bytes memory ret) = target.call{value: msg.value}(data);
        if (!ok) assembly { revert(add(ret, 32), mload(ret)) }
    }
    function forgeMint(uint256 tokenId, uint256 platformId, address owner, bytes32 h) external {
        emit CardMinted(tokenId, platformId, owner, h);
    }
    function forgeSale(uint256 auctionId, uint256 tokenId, address buyer, address seller, uint256 amount) external payable {
        emit Transfer(seller, buyer, tokenId);
        emit CardSold(auctionId, tokenId, buyer, seller, amount);
    }
    function forgePayment(uint256 auctionId, address seller) external payable {
        emit PaymentMade(auctionId, address(this), seller, msg.value);
    }
}
"""


@lru_cache(maxsize=1)
def _compiled():
    out = solcx.compile_source(SOURCE, output_values=["abi", "bin"], solc_version="0.8.24")
    return next(v for k, v in out.items() if k.endswith(":SmartAccount"))


def deploy(w3, sender):
    iface = _compiled()
    receipt = w3.eth.wait_for_transaction_receipt(
        w3.eth.contract(abi=iface["abi"], bytecode=iface["bin"]).constructor().transact({"from": sender}))
    return w3.eth.contract(address=receipt.contractAddress, abi=iface["abi"])


def send_through(account, signer, target, data, value=0):
    """The wallet's call, wrapped: sent by `signer` to the smart account, which calls `target`. Returns the hash."""
    tx_hash = account.functions.execute(Web3.to_checksum_address(target), data).transact(
        {"from": signer, "value": value})
    receipt = account.w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["to"] == account.address  # tx.to is the wrapper, not our contract, as on Sepolia
    return Web3.to_hex(tx_hash)
