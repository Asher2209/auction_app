// Listing form: show the questions that belong to the chosen category and hide the others.
// Fields of hidden sets are disabled so the browser does not send them (the server also ignores any that arrive).
// Without JavaScript every set stays visible and the server only reads the chosen category's answers.
(function () {
  const select = document.getElementById("category_id");
  const sets = document.querySelectorAll("[data-category-set]");
  if (!select || !sets.length) return;

  function show() {
    sets.forEach((set) => {
      const on = set.getAttribute("data-category-set") === select.value;
      set.hidden = !on;
      set.querySelectorAll("input, select, textarea").forEach((el) => { el.disabled = !on; });
    });
  }
  select.addEventListener("change", show);
  show();
})();
