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

// Forms that wait for the assistant (data-busy): it takes 10 to 20 seconds, so the button shows it is
// working and a note says how long it usually takes. Nobody should think nothing happened.
const busyButtons = new WeakMap();

function showBusy(form, submitter) {
  if (!form.dataset.busy) return;
  const button = submitter || form.querySelector('button[type="submit"], button:not([type])');
  if (!button || form.classList.contains("is-busy")) return;
  busyButtons.set(button, [...button.childNodes].map((node) => node.cloneNode(true)));
  const spinner = document.createElement("span");
  spinner.className = "spinner";
  spinner.setAttribute("aria-hidden", "true");
  const label = document.createElement("span");
  label.textContent = form.dataset.busy;
  button.replaceChildren(spinner, label);
  button.setAttribute("aria-disabled", "true");
  form.classList.add("is-busy");
  form.setAttribute("aria-busy", "true");
  const note = document.createElement("p");
  note.className = "busy-note";
  note.setAttribute("role", "status");
  note.textContent = "El asistente está trabajando: suele tardar entre 10 y 20 segundos.";
  form.append(note);
  form.busyTimer = setTimeout(() => {
    note.textContent = "Está tardando más de lo normal. No cierres la página: en cuanto responda, verás la propuesta.";
  }, 25000);
}

function clearBusy(form) {
  clearTimeout(form.busyTimer);
  form.classList.remove("is-busy");
  form.removeAttribute("aria-busy");
  form.querySelectorAll(".busy-note").forEach((note) => note.remove());
  form.querySelectorAll("button").forEach((button) => {
    const original = busyButtons.get(button);
    if (original) button.replaceChildren(...original);
    button.removeAttribute("aria-disabled");
  });
}

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
  showBusy(form, event.submitter);
});

window.addEventListener("pageshow", () => {
  document.querySelectorAll("form.is-busy").forEach(clearBusy);
});

// Installable web app: the service worker caches static files and an offline page, never pages.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

// «Instalar la app» page: the steps for this device first, and a direct install button where the
// browser offers one (Chrome, Edge, Android). Safari on iOS has no such button, only the steps.
let installPrompt = null;
const installedAsApp = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;

function deviceKind() {
  const ua = navigator.userAgent;
  if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "ios";
  if (/Android/.test(ua)) return "android";
  return "desktop";
}

function setUpInstallPage() {
  const steps = document.querySelector("[data-install-steps]");
  if (!steps) return;
  document.querySelector("[data-install-installed]").hidden = !installedAsApp();
  const mine = steps.querySelector(`[data-os="${deviceKind()}"]`);
  if (mine) {
    steps.prepend(mine);
    mine.classList.add("mine");
    mine.querySelector("[data-os-mine]").hidden = false;
  }
  document.querySelector("[data-install-now]").hidden = !installPrompt || installedAsApp();
}

// Other pages (the landing): a direct «Instalar» button where the browser offers it; the link to
// the steps stays, and stops being the main button then.
function showDirectInstall() {
  const available = Boolean(installPrompt) && !installedAsApp();
  document.querySelectorAll("[data-install-direct]").forEach((button) => { button.hidden = !available; });
  document.querySelectorAll("[data-install-guide]").forEach((link) => link.classList.toggle("primary", !available));
}

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();  // keep it for our own button
  installPrompt = event;
  setUpInstallPage();
  showDirectInstall();
});

window.addEventListener("appinstalled", () => {
  installPrompt = null;
  setUpInstallPage();
  showDirectInstall();
});

document.addEventListener("click", async (event) => {
  if (!event.target.closest("[data-install-button]") || !installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  setUpInstallPage();
  showDirectInstall();
});

document.addEventListener("DOMContentLoaded", setUpInstallPage);

// Shopping list on this device. The last list opened is kept in the browser, so it can be read and
// ticked in the shop without connection; ticks made offline are sent when the connection returns.
// It belongs to whoever opened it: it is dropped as soon as another person, or nobody, is signed in.
const SHOPPING_KEY = "menuamano:shopping";
const QUEUE_KEY = "menuamano:shopping-queue";

const store = {
  get(key) { try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; } },
  drop(key) { try { localStorage.removeItem(key); } catch {} },
};

