const CACHE_NAME = "regenradar-shell-v2";
const SHELL_FILES = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./manifest.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

const SHELL_PATHS = new Set(
  SHELL_FILES.map((f) => new URL(f, self.registration.scope).pathname)
);

// Network-first fuer die App-Shell: online gibt es IMMER die aktuell
// deployte Version (kein "haengt an altem Cache fest, bis jemand die
// Versionsnummer hochzaehlt"-Problem mehr). Der Cache wird bei jedem
// erfolgreichen Request automatisch aufgefrischt und dient nur noch als
// Fallback fuer offline.
//
// data/radar/* bewusst NICHT ueber den Service-Worker-Cache anfassen -
// die Zeitstempel-URLs waeren sonst ein wachsender, nie aufgeraeumter
// Cache-Eintrag pro jemals gesehenem Radar-Frame. app.js kuemmert sich
// dort selbst um Caching (siehe fetch() mit cache-busting Query-Param).
self.addEventListener("fetch", (event) => {
  const requestUrl = new URL(event.request.url);
  if (requestUrl.origin !== self.location.origin) return;
  if (!SHELL_PATHS.has(requestUrl.pathname)) return;

  event.respondWith(
    fetch(event.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return res;
      })
      .catch(() => caches.match(event.request))
  );
});
