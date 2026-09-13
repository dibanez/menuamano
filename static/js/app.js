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

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.dataset.busy || event.defaultPrevented) return;
  const button = event.submitter || form.querySelector('button[type="submit"], button:not([type])');
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
});

window.addEventListener("pageshow", () => {
  document.querySelectorAll("form.is-busy").forEach((form) => {
    clearTimeout(form.busyTimer);
    form.classList.remove("is-busy");
    form.removeAttribute("aria-busy");
    form.querySelectorAll(".busy-note").forEach((note) => note.remove());
    form.querySelectorAll("button").forEach((button) => {
      const original = busyButtons.get(button);
      if (original) button.replaceChildren(...original);
      button.removeAttribute("aria-disabled");
    });
  });
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
