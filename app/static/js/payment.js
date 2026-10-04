// While a payment is "processing", poll its status. For crypto payments, show the confirmation count
// as the blockchain confirms it; reload as soon as the payment finishes (succeeds or fails).
(function () {
  const root = document.getElementById("payment-root");
  if (!root || root.dataset.processing !== "true") return;
  const url = `/payments/${root.dataset.auctionId}/status`;
  const timer = setInterval(() => {
    fetch(url, { headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((s) => {
        if (!s.processing) {
          clearInterval(timer);
          window.location.reload();
          return;
        }
        const conf = document.getElementById("conf-count");
        if (conf && typeof s.confirmations === "number") conf.textContent = s.confirmations;
        const note = document.getElementById("crypto-note");
        if (note) note.textContent = s.error || "";
      })
      .catch(() => {});
  }, 3000);
})();
