// Runs in <head> before the page paints, so the chosen theme never flashes. External (not inline) because the CSP forbids inline scripts.
// The preference lives in this browser's localStorage only (never sent to the server). With none saved the site opens in its
// dark "Vault" look; the header switch (effects.js) changes it.
(function () {
  var root = document.documentElement;
  var theme = null;
  try { theme = window.localStorage.getItem("mintlot-theme"); } catch (e) { /* storage blocked: fall through */ }
  root.setAttribute("data-bs-theme", theme === "light" ? "light" : "dark");
})();
