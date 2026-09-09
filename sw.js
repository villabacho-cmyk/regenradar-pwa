const CACHE_NAME = "regenradar-shell-v1";
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

// App-Shell aus Cache, alles andere (v.a. DWD-Radarkacheln + Leaflet CDN) immer live vom Netz.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isShellFile = url.origin === self.location.origin;

  if (!isShellFile) return; // Radar-Tiles & CDN: nicht anfassen, immer frisch aus dem Netz

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