function csrfToken() {
  try { return JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRFToken"] || ""; } catch { return ""; }
}

function forgetOtherPeoplesList() {
  const user = document.body.dataset.user || "";
  const saved = store.get(SHOPPING_KEY);
  const queue = store.get(QUEUE_KEY);
  if ((saved && saved.user !== user) || (queue && queue.user !== user)) {
    store.drop(SHOPPING_KEY);
    store.drop(QUEUE_KEY);
  }
}

// Sends the ticks made offline. Returns how many were saved.
async function syncShoppingQueue() {
  const queue = store.get(QUEUE_KEY);
  const token = csrfToken();
  if (!queue || !navigator.onLine || !token) return 0;
  let sent = 0;
  for (const [id, change] of Object.entries(queue.items || {})) {
    let response;
    try {
      response = await fetch(change.url, {
        method: "POST", credentials: "same-origin", redirect: "manual",
        headers: { "X-CSRFToken": token, "Content-Type": "application/x-www-form-urlencoded" },
        body: `done=${change.done ? 1 : 0}`,
      });
    } catch { break; }  // still offline: keep the rest for later
    if (response.type === "opaqueredirect") break;  // signed out: keep them until signed in again
    if (response.ok) sent += 1;
    // Any other answer is final (the item is gone, or it can no longer be edited).
    delete queue.items[id];
  }
  if (Object.keys(queue.items || {}).length) store.set(QUEUE_KEY, queue); else store.drop(QUEUE_KEY);
  return sent;
}

// The list of this page with the ticks as they are now on screen.
function currentShoppingList() {
  const data = document.getElementById("shopping-data");
  if (!data) return null;
  const list = JSON.parse(data.textContent);
  for (const group of list.groups) {
    for (const item of group.items) {
      const row = document.getElementById(`item-${item.id}`);
      if (row) item.done = row.classList.contains("done");
    }
  }
  return list;
}

function shoppingText(list) {
  const lines = [`Lista de la compra: ${list.title}`];
  for (const group of list.groups) {
    const pending = group.items.filter((item) => !item.done);
    if (!pending.length) continue;
    lines.push("", group.label);
    for (const item of pending) lines.push(`• ${item.name}${item.amount ? `: ${item.amount}` : ""}`);
  }
  return lines.join("\n");
}

async function setUpShoppingList() {
  const list = currentShoppingList();
  if (!list) return;
  if (await syncShoppingQueue()) {
    window.location.reload();  // show what was ticked offline
    return;
  }
  const saved = document.querySelector("[data-offline-saved]");
  if (store.set(SHOPPING_KEY, list) && saved) saved.hidden = false;
  const share = document.querySelector("[data-share-list]");
  if (share && (navigator.share || navigator.clipboard)) share.hidden = false;
}

document.addEventListener("DOMContentLoaded", () => {
  if (document.body.hasAttribute("data-offline")) {
    renderOfflineList();
    return;
  }
  forgetOtherPeoplesList();
  if (document.getElementById("shopping-data")) setUpShoppingList();
  else syncShoppingQueue();
});

window.addEventListener("online", () => {
  if (!document.body.hasAttribute("data-offline")) syncShoppingQueue();
});

// Ticks made online (HTMX) keep the saved copy up to date.
document.addEventListener("htmx:afterSettle", () => {
  const list = currentShoppingList();
  const saved = store.get(SHOPPING_KEY);
  if (list && saved && saved.id === list.id) store.set(SHOPPING_KEY, list);
});

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-share-list]");
  if (!button) return;
  const list = currentShoppingList();
  if (!list) return;
  const text = shoppingText(list);
  if (navigator.share) {
    try {
      await navigator.share({ title: `Lista de la compra: ${list.title}`, text });
      return;
    } catch (error) {
      if (error.name === "AbortError") return;  // closed by the person
    }
  }
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Lista copiada";
  } catch {
    button.textContent = "No se ha podido copiar";
  }
});

// Offline page: the saved list, drawn with DOM methods only (its texts come from the household).
function renderOfflineList() {
  const section = document.querySelector("[data-offline-list]");
  const list = store.get(SHOPPING_KEY);
  if (!section || !list || !list.groups || !list.groups.length) return;
  const savedAt = new Date(list.saved_at).toLocaleString("es-ES", {
    day: "numeric", month: "long", hour: "2-digit", minute: "2-digit",
  });
  section.querySelector("[data-offline-lead]").textContent =
    `Tu última lista de la compra, ${list.title}, guardada el ${savedAt}.` +
    (list.can_edit ? " Lo que marques se guardará cuando vuelva la conexión." : "");
  const container = section.querySelector("[data-offline-groups]");
  container.replaceChildren();
  for (const group of list.groups) {
    const block = document.createElement("section");
    block.className = "shop-group";
    const title = document.createElement("h2");
    title.textContent = group.label;
    const items = document.createElement("ul");
    items.className = "list";
    for (const item of group.items) items.append(offlineItem(list, item));
    block.append(title, items);
    container.append(block);
  }
  document.querySelector("[data-offline-empty]").hidden = true;
  section.hidden = false;
}

