// menuamano service worker. It caches only static files and an offline page: pages carry each
// household's data, so they always come from the network.
const CACHE = "{{ cache_name }}";
const PRECACHE = {{ precache|safe }};
const OFFLINE_URL = {{ offline_url|safe }};

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
