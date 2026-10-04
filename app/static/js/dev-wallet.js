// DEVELOPMENT ONLY: a stand-in for MetaMask, loaded only when LOCAL_CHAIN=1 and no real wallet exists.
// It implements just enough of the EIP-1193 provider interface for the payment page and forwards
// signing to the server's in-memory test chain. It is never loaded in a Sepolia deployment.
(function () {
  if (window.ethereum) return; // a real wallet wins
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content;
  const json = (path, opts) => fetch(path, opts).then((r) => r.json().then((d) => (r.ok ? d : Promise.reject(Object.assign(new Error(d.error || "failed"), { code: -32000 })))));
  const post = (path, body) => json(path, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: JSON.stringify(body) });

  window.ethereum = {
    isDevWallet: true,
    request({ method, params }) {
      switch (method) {
        case "eth_requestAccounts":
        case "eth_accounts":
          return json("/dev-wallet/account").then((d) => [d.address]);
        case "eth_chainId":
          return json("/dev-wallet/account").then((d) => d.chain_id);
        case "wallet_switchEthereumChain":
          return Promise.resolve(null); // the demo wallet is always on the local chain
        case "eth_sendTransaction":
          return post("/dev-wallet/send", { tx: params[0] }).then((d) => d.hash); // the server advances the chain
        default:
          return Promise.reject(Object.assign(new Error("Unsupported method: " + method), { code: 4200 }));
      }
    },
  };
})();