function offlineItem(list, item) {
  const row = document.createElement("li");
  row.className = `shop-item${item.done ? " done" : ""}`;
  const tick = document.createElement(list.can_edit ? "button" : "span");
  tick.className = `tick${item.done ? " on" : ""}`;
  tick.textContent = "✓";
  if (list.can_edit) {
    tick.type = "button";
    tick.setAttribute("aria-pressed", String(item.done));
    tick.setAttribute("aria-label", `${item.done ? "Desmarcar" : "Marcar comprado"}: ${item.name}`);
    tick.addEventListener("click", () => toggleOffline(list, item, row, tick));
  } else {
    tick.setAttribute("aria-hidden", "true");
  }
  const text = document.createElement("div");
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = item.name;
  text.append(name);
  if (item.amount) {
    const amount = document.createElement("div");
    amount.className = "amounts";
    amount.textContent = item.amount;
    text.append(amount);
  }
  row.append(tick, text);
  return row;
}

// Reminders page: this device subscribes to the server's notifications (web push).
function vapidKeyBytes(value) {
  const base64 = (value + "=".repeat((4 - (value.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
}

async function postJSON(url, data) {
  return fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
    body: JSON.stringify(data),
  });
}

async function setUpPush() {
  const box = document.querySelector("[data-push]");
  if (!box) return;
  const status = box.querySelector("[data-push-status]");
  const enable = box.querySelector("[data-push-enable]");
  const disable = box.querySelector("[data-push-disable]");
  if (!("serviceWorker" in navigator && "PushManager" in window && "Notification" in window)) {
    const ios = deviceKind() === "ios" && !installedAsApp();
    box.querySelector("[data-push-ios]").hidden = !ios;
    status.textContent = ios ? "Instala la app para recibir avisos en este dispositivo." : "Este navegador no puede recibir avisos.";
    return;
  }
  const registration = await navigator.serviceWorker.ready;
  const current = await registration.pushManager.getSubscription();
  if (Notification.permission === "denied") {
    status.textContent = "Has bloqueado los avisos de menuamano: permítelos en los ajustes del navegador.";
    return;
  }
  status.textContent = current ? "Los avisos están activados en este dispositivo." : "Los avisos están desactivados en este dispositivo.";
  enable.hidden = Boolean(current);
  disable.hidden = !current;

  enable.addEventListener("click", async () => {
    enable.disabled = true;
    try {
      if (await Notification.requestPermission() !== "granted") {
        status.textContent = "Sin permiso no se pueden enviar avisos. Puedes darlo en los ajustes del navegador.";
        return;
      }
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true, applicationServerKey: vapidKeyBytes(box.dataset.publicKey),
      });
      const response = await postJSON(box.dataset.subscribeUrl, subscription.toJSON());
      if (!response.ok) throw new Error(String(response.status));
      window.location.reload();
    } catch {
      status.textContent = "No se han podido activar los avisos. Inténtalo de nuevo.";
    } finally {
      enable.disabled = false;
    }
  });

  disable.addEventListener("click", async () => {
    const subscription = await registration.pushManager.getSubscription();
    if (subscription) {
      await postJSON(box.dataset.unsubscribeUrl, { endpoint: subscription.endpoint });
      await subscription.unsubscribe();
    }
    window.location.reload();
  });
}

document.addEventListener("DOMContentLoaded", setUpPush);

