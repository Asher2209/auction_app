// Small site-wide behaviours, driven by data attributes so no inline scripts or handlers are needed
// (the Content-Security-Policy forbids them).
//   <form data-confirm="Delete this?">   asks before submitting
//   <select data-autosubmit>             submits its form when changed
document.addEventListener("submit", (e) => {
  const form = e.target;
  if (form instanceof HTMLFormElement && form.dataset.confirm && !window.confirm(form.dataset.confirm)) e.preventDefault();
}, true);

document.addEventListener("change", (e) => {
  const el = e.target;
  if (el instanceof HTMLSelectElement && el.hasAttribute("data-autosubmit") && el.form) el.form.submit();
});
