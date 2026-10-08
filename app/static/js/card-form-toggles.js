// Card submission form: show the grading and card-type sections that apply to the card being described.
// Kept in a file because the Content-Security-Policy forbids inline scripts.
document.addEventListener("DOMContentLoaded", function () {
  const setDisplay = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.style.display = value;
  };

  const graded = document.getElementById("is_graded");
  if (graded) {
    const toggleGrading = () => {
      const value = graded.checked ? "grid" : "none";
      setDisplay("grading-fields", value);
      setDisplay("cert-fields", value);
    };
    graded.addEventListener("change", toggleGrading);
    toggleGrading();
  }

  const typeSelect = document.getElementById("card_type_id");
  if (typeSelect) {
    const toggleType = () => {
      const chosen = typeSelect.options[typeSelect.selectedIndex];
      const name = chosen ? chosen.textContent.toLowerCase() : "";
      setDisplay("pokemon-fields", name.includes("pokémon") || name.includes("pokemon") ? "block" : "none");
      setDisplay("football-fields", name.includes("football") || name.includes("soccer") ? "block" : "none");
    };
    typeSelect.addEventListener("change", toggleType);
    toggleType();
  }
});
