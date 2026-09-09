// Regenradar: OSM-Basiskarte + vorab gebackene DWD-Radar-Frames.
// Kein Backend im eigentlichen Sinn, keine Werbung, keine API-Keys.
//
// Die Radar-Bilder werden NICHT live beim Laden der Seite vom DWD geholt
// (der DWD-Server braucht ca. 3-4s pro Bild - viel zu langsam fuer den
// Live-Betrieb). Stattdessen holt sie ein GitHub-Actions-Workflow alle
// 10 Minuten im Hintergrund und legt sie unter data/radar/ ab (siehe
// scripts/fetch_radar.py). Der Client hier laedt nur noch die fertigen
// Bilder von GitHub Pages - schnell, weil kein Warten auf DWD mehr.
//
// Fuer einen fluessigen Loop ohne Flackern werden alle Frames vorab geladen
// und ueber zwei uebereinanderliegende Bild-Ebenen (Doppelpufferung)
// angezeigt: das naechste Bild wird erst sichtbar geschaltet, wenn es
// tatsaechlich fertig geladen ist.
//
// Der Loop enthaelt 60 Minuten Vergangenheit UND 120 Minuten Prognose
// (reine Radarecho-Extrapolation vom DWD, kein Modell-Nowcasting) - beim
// Start bzw. nach jedem Refresh springt die Anzeige auf "jetzt"
// (manifest.nowIndex), nicht ans Ende der Prognose.

const MANIFEST_URL = "data/radar/manifest.json";
const PLAY_INTERVAL_MS = 450;
const MANIFEST_POLL_MS = 90 * 1000; // die meisten Frames kommen dank
// zeitstempel-basiertem Cache-Busting eh aus dem Browser-Cache - billig genug
// fuer haeufiges Nachfragen.
const OVERLAY_OPACITY = 0.75;
const ATTRIBUTION = "Radardaten: Deutscher Wetterdienst (Open Data)";

const DEFAULT_CENTER = [52.52, 13.405]; // Berlin, Fallback ohne Geolocation
const DEFAULT_ZOOM = 8;

const statusEl = document.getElementById("status");
const timestampEl = document.getElementById("timestamp");
const sliderEl = document.getElementById("slider");
const playBtn = document.getElementById("playBtn");

function showStatus(text) {
  statusEl.textContent = text;
  statusEl.classList.add("visible");
}

function hideStatus() {
  statusEl.classList.remove("visible");
}

function flashStatus(text, timeoutMs) {
  showStatus(text);
  setTimeout(hideStatus, timeoutMs);
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Verhindert, dass eine haengende Anfrage (z.B. Bild nicht erreichbar) den
// Loop fuer immer bei "Lade Radardaten..." stehen laesst.
function withTimeout(promise, ms) {
  return Promise.race([promise, wait(ms)]);
}

function formatLocal(date) {
  return date.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

function frameUrl(frame) {
  // Zeitstempel als Cache-Buster: jede (Datei, Zeit)-Kombination ist inhaltlich
  // stabil, der Browser darf sie also cachen - nur neue Zeitstempel werden
  // tatsaechlich frisch vom Netz geholt.
  return `${MANIFEST_URL.replace("manifest.json", "")}${frame.file}?t=${encodeURIComponent(frame.time)}`;
}

// Laedt das Bild schon mal offscreen, damit es beim spaeteren Anzeigen aus
// dem Browser-Cache kommt statt live nachgeladen zu werden.
//
// Bewusst KEIN img.decode() hier: das haengt sich in manchen Browser-
// Umgebungen fuer nicht im DOM haengende Images komplett auf (nie
// aufloesend, kein Fehler) - waere schlimmer als das Problem, das es loesen
// sollte. Die eigentliche Flacker-Vermeidung passiert stattdessen ueber die
// Doppelpufferung unten: ein Bild wird erst sichtbar geschaltet, wenn sein
// eigenes load-Event gefeuert hat.
function primeLoad(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve("loaded");
    img.onerror = () => resolve("error");
    img.src = url;
  });
}

const map = L.map("map", {
  zoomControl: true,
  attributionControl: true,
}).setView(DEFAULT_CENTER, DEFAULT_ZOOM);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 12,
  attribution: "&copy; OpenStreetMap-Mitwirkende",
}).addTo(map);

let frames = [];
let currentIndex = 0;
let nowIndex = 0; // Index des letzten Nicht-Vorhersage-Frames ("jetzt")
let isPlaying = false;
let playLoopToken = null;
let manifestToken = 0; // verwirft veraltete refreshFrames-Laeufe

// Doppelpufferung: overlayA/overlayB liegen exakt uebereinander, immer nur
// eine ist sichtbar. "active" zeigt das aktuelle Bild, "standby" bekommt im
// Hintergrund das naechste Bild und wird erst nach dessen load-Event sichtbar.
let overlayA = null;
let overlayB = null;
let activeOverlay = null;
let standbyOverlay = null;

