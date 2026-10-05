// Runs in <head> before the page paints, so the chosen theme never flashes. External (not inline) because the CSP forbids inline scripts.
// The preference lives in this browser's localStorage only (never sent to the server); with none saved, the system setting decides.
(function () {
  var root = document.documentElement;
  var theme = null;
  try { theme = window.localStorage.getItem("chainbid-theme"); } catch (e) { /* storage blocked: fall through */ }
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  root.setAttribute("data-bs-theme", theme);
  // Scroll-reveal hides sections until they are seen, so only switch it on when we can also reveal them.
  if ("IntersectionObserver" in window && !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) {
    root.classList.add("js-reveal");
  }
})();
