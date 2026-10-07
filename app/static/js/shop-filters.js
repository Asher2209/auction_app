// Shop page: choosing a filter reloads the list with the chosen filters in the address.
// Driven by data attributes because the Content-Security-Policy forbids inline scripts and handlers:
//   <div data-shop-url="/shop">  holds the filters;  <select data-shop-filter="category">  is one of them.
document.addEventListener("change", (e) => {
  const select = e.target;
  if (!(select instanceof HTMLSelectElement) || !select.hasAttribute("data-shop-filter")) return;
  const bar = select.closest("[data-shop-url]");
  if (!bar) return;
  const params = new URLSearchParams();
  bar.querySelectorAll("select[data-shop-filter]").forEach((s) => {
    if (s.value) params.set(s.dataset.shopFilter, s.value);
  });
  const query = params.toString();
  window.location.href = bar.dataset.shopUrl + (query ? "?" + query : "");
});