// Label review: read a product's barcode with the camera where the browser can (Chrome on Android).
// Elsewhere (Safari on iPhone) the button stays hidden and the code is typed.
function setUpBarcodeScanner() {
  const button = document.querySelector("[data-barcode-scan]");
  if (!button || !("BarcodeDetector" in window) || !navigator.mediaDevices?.getUserMedia) return;
  const box = document.querySelector("[data-barcode-scanner]");
  const video = box.querySelector("video");
  const status = box.querySelector("[data-barcode-status]");
  const form = document.querySelector("[data-barcode-form]");
  let stream = null;
  let active = false;
  button.hidden = false;

  const stop = () => {
    active = false;
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    box.hidden = true;
  };
  box.querySelector("[data-barcode-stop]").addEventListener("click", stop);

  button.addEventListener("click", async () => {
    let detector;
    try {
      detector = new BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e"] });
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    } catch {
      box.hidden = false;
      status.textContent = "No se puede usar la cámara: escribe el código a mano.";
      return;
    }
    video.srcObject = stream;
    box.hidden = false;
    active = true;
    await video.play();
    const scan = async () => {
      if (!active) return;
      try {
        const [code] = await detector.detect(video);
        if (code && /^\d{8,14}$/.test(code.rawValue)) {
          stop();
          form.querySelector('[name="codigo"]').value = code.rawValue;
          form.submit();
          return;
        }
      } catch {}
      setTimeout(scan, 250);
    };
    scan();
  });
}

document.addEventListener("DOMContentLoaded", setUpBarcodeScanner);

function toggleOffline(list, item, row, tick) {
  item.done = !item.done;
  store.set(SHOPPING_KEY, list);
  const queue = store.get(QUEUE_KEY) || { user: list.user, items: {} };
  queue.items[item.id] = { done: item.done, url: item.state_url };
  store.set(QUEUE_KEY, queue);
  row.classList.toggle("done", item.done);
  tick.classList.toggle("on", item.done);
  tick.setAttribute("aria-pressed", String(item.done));
  tick.setAttribute("aria-label", `${item.done ? "Desmarcar" : "Marcar comprado"}: ${item.name}`);
}

// Assistant with each person's own AI key (free plan). The key is kept only in this browser, per
// account, and sent straight to the provider: menuamano's server never receives it. A request takes
// two steps: the server prepares the data (anonymised, as for its own provider), this browser asks
// the provider, and the form is then sent as usual with the answer, which the server validates.
const AI_KEY_PREFIX = "menuamano:ai-key:";
const AI_TIMEOUT_MS = 180000;
const AI_INCOMPLETE = "La respuesta de la IA llegó incompleta. Prueba con una petición más acotada o con otro modelo.";
const AI_REFUSED = "La IA no ha querido responder a esta petición.";

class AIFailure extends Error {}

function providerErrorMessage(status, body) {
  const detail = String(body?.error?.message || body?.message || "").slice(0, 200);
  if (status === 401 || status === 403) return "Tu proveedor de IA no acepta la clave o no te deja usar ese modelo.";
  if (status === 404) return "Tu proveedor de IA no encuentra ese modelo. Revisa el nombre.";
  if (status === 429) return "Tu cuenta del proveedor de IA ha llegado a su límite o no tiene saldo. Prueba más tarde o revisa tu cuenta.";
  if (status === 400 || status === 422) return `Tu proveedor de IA ha rechazado la petición${detail ? `: ${detail}` : ". Prueba con otro modelo."}`;
  return "Tu proveedor de IA ha devuelto un error. Inténtalo de nuevo más tarde.";
}

async function providerFetch(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), AI_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(url, { ...options, signal: controller.signal, credentials: "omit", referrerPolicy: "no-referrer" });
  } catch (error) {
    throw new AIFailure(error.name === "AbortError"
      ? "La IA ha tardado demasiado en responder. Inténtalo de nuevo más tarde."
      : "No se ha podido conectar con tu proveedor de IA. Revisa la conexión; si sigue fallando, puede que ese proveedor no admita llamadas desde el navegador.");
  } finally {
    clearTimeout(timer);
  }
  let body = null;
  try { body = await response.json(); } catch {}
  if (!response.ok) throw new AIFailure(providerErrorMessage(response.status, body));
  return body || {};
}

const bearer = (settings) => ({ Authorization: `Bearer ${settings.key}` });
const jsonHeaders = (extra) => ({ "Content-Type": "application/json", ...extra });

