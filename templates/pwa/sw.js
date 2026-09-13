// menuamano service worker. It caches only static files and an offline page: pages carry each
// household's data, so they always come from the network.
const CACHE = "{{ cache_name }}";
const PRECACHE = {{ precache|safe }};
const OFFLINE_URL = {{ offline_url|safe }};
const ICON_URL = {{ icon_url|safe }};

self.addEventListener("install", (event) => {
  // Straight from the server, never from the browser's HTTP cache: a new worker must store current files.
  const fresh = PRECACHE.map((url) => new Request(url, { cache: "reload" }));
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(fresh)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key.startsWith("menuamano-") && key !== CACHE).map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }
  if (url.pathname.startsWith("/static/")) {
    // Hashed names (production) never change content: cache first. Others (development): network first.
    const hashed = /\.[0-9a-f]{12}\.[a-z0-9]+$/.test(url.pathname);
    event.respondWith(hashed ? cacheFirst(request) : networkFirst(request));
  }
});

// Reminders sent by the server (web push). Only same-site links are opened.
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(self.registration.showNotification(data.title || "menuamano", {
    body: data.body || "", icon: ICON_URL, badge: ICON_URL, tag: data.tag || "menuamano", lang: "es",
    data: { url: data.url || "/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin);
  if (url.origin !== self.location.origin) return;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((client) => "focus" in client);
      if (!open) return self.clients.openWindow(url.href);
      return open.focus().then((client) => client.navigate(url.href)).catch(() => self.clients.openWindow(url.href));
    }),
  );
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) (await caches.open(CACHE)).put(request, response.clone());
  return response;
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) (await caches.open(CACHE)).put(request, response.clone());
    return response;
  } catch (error) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw error;
  }
}
