// Demo wallet page (development only): the "Mine a block" button.
(function () {
  const btn = document.getElementById("mine-btn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    fetch("/dev-wallet/mine", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content },
      body: JSON.stringify({ blocks: 1 }),
    }).then((r) => r.json()).then((d) => { document.getElementById("mine-out").textContent = "Now at block " + d.block; });
  });
})();
