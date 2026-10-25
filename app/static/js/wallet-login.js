// Sign in with a wallet (EIP-4361): the server issues a one-time sign-in message, the wallet signs it (personal_sign)
// and the server signs in the account that has proven this wallet. No transaction is sent and no key leaves the wallet.
// All text is written with textContent.
(function () {
  const button = document.getElementById("wallet-login");
  const out = document.getElementById("wallet-login-status");
  if (!button || !out) return;
  const csrf = (document.querySelector("meta[name=\"csrf-token\"]") || {}).content;
  const say = (msg, isError) => {
    out.textContent = msg || "";
    out.classList.toggle("text-danger", Boolean(isError));
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
      const challenge = await post(button.dataset.challengeUrl, { address });
      if (!challenge.ok) throw new Error(challenge.error || "Could not start signing in.");
      say("Check your wallet and sign the message. Signing does not send a transaction.");
      const signature = await provider.request({ method: "personal_sign", params: [toHex(challenge.message), address] });
      const done = await post(button.dataset.verifyUrl, { address, signature, next: button.dataset.next || "" });
      if (!done.ok) throw new Error(done.error || "Signing in with the wallet failed.");
      window.location.assign(done.redirect);
    } catch (e) {
      say(e && e.code === 4001 ? "You cancelled the request in your wallet." : (e && e.message) || "The wallet request failed.", true);
      button.disabled = false;
    }
  });
})();
