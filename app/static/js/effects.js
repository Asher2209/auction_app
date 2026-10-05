// Visual behaviours, all optional: the site works the same without them.
//   [data-reveal]  fades in when scrolled into view (styles in theme.css, switched on by theme-init.js)
//   [data-beam]    a soft light that follows the cursor over the element
//   #theme-toggle  switches light/dark and remembers the choice in localStorage
(function () {
  const root = document.documentElement;

  // ---- scroll reveal
  const items = document.querySelectorAll("[data-reveal]");
  if (items.length && root.classList.contains("js-reveal")) {
    const seen = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          seen.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
    items.forEach((el) => seen.observe(el));
    // never leave content hidden if the observer is somehow slow
    window.setTimeout(() => items.forEach((el) => el.classList.add("is-visible")), 4000);
  }

  // ---- cursor beam (mouse and pen only, and not when the user prefers less motion)
  const calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!calm) {
    document.querySelectorAll("[data-beam]").forEach((el) => {
      el.addEventListener("pointermove", (e) => {
        if (e.pointerType === "touch") return;
        const r = el.getBoundingClientRect();
        el.style.setProperty("--mx", `${e.clientX - r.left}px`);
        el.style.setProperty("--my", `${e.clientY - r.top}px`);
        el.style.setProperty("--beam", "1");
      });
      el.addEventListener("pointerleave", () => el.style.setProperty("--beam", "0"));
    });
  }

  // ---- theme toggle
  const toggle = document.getElementById("theme-toggle");
  if (toggle) {
    const sync = () => {
      const dark = root.getAttribute("data-bs-theme") === "dark";
      toggle.setAttribute("aria-pressed", dark ? "true" : "false");
      toggle.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    };
    sync();
    toggle.addEventListener("click", () => {
      const next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-bs-theme", next);
      try { window.localStorage.setItem("chainbid-theme", next); } catch (e) { /* storage blocked: still switches for this visit */ }
      sync();
    });
  }
})();