// Providers with an OpenAI-style Chat Completions API and structured outputs.
function chatCompletions(base) {
  return {
    async ask(settings, job) {
      const data = await providerFetch(`${base}/chat/completions`, {
        method: "POST",
        headers: jsonHeaders(bearer(settings)),
        body: JSON.stringify({
          model: settings.model,
          max_tokens: job.max_output_tokens,
          messages: [{ role: "system", content: job.instructions }, { role: "user", content: job.input }],
          response_format: { type: "json_schema", json_schema: { name: job.schema_name, schema: job.schema, strict: true } },
        }),
      });
      const choice = (data.choices || [])[0];
      if (choice?.finish_reason === "length") throw new AIFailure(AI_INCOMPLETE);
      if (choice?.message?.refusal) throw new AIFailure(AI_REFUSED);
      let text = choice?.message?.content || "";
      if (Array.isArray(text)) text = text.map((part) => part.text || "").join("");
      return { text, model: data.model, inputTokens: data.usage?.prompt_tokens, outputTokens: data.usage?.completion_tokens };
    },
    async check(settings) {
      const data = await providerFetch(`${base}/models`, { headers: bearer(settings) });
      return (data.data || []).map((model) => model.id);
    },
  };
}

const anthropicHeaders = (settings) => ({
  "x-api-key": settings.key,
  "anthropic-version": "2023-06-01",
  "anthropic-dangerous-direct-browser-access": "true",
});

