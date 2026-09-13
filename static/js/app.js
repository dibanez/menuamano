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

// Searchable checkbox lists: typing hides the entries that do not match (checked ones included,
// they stay selected and are still submitted).
document.addEventListener("input", (event) => {
  const input = event.target.closest("[data-filter-list]");
  if (!input) return;
  const list = input.closest("fieldset")?.querySelector(".checklist");
  if (!list) return;
  const term = normalizeText(input.value.trim());
  for (const label of list.querySelectorAll("label")) {
    label.hidden = Boolean(term) && !normalizeText(label.textContent).includes(term);
  }
});

// Cookie consent for Google Tag Manager (Consent Mode v2). The choice is kept in this browser.
const CONSENT_KEY = "menuamano-consent";
const readConsent = () => { try { return localStorage.getItem(CONSENT_KEY); } catch { return null; } };

document.addEventListener("DOMContentLoaded", () => {
  const banner = document.getElementById("consent-banner");
  if (banner && !readConsent()) banner.hidden = false;
});

document.addEventListener("click", (event) => {
  const reopen = event.target.closest("[data-consent-reopen]");
  const banner = document.getElementById("consent-banner");
  if (reopen && banner) {
    event.preventDefault();
    banner.hidden = false;
    return;
  }
  const button = event.target.closest("[data-consent]");
  if (!button) return;
  const choice = button.dataset.consent;
  try { localStorage.setItem(CONSENT_KEY, choice); } catch {}
  const value = choice === "granted" ? "granted" : "denied";
  if (typeof window.gtag === "function") {
    window.gtag("consent", "update", {
      ad_storage: value, ad_user_data: value, ad_personalization: value, analytics_storage: value,
    });
  }
  if (banner) banner.hidden = true;
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

// Forms are sent once: another tap while the next page loads would repeat the action (a deleted
// item then answers 404, a login fails its CSRF check). HTMX forms manage their own requests.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.method !== "post") return;
  if (form.hasAttribute("hx-post") || form.hasAttribute("hx-get")) return;
  if (form.dataset.submitting === "1") {
    event.preventDefault();
    return;
  }
  if (event.defaultPrevented) return;
  form.dataset.submitting = "1";
  setTimeout(() => { delete form.dataset.submitting; }, 8000);
});

// Back/forward restores the page as it was left: let its forms be sent again.
window.addEventListener("pageshow", () => {
  document.querySelectorAll("form[data-submitting]").forEach((form) => { delete form.dataset.submitting; });
});

// Installable web app: the service worker caches static files and an offline page, never pages.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
