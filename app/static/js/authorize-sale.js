// The seller authorizes the transfer of a sold card: connect the wallet that owns the token (MetaMask), sign the
// transaction the SERVER prepared, then wait until the blockchain shows the authorization. No private keys are handled.
(function () {
  const root = document.getElementById("sale-root");
  if (!root) return;

  const base = `/seller/cards/${root.dataset.cardId}/sale`;
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content;
  const connectBtn = document.getElementById("sale-connect");
  const sendBtn = document.getElementById("sale-send");
  const checkBtn = document.getElementById("sale-check");
  const acct = document.getElementById("sale-account");
  const err = document.getElementById("sale-error");
  const msg = document.getElementById("sale-message");

  let account = null;
  const showMessage = (text) => { msg.textContent = text || ""; err.textContent = ""; };
  const showError = (text) => { err.textContent = text || ""; msg.textContent = ""; };
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function post(path, body) {
    return fetch(`${base}/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(body || {}),
    }).then((r) => r.json().catch(() => ({ ok: false, error: "Unexpected server response." })));
  }

  function walletError(e) {
    if (e && e.code === 4001) return "You rejected the request in your wallet. Nothing was sent.";
    if (e && e.code === 4902) return "Your wallet does not have this network yet. Add it, then try again.";
    return (e && e.message) || "The wallet request failed.";
  }

  async function check() {
    const res = await post("check");
    if (res.state === "authorized") { window.location.reload(); return true; }
    if (res.state === "mismatch") { showError(res.reason); return true; }
    showMessage(res.reason || "Waiting for the blockchain...");
    return false;
  }

  connectBtn.addEventListener("click", async () => {
    showError("");
    if (!window.ethereum) { showError("No wallet found. Install MetaMask, then reload."); return; }
    try {
      const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
      if (!accounts || !accounts.length) { showError("No account was shared by your wallet."); return; }
      account = accounts[0];
      acct.textContent = account;
      sendBtn.disabled = false;
    } catch (e) { showError(walletError(e)); }
  });

  sendBtn.addEventListener("click", async () => {
    showError("");
    if (!window.ethereum || !account) { showError("Connect your wallet first."); return; }
    sendBtn.disabled = true;
    try {
      const prep = await post("prepare", { wallet_address: account });
      if (!prep.ok) throw new Error(prep.error || "Could not prepare the authorization.");
      const current = await window.ethereum.request({ method: "eth_chainId" });
      if (current.toLowerCase() !== prep.chain.id_hex.toLowerCase()) {
        await window.ethereum.request({ method: "wallet_switchEthereumChain", params: [{ chainId: prep.chain.id_hex }] });
      }
      await window.ethereum.request({ method: "eth_sendTransaction", params: [prep.tx] });
      showMessage("Sent. Waiting for the blockchain to confirm it...");
      for (let i = 0; i < 40; i++) {
        await sleep(3000);
        if (await check()) return;
      }
      showMessage("Still waiting. Use Check the blockchain in a moment.");
    } catch (e) {
      showError(walletError(e));
    }
    sendBtn.disabled = false;
  });

  checkBtn.addEventListener("click", async () => { showMessage("Checking..."); await check(); });
})();
