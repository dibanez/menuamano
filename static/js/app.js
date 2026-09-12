// Small progressive enhancements. Every flow also works without JavaScript.

// Formset rows: clone the empty form template and bump TOTAL_FORMS.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-add-row]");
  if (!button) return;
  const prefix = button.dataset.addRow;
  const total = document.getElementById(`id_${prefix}-TOTAL_FORMS`);
  const template = document.getElementById(`${prefix}-empty`);
  const container = document.getElementById(`${prefix}-rows`);
  if (!total || !template || !container) return;
  const index = parseInt(total.value, 10);
  const html = template.innerHTML.replace(/__prefix__/g, String(index));
  container.insertAdjacentHTML("beforeend", html);
  total.value = String(index + 1);
  const firstInput = container.lastElementChild?.querySelector("input, select, textarea");
  if (firstInput) firstInput.focus();
});

// Searchable selects: typing narrows the options of the select in the same field and picks the
// first match (hiding options is ignored by some mobile browsers, selecting always works).
const normalizeText = (text) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

document.addEventListener("input", (event) => {
  const input = event.target.closest("[data-filter-select]");
  if (!input) return;
  const select = input.closest(".field")?.querySelector("select");
  if (!select) return;
  const term = normalizeText(input.value.trim());
  let firstMatch = null;
  for (const option of select.options) {
    const match = !term || normalizeText(option.text).includes(term);
    option.hidden = !match && option.value !== "";
    if (match && option.value && !firstMatch) firstMatch = option;
  }
  if (term && firstMatch) select.value = firstMatch.value;
  input.setAttribute("aria-description", firstMatch ? `Seleccionado: ${firstMatch.text}` : "Sin coincidencias");
});

// Copy the value of an input to the clipboard.
document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const input = document.getElementById(button.dataset.copy);
  if (!input) return;
  input.select();
  try {
    await navigator.clipboard.writeText(input.value);
    button.textContent = "Copiado";
  } catch {
    button.textContent = "Selecciónalo y cópialo";
  }
});

// Confirmation for destructive buttons, using a native dialog-free approach:
// buttons with data-confirm are only submitted after a second tap.
document.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-confirm]");
  if (!button) return;
  if (button.dataset.armed === "1") return;
  event.preventDefault();
  button.dataset.armed = "1";
  button.dataset.original = button.textContent;
  button.textContent = button.dataset.confirm;
  setTimeout(() => {
    button.dataset.armed = "0";
    button.textContent = button.dataset.original;
  }, 4000);
});
