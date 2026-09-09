// Regenradar: OSM-Basiskarte + DWD-Radar (offene Geodaten, WMS mit Zeit-Dimension).
// Kein Backend, keine Werbung, keine API-Keys.
//
// Wichtig: die einzelnen Zeit-Frames werden VOR dem Abspielen komplett als
// Bild-Blobs vorgeladen (DWD antwortet zu langsam fuer Live-Requests im
// 450ms-Takt). Beim Loop wird dann nur noch zwischen bereits geladenen
// Bildern umgeschaltet, kein Netzwerk-Request pro Frame mehr.

const DWD_WMS_URL = "https://maps.dwd.de/geoserver/dwd/wms";
const DWD_LAYER = "Radar_rv_product_1x1km_ger";

const FRAME_COUNT = 18; // 18 * 5 min = 90 Minuten Loop
const FRAME_STEP_MIN = 5;
const LAG_BUFFER_MIN = 10; // DWD braucht ein paar Minuten bis das neueste Bild verfuegbar ist
const PLAY_INTERVAL_MS = 450;
const PRELOAD_CONCURRENCY = 4;
const MOVE_DEBOUNCE_MS = 300;

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

function buildFrameTimes() {
  const now = new Date();
  const flooredMinutes = Math.floor(now.getUTCMinutes() / FRAME_STEP_MIN) * FRAME_STEP_MIN;
  const latest = new Date(now);
  latest.setUTCMinutes(flooredMinutes, 0, 0);
  latest.setUTCMinutes(latest.getUTCMinutes() - LAG_BUFFER_MIN);

  const result = [];
  for (let i = FRAME_COUNT - 1; i >= 0; i--) {
    result.push(new Date(latest.getTime() - i * FRAME_STEP_MIN * 60 * 1000));
  }
  return result;
}

function formatLocal(date) {
  return date.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

function buildWmsImageUrl(bbox, width, height, timeIso) {
  const params = new URLSearchParams({
    service: "WMS",
    version: "1.3.0",
    request: "GetMap",
    layers: DWD_LAYER,
    styles: "",
    format: "image/png",
    transparent: "true",
    crs: "EPSG:3857",
    bbox: bbox.join(","),
    width: String(width),
    height: String(height),
    time: timeIso,
  });
  return `${DWD_WMS_URL}?${params.toString()}`;
}

const map = L.map("map", {
  zoomControl: true,
  attributionControl: true,
}).setView(DEFAULT_CENTER, DEFAULT_ZOOM);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 12,
  attribution: "&copy; OpenStreetMap-Mitwirkende",
}).addTo(map);

let frames = buildFrameTimes();
let currentIndex = frames.length - 1;
let isPlaying = false;
let playTimer = null;
let frameCache = new Map(); // isoString -> objectURL
let radarOverlay = null;
let preloadToken = 0; // verwirft veraltete Preload-Laeufe (z.B. nach schnellem Pan)

sliderEl.max = String(frames.length - 1);
sliderEl.value = String(currentIndex);

function currentViewSnapshot() {
  const bounds = map.getBounds();
  const sw = L.CRS.EPSG3857.project(bounds.getSouthWest());
  const ne = L.CRS.EPSG3857.project(bounds.getNorthEast());
  const size = map.getSize();
  return {
    latLngBounds: bounds,
    bbox: [sw.x, sw.y, ne.x, ne.y],
    width: Math.max(1, Math.round(size.x)),
    height: Math.max(1, Math.round(size.y)),
  };
}

async function fetchFrameBlob(view, date) {
  const iso = date.toISOString();
  const url = buildWmsImageUrl(view.bbox, view.width, view.height, iso);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

async function preloadFrames() {
  const myToken = ++preloadToken;
  stopPlaying();
  playBtn.disabled = true;
  showStatus(`Lade Radardaten… 0/${frames.length}`);

  const view = currentViewSnapshot();
  const newCache = new Map();
  const queue = frames.map((d) => d);
  let loaded = 0;

  async function worker() {
    while (queue.length) {
      const date = queue.shift();
      try {
        const objectUrl = await fetchFrameBlob(view, date);
        if (myToken !== preloadToken) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        newCache.set(date.toISOString(), objectUrl);
      } catch (e) {
        // einzelner Frame fehlt einfach - Loop macht ohne ihn weiter
      }
      loaded++;
      if (myToken === preloadToken) {
        showStatus(`Lade Radardaten… ${loaded}/${frames.length}`);
      }
    }
  }

  await Promise.all(
    Array.from({ length: PRELOAD_CONCURRENCY }, () => worker())
  );

  if (myToken !== preloadToken) {
    // ein neuerer Preload-Lauf hat diesen ueberholt (z.B. Kartenbewegung) - verwerfen
    for (const url of newCache.values()) URL.revokeObjectURL(url);
    return;
  }

  for (const url of frameCache.values()) URL.revokeObjectURL(url);
  frameCache = newCache;

  if (!radarOverlay) {
    radarOverlay = L.imageOverlay("", view.latLngBounds, {
      opacity: 0.75,
      interactive: false,
      attribution: "Radardaten: Deutscher Wetterdienst (Open Data)",
    }).addTo(map);
  } else {
    radarOverlay.setBounds(view.latLngBounds);
  }

  hideStatus();
  playBtn.disabled = false;
  renderFrame(currentIndex);
}

function renderFrame(index) {
  currentIndex = index;
  const date = frames[index];
  const url = frameCache.get(date.toISOString());
  if (url && radarOverlay) radarOverlay.setUrl(url);
  sliderEl.value = String(index);
  timestampEl.textContent = formatLocal(date) + " Uhr";
}

function stopPlaying() {
  isPlaying = false;
  playBtn.textContent = "▶";
  if (playTimer) {
    clearInterval(playTimer);
    playTimer = null;
  }
}

function startPlaying() {
  isPlaying = true;
  playBtn.textContent = "❚❚";
  playTimer = setInterval(() => {
    renderFrame((currentIndex + 1) % frames.length);
  }, PLAY_INTERVAL_MS);
}

playBtn.addEventListener("click", () => {
  if (isPlaying) stopPlaying();
  else startPlaying();
});

sliderEl.addEventListener("input", () => {
  stopPlaying();
  renderFrame(Number(sliderEl.value));
});

let moveDebounceTimer = null;
map.on("moveend zoomend", () => {
  clearTimeout(moveDebounceTimer);
  moveDebounceTimer = setTimeout(preloadFrames, MOVE_DEBOUNCE_MS);
});

preloadFrames();

// Alle 5 Minuten neue Frame-Liste + Bilder nachziehen, damit der Loop aktuell bleibt.
setInterval(() => {
  const wasPlaying = isPlaying;
  frames = buildFrameTimes();
  sliderEl.max = String(frames.length - 1);
  currentIndex = frames.length - 1;
  preloadFrames().then(() => {
    if (wasPlaying) startPlaying();
  });
}, 5 * 60 * 1000);

if ("geolocation" in navigator) {
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      map.setView([pos.coords.latitude, pos.coords.longitude], DEFAULT_ZOOM);
    },
    () => {
      flashStatus("Standort nicht verfügbar – zeige Berlin", 3000);
    },
    { timeout: 5000 }
  );
}
