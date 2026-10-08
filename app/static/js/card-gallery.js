// Card gallery: clicking a thumbnail shows that image in the large frame.
(function () {
  const main = document.getElementById("gallery-main");
  const thumbs = document.getElementById("gallery-thumbs");
  if (!main || !thumbs) return;
  thumbs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-gallery-src]");
    if (!button) return;
    main.src = button.dataset.gallerySrc;
    thumbs.querySelectorAll("[data-gallery-src]").forEach((b) => b.removeAttribute("aria-current"));
    button.setAttribute("aria-current", "true");
  });
})();
