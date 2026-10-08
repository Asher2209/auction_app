// Crypto payment: connect a wallet (MetaMask), ask it to sign the transaction the SERVER prepared,
// then report the transaction hash back. The server verifies everything on the blockchain itself.
// This script never touches private keys or seed phrases; all text is written with textContent.
(function () {
  const root = document.getElementById("crypto-root");
  if (!root) return;

  const auctionId = root.dataset.auctionId;
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content;
  const connectBtn = document.getElementById("crypto-connect");
  const payBtn = document.getElementById("crypto-pay");
  const acct = document.getElementById("crypto-account");
  const err = document.getElementById("crypto-error");
  if (!connectBtn || !payBtn) return;

  let account = null;
  const say = (msg) => { err.textContent = msg || ""; };

  function post(path, body) {
    return fetch(`/payments/${auctionId}/crypto/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(body),
    }).then((r) => r.json().catch(() => ({ ok: false, error: "Unexpected server response." })));
  }

  function walletError(e) {
    if (e && e.code === 4001) return "You rejected the request in your wallet. Nothing was sent.";
    if (e && e.code === 4902) return "Your wallet does not have this network yet. Add it, then try again.";
    return (e && e.message) || "The wallet request failed.";
  }

  connectBtn.addEventListener("click", async () => {
    say("");
    const provider = window.ethereum;
    if (!provider) {
      say("No wallet found. Install MetaMask (or open this page in a browser that has it), then reload.");
      return;
    }
    try {
      const accounts = await provider.request({ method: "eth_requestAccounts" });
      if (!accounts || !accounts.length) { say("No account was shared by your wallet."); return; }
      account = accounts[0];
      acct.textContent = account;
      payBtn.disabled = false;
      connectBtn.textContent = "Reconnect";
    } catch (e) {
      say(walletError(e));
    }
  });

  payBtn.addEventListener("click", async () => {
    say("");
    const provider = window.ethereum;
    if (!provider || !account) { say("Connect your wallet first."); return; }
    const accept = document.getElementById("accept-crypto");
    if (!accept || !accept.checked) { say("Please tick the box to confirm you have read the Refund Policy."); return; }
    payBtn.disabled = true;
    try {
      // 1. the server locks the quote and builds the exact transaction
      const prep = await post("prepare", { wallet_address: account, accept_terms: true });
      if (!prep.ok) throw new Error(prep.error || "Could not start the payment.");

      // 2. the wallet must be on the right network
      const current = await provider.request({ method: "eth_chainId" });
      if (current.toLowerCase() !== prep.chain.id_hex.toLowerCase()) {
        await provider.request({ method: "wallet_switchEthereumChain", params: [{ chainId: prep.chain.id_hex }] });
      }

      // 3. the wallet shows the amount and recipient; the user approves (or rejects) it there
      const hash = await provider.request({ method: "eth_sendTransaction", params: [prep.tx] });

      // 4. tell the server which transaction to verify
      const sub = await post("submit", { tx_hash: hash });
      if (!sub.ok) throw new Error(sub.error || "The server could not record the transaction.");
      window.location.reload(); // the page now shows the confirmation progress
    } catch (e) {
      say(walletError(e));
      payBtn.disabled = false;
    }
  });
})();
