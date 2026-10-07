// Mint a card token: connect the admin wallet (MetaMask), ask it to sign the transaction the SERVER prepared,
// report the hash, then ask the server to verify the mint on the blockchain. No private keys are ever handled.
(function () {
  const root = document.getElementById("mint-root");
  if (!root) return;

  const base = `/admin/tokens/${root.dataset.assetId}`;
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content;
  const connectBtn = document.getElementById("mint-connect");
  const sendBtn = document.getElementById("mint-send");
  const checkBtn = document.getElementById("mint-check");
  const acct = document.getElementById("mint-account");
  const err = document.getElementById("mint-error");
  const msg = document.getElementById("mint-message");

  let account = null;
  const showMessage = (text) => { msg.textContent = text || ""; err.textContent = ""; };
  const showError = (text) => { err.textContent = text || ""; msg.textContent = ""; };

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

  async function verify() {
    const res = await post("verify");
    if (res.status === "confirmed") { window.location.reload(); return; }
    if (res.status === "failed") { showError(res.reason); return; }
    if (res.status === "error") { showError(res.reason); return; }
    showMessage(res.reason || "Still waiting for the blockchain.");
  }

  if (connectBtn) {
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
  }

  if (sendBtn) {
    sendBtn.addEventListener("click", async () => {
      showError("");
      if (!window.ethereum || !account) { showError("Connect your wallet first."); return; }
      sendBtn.disabled = true;
      try {
        const prep = await post("mint/prepare", { wallet_address: account });
        if (!prep.ok) throw new Error(prep.error || "Could not prepare the mint.");
        const current = await window.ethereum.request({ method: "eth_chainId" });
        if (current.toLowerCase() !== prep.chain.id_hex.toLowerCase()) {
          await window.ethereum.request({ method: "wallet_switchEthereumChain", params: [{ chainId: prep.chain.id_hex }] });
        }
        const hash = await window.ethereum.request({ method: "eth_sendTransaction", params: [prep.tx] });
        const sub = await post("mint/submit", { tx_hash: hash });
        if (!sub.ok) throw new Error(sub.error || "The server could not record the transaction.");
        window.location.reload();
      } catch (e) {
        showError(walletError(e));
        sendBtn.disabled = false;
      }
    });
  }

  if (checkBtn) {
    checkBtn.addEventListener("click", async () => { showMessage("Checking..."); await verify(); });
  }
})();
