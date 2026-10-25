// The light/dark switch (#theme-toggle in the header). The choice is kept in this browser's localStorage only;
// theme-init.js applies it in <head> before the page paints.
(function () {
  const root = document.documentElement;
  const toggle = document.getElementById("theme-toggle");
  if (!toggle) return;
  const sync = () => {
    const dark = root.getAttribute("data-bs-theme") === "dark";
    toggle.setAttribute("aria-pressed", dark ? "true" : "false");
    toggle.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  };
  sync();
  toggle.addEventListener("click", () => {
    const next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-bs-theme", next);
    try { window.localStorage.setItem("mintlot-theme", next); } catch (e) { /* storage blocked: still switches for this visit */ }
    sync();
  });
})();
