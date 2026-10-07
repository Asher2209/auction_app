// Link a wallet by proving control of it: the server issues a one-time message, the wallet signs it
// (personal_sign) and the server recovers the signer. No transaction is sent and no key ever leaves the wallet.
// All text is written with textContent.
(function () {
  const root = document.getElementById("wallet-root");
  const button = document.getElementById("wallet-verify");
  const out = document.getElementById("wallet-error");
  if (!root || !button || !out) return;
  const csrf = (document.querySelector("meta[name=\"csrf-token\"]") || {}).content;
  const say = (msg, isError) => {
    out.textContent = msg || "";
    out.classList.toggle("text-danger", Boolean(isError)); // progress notes stay neutral; only failures are red
  };

  function post(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(body),
    }).then((r) => r.json().catch(() => ({ ok: false, error: "Unexpected server response." })));
  }

  // personal_sign takes the message as hex-encoded UTF-8; the server checks the same bytes
  function toHex(text) {
    return "0x" + Array.from(new TextEncoder().encode(text)).map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  button.addEventListener("click", async () => {
    say("");
    const provider = window.ethereum;
    if (!provider) {
      say("No wallet found. Install MetaMask (or open this page in a browser that has it), then reload.", true);
      return;
    }
    button.disabled = true;
    try {
      const accounts = await provider.request({ method: "eth_requestAccounts" });
      const address = accounts && accounts[0];
      if (!address) throw new Error("The wallet did not share an account.");
      const challenge = await post(root.dataset.challengeUrl, { address });
      if (!challenge.ok) throw new Error(challenge.error || "Could not start the check.");
      say("Check your wallet and sign the message. Signing does not send a transaction.");
      const signature = await provider.request({ method: "personal_sign", params: [toHex(challenge.message), address] });
      const done = await post(root.dataset.verifyUrl, { address, signature });
      if (!done.ok) throw new Error(done.error || "The wallet could not be verified.");
      window.location.reload();
    } catch (e) {
      say(e && e.code === 4001 ? "You cancelled the request in your wallet. Nothing was linked." : (e && e.message) || "The wallet request failed.", true);
    } finally {
      button.disabled = false;
    }
  });
})();