function ensureOverlays(bounds) {
  overlayA = L.imageOverlay("", bounds, {
    opacity: OVERLAY_OPACITY,
    interactive: false,
    attribution: ATTRIBUTION,
  }).addTo(map);
  overlayB = L.imageOverlay("", bounds, {
    opacity: 0,
    interactive: false,
  }).addTo(map);
  activeOverlay = overlayA;
  standbyOverlay = overlayB;
}

function setOverlayImage(overlay, url) {
  return withTimeout(
    new Promise((resolve) => {
      overlay.once("load", resolve);
      overlay.once("error", resolve);
      overlay.setUrl(url);
    }),
    3000
  );
}

async function renderFrame(index) {
  currentIndex = index;
  const frame = frames[index];
  if (!frame) return;
  sliderEl.value = String(index);
  timestampEl.textContent =
    formatLocal(new Date(frame.time)) + " Uhr" + (frame.isForecast ? " · Prognose" : "");

  if (!standbyOverlay) return;
  await setOverlayImage(standbyOverlay, frameUrl(frame));
  standbyOverlay.setOpacity(OVERLAY_OPACITY);
  activeOverlay.setOpacity(0);
  const tmp = activeOverlay;
  activeOverlay = standbyOverlay;
  standbyOverlay = tmp;
}

async function refreshFrames() {
  const myToken = ++manifestToken;
  let manifest;
  try {
    const res = await fetch(MANIFEST_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    manifest = await res.json();
  } catch (e) {
    flashStatus("Radar-Daten gerade nicht erreichbar", 3000);
    return;
  }
  if (myToken !== manifestToken) return;

  if (!overlayA) {
    const bounds = L.latLngBounds(
      [manifest.bbox.south, manifest.bbox.west],
      [manifest.bbox.north, manifest.bbox.east]
    );
    ensureOverlays(bounds);
  }

  // Beim allerersten Laden sowie wenn zuvor am "Jetzt"-Frame oder in der
  // Prognose gestanden wurde, nach dem Refresh wieder dort einsteigen -
  // sonst bleibt die aktuelle Position (z.B. beim manuellen Durchscrubben
  // der Vergangenheit) erhalten.
  const wasAtNow = frames.length === 0 || currentIndex >= nowIndex;
  frames = manifest.frames;
  nowIndex = manifest.nowIndex;
  sliderEl.max = String(frames.length - 1);

  stopPlaying();
  playBtn.disabled = true;
  showStatus(`Lade Radardaten… 0/${frames.length}`);

  let loaded = 0;
  await Promise.all(
    frames.map(async (frame) => {
      await withTimeout(primeLoad(frameUrl(frame)), 8000);
      loaded++;
      if (myToken === manifestToken) showStatus(`Lade Radardaten… ${loaded}/${frames.length}`);
    })
  );
  if (myToken !== manifestToken) return;

  hideStatus();
  playBtn.disabled = false;
  await renderFrame(wasAtNow ? nowIndex : Math.min(currentIndex, frames.length - 1));
}

function stopPlaying() {
  isPlaying = false;
  playBtn.textContent = "▶";
  playLoopToken = null;
}

function startPlaying() {
  isPlaying = true;
  playBtn.textContent = "❚❚";
  const myLoopToken = {};
  playLoopToken = myLoopToken;

  (async function loop() {
    while (playLoopToken === myLoopToken) {
      await wait(PLAY_INTERVAL_MS);
      if (playLoopToken !== myLoopToken) break;
      await renderFrame((currentIndex + 1) % frames.length);
    }
  })();
}

playBtn.addEventListener("click", () => {
  if (isPlaying) stopPlaying();
  else startPlaying();
});

sliderEl.addEventListener("input", () => {
  stopPlaying();
  renderFrame(Number(sliderEl.value));
});

refreshFrames();
setInterval(refreshFrames, MANIFEST_POLL_MS);

if ("geolocation" in navigator) {
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const latlng = [pos.coords.latitude, pos.coords.longitude];
      map.setView(latlng, DEFAULT_ZOOM);
      // Kreis statt Leaflet-Standardmarker: kein Icon-Asset noetig (der
      // Standard-Marker bricht oft, wenn Leaflet nur per CDN-Script
      // eingebunden ist, ohne die zugehoerigen Bild-Pfade).
      L.circleMarker(latlng, {
        radius: 7,
        color: "#fff",
        weight: 2,
        fillColor: "#5ac8ff", // = --accent aus style.css
        fillOpacity: 1,
      }).addTo(map);
    },
    () => {
      flashStatus("Standort nicht verfügbar – zeige Berlin", 3000);
    },
    { timeout: 5000 }
  );
}