const AI_PROVIDERS = {
  openai: {
    async ask(settings, job) {
      const data = await providerFetch("https://api.openai.com/v1/responses", {
        method: "POST",
        headers: jsonHeaders(bearer(settings)),
        body: JSON.stringify({
          model: settings.model,
          instructions: job.instructions,
          input: [{ role: "user", content: job.input }],
          text: { format: { type: "json_schema", name: job.schema_name, schema: job.schema, strict: true } },
          max_output_tokens: job.max_output_tokens,
          store: false,
        }),
      });
      if (data.status === "incomplete") throw new AIFailure(AI_INCOMPLETE);
      let text = "";
      for (const item of data.output || []) {
        if (item.type !== "message") continue;
        for (const part of item.content || []) {
          if (part.type === "refusal") throw new AIFailure(AI_REFUSED);
          if (part.type === "output_text") text += part.text;
        }
      }
      return { text, model: data.model, inputTokens: data.usage?.input_tokens, outputTokens: data.usage?.output_tokens };
    },
    async check(settings) {
      const data = await providerFetch("https://api.openai.com/v1/models", { headers: bearer(settings) });
      return (data.data || []).map((model) => model.id);
    },
  },
  anthropic: {
    // A forced tool call whose input follows the schema: Claude's way to answer with structured data.
    async ask(settings, job) {
      const data = await providerFetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: jsonHeaders(anthropicHeaders(settings)),
        body: JSON.stringify({
          model: settings.model,
          max_tokens: job.max_output_tokens,
          system: job.instructions,
          messages: [{ role: "user", content: job.input }],
          tools: [{ name: job.schema_name, description: "La respuesta del asistente.", input_schema: job.schema }],
          tool_choice: { type: "tool", name: job.schema_name },
        }),
      });
      if (data.stop_reason === "max_tokens") throw new AIFailure(AI_INCOMPLETE);
      if (data.stop_reason === "refusal") throw new AIFailure(AI_REFUSED);
      const call = (data.content || []).find((block) => block.type === "tool_use");
      return {
        text: call ? JSON.stringify(call.input) : "", model: data.model,
        inputTokens: data.usage?.input_tokens, outputTokens: data.usage?.output_tokens,
      };
    },
    async check(settings) {
      const data = await providerFetch("https://api.anthropic.com/v1/models?limit=1000", { headers: anthropicHeaders(settings) });
      return (data.data || []).map((model) => model.id);
    },
  },
  gemini: {
    async ask(settings, job) {
      const model = settings.model.replace(/^models\//, "");
      const data = await providerFetch(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`, {
        method: "POST",
        headers: jsonHeaders({ "x-goog-api-key": settings.key }),
        body: JSON.stringify({
          systemInstruction: { parts: [{ text: job.instructions }] },
          contents: [{ role: "user", parts: [{ text: job.input }] }],
          generationConfig: { responseMimeType: "application/json", responseJsonSchema: job.schema, maxOutputTokens: job.max_output_tokens },
        }),
      });
      const candidate = (data.candidates || [])[0];
      if (!candidate) throw new AIFailure(AI_REFUSED);
      if (candidate.finishReason === "MAX_TOKENS") throw new AIFailure(AI_INCOMPLETE);
      if (["SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"].includes(candidate.finishReason)) throw new AIFailure(AI_REFUSED);
      const text = (candidate.content?.parts || []).filter((part) => !part.thought).map((part) => part.text || "").join("");
      return {
        text, model: data.modelVersion || model,
        inputTokens: data.usageMetadata?.promptTokenCount, outputTokens: data.usageMetadata?.candidatesTokenCount,
      };
    },
    async check(settings) {
      const data = await providerFetch("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", {
        headers: { "x-goog-api-key": settings.key },
      });
      return (data.models || []).map((model) => model.name.replace(/^models\//, ""));
    },
  },
  mistral: chatCompletions("https://api.mistral.ai/v1"),
  openrouter: {
    ask: chatCompletions("https://openrouter.ai/api/v1").ask,
    async check(settings) {
      await providerFetch("https://openrouter.ai/api/v1/key", { headers: bearer(settings) });  // its model list is public
      const data = await providerFetch("https://openrouter.ai/api/v1/models");
      return (data.data || []).map((model) => model.id);
    },
  },
};

const aiKeyName = () => AI_KEY_PREFIX + (document.body.dataset.user || "");

function loadAIKey() {
  const saved = store.get(aiKeyName());
  return saved && AI_PROVIDERS[saved.provider] && saved.model && saved.key ? saved : null;
}

// Some models wrap the JSON in a Markdown code block.
const cleanJSON = (text) => String(text || "").trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");

async function prepareAIRequest(form) {
  let response;
  try {
    response = await fetch(form.getAttribute("hx-post") || form.action, {
      method: "POST", credentials: "same-origin",
      headers: { "X-AI-Stage": "prepare", "X-CSRFToken": csrfToken() },
      body: new FormData(form),
    });
  } catch {
    throw new AIFailure("No se ha podido conectar con menuamano. Revisa la conexión.");
  }
  let data = null;
  try { data = await response.json(); } catch {}
  if (data?.error) throw new AIFailure(data.error);
  if (!response.ok || !data?.token) throw new AIFailure("No se ha podido preparar la petición. Recarga la página e inténtalo de nuevo.");
  return data;
}

function clearAIAnswer(form) {
  form.querySelectorAll("input.ai-answer").forEach((input) => input.remove());
  delete form.dataset.aiReady;
}

function attachAIAnswer(form, fields) {
  clearAIAnswer(form);
  for (const [name, value] of Object.entries(fields)) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.className = "ai-answer";
    input.name = name;
    input.value = value ?? "";
    form.append(input);
  }
}

function showAIError(form, message) {
  form.aiError?.remove();
  const note = document.createElement("div");
  note.className = "notice conflict ai-error";
  note.setAttribute("role", "alert");
  const link = document.createElement("a");
  link.href = document.body.dataset.aiKeyUrl || "#";
  link.textContent = "IA en este dispositivo";
  note.append(`${message} `, link);
  form.after(note);
  form.aiError = note;
}

// Capture phase: this runs before HTMX and the other submit handlers, and holds the form back until
// the provider has answered. Then the form is sent again, as usual, with the answer attached.
document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.dataset.ai !== "device") return;
  if (form.dataset.aiReady === "1") {
    delete form.dataset.aiReady;
    return;
  }
  event.preventDefault();
  event.stopImmediatePropagation();
  if (form.classList.contains("ai-working")) return;
  form.aiError?.remove();
  clearAIAnswer(form);
  const settings = loadAIKey();
  if (!settings) {
    showAIError(form, "Para usar el asistente con el plan gratuito, guarda antes tu clave de IA en este dispositivo.");
    return;
  }
  const submitter = event.submitter;
  form.classList.add("ai-working", "htmx-request");
  showBusy(form, submitter);
  try {
    const job = await prepareAIRequest(form);
    const started = performance.now();
    const answer = await AI_PROVIDERS[settings.provider].ask(settings, job);
    const output = cleanJSON(answer.text);
    if (!output) throw new AIFailure("La IA no ha devuelto una propuesta válida. No se ha cambiado nada.");
    attachAIAnswer(form, {
      ai_token: job.token, ai_output: output, ai_provider: settings.provider, ai_model: answer.model || settings.model,
      ai_input_tokens: answer.inputTokens, ai_output_tokens: answer.outputTokens,
      ai_latency_ms: Math.round(performance.now() - started),
    });
  } catch (error) {
    form.classList.remove("ai-working", "htmx-request");
    clearBusy(form);
    showAIError(form, error instanceof AIFailure ? error.message : "No se ha podido completar la petición al asistente. Inténtalo de nuevo.");
    return;
  }
  form.classList.remove("ai-working", "htmx-request");
  form.dataset.aiReady = "1";
  form.requestSubmit(submitter?.form === form ? submitter : undefined);
}, true);

document.addEventListener("htmx:afterRequest", (event) => {
  const form = event.detail.elt;
  if (form instanceof HTMLFormElement && form.dataset.ai === "device") clearAIAnswer(form);
});

window.addEventListener("pageshow", () => {
  document.querySelectorAll('form[data-ai="device"]').forEach((form) => {
    form.classList.remove("ai-working", "htmx-request");
    clearAIAnswer(form);
  });
});

// «IA en este dispositivo»: the form has no action and its fields no names, so nothing is ever sent.
function setUpDeviceKey() {
  const form = document.querySelector("[data-ai-key-form]");
  if (!form) return;
  const catalogue = JSON.parse(document.getElementById("ai-providers").textContent);
  const provider = form.querySelector("#ai-provider");
  const model = form.querySelector("#ai-model");
  const key = form.querySelector("#ai-key");
  const suggestions = document.getElementById("ai-models");
  const keysLink = form.querySelector("[data-ai-keys-link]");
  const status = form.querySelector("[data-ai-key-status]");
  const saved = document.querySelector("[data-ai-key-saved]");
  const forget = form.querySelector("[data-ai-key-forget]");

  const say = (text, kind = "") => {
    status.textContent = text;
    status.className = `notice ${kind}`;
    status.hidden = !text;
  };

  function showProvider() {
    const info = catalogue[provider.value];
    suggestions.replaceChildren(...info.models.map((name) => Object.assign(document.createElement("option"), { value: name })));
    model.placeholder = info.models[0] || "El nombre del modelo en tu proveedor";
    keysLink.href = info.keys_url;
    keysLink.textContent = new URL(info.keys_url).host;
    const current = loadAIKey();
    key.required = !current || current.provider !== provider.value;
    key.placeholder = key.required ? "" : "Déjala vacía para mantener la guardada";
  }

  function showSaved() {
    const current = loadAIKey();
    saved.hidden = !current;
    forget.hidden = !current;
    if (current) {
      saved.textContent = `Guardada en este dispositivo: ${catalogue[current.provider].label}, modelo ${current.model}, clave terminada en ${current.key.slice(-4)}.`;
    }
    showProvider();
  }

  // What the form says now; an empty key keeps the saved one of the same provider.
  function formSettings() {
    const current = loadAIKey();
    const typed = key.value.trim();
    return {
      provider: provider.value,
      model: model.value.trim() || catalogue[provider.value].models[0] || "",
      key: typed || (current && current.provider === provider.value ? current.key : ""),
    };
  }

  function problem(settings) {
    if (!settings.model) return "Escribe el modelo que quieres usar.";
    if (!settings.key) return "Pega la clave de la API de tu proveedor.";
    return "";
  }

  const current = loadAIKey();
  if (current) {
    provider.value = current.provider;
    model.value = current.model;
  }
  showSaved();
  provider.addEventListener("change", () => {
    model.value = "";
    showProvider();
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const settings = formSettings();
    const error = problem(settings);
    if (error) return say(error, "conflict");
    if (!store.set(aiKeyName(), settings)) {
      return say("Este navegador no deja guardar datos (quizá estás en una ventana privada). Sin guardar la clave no se puede usar el asistente.", "conflict");
    }
    key.value = "";
    model.value = settings.model;
    showSaved();
    say("Clave guardada en este dispositivo.", "ok");
  });

  form.querySelector("[data-ai-key-test]").addEventListener("click", async () => {
    const settings = formSettings();
    const error = problem(settings);
    if (error) return say(error, "conflict");
    say("Comprobando la clave con tu proveedor…");
    try {
      const models = await AI_PROVIDERS[settings.provider].check(settings);
      if (!models.length || models.includes(settings.model)) {
        say("La clave funciona.", "ok");
      } else {
        say(`La clave funciona, pero tu cuenta no muestra el modelo «${settings.model}». Revisa el nombre.`, "unknown");
      }
    } catch (failure) {
      say(failure instanceof AIFailure ? failure.message : "No se ha podido comprobar la clave.", "conflict");
    }
  });

  forget.addEventListener("click", () => {
    store.drop(aiKeyName());
    key.value = "";
    showSaved();
    say("Clave borrada de este dispositivo.", "ok");
  });
}

document.addEventListener("DOMContentLoaded", setUpDeviceKey);
