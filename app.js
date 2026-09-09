// Regenradar: OSM-Basiskarte + DWD-Radar (offene Geodaten, WMS mit Zeit-Dimension).
// Kein Backend, keine Werbung, keine API-Keys.

const DWD_WMS_URL = "https://maps.dwd.de/geoserver/dwd/wms";
const DWD_LAYER = "Radar_rv_product_1x1km_ger";

const FRAME_COUNT = 18; // 18 * 5 min = 90 Minuten Loop
const FRAME_STEP_MIN = 5;
const LAG_BUFFER_MIN = 10; // DWD braucht ein paar Minuten bis das neueste Bild verfuegbar ist
const PLAY_INTERVAL_MS = 450;

const DEFAULT_CENTER = [52.52, 13.405]; // Berlin, Fallback ohne Geolocation
const DEFAULT_ZOOM = 8;

const statusEl = document.getElementById("status");
const timestampEl = document.getElementById("timestamp");
const sliderEl = document.getElementById("slider");
const playBtn = document.getElementById("playBtn");

function showStatus(text, timeoutMs) {
  statusEl.textContent = text;
  statusEl.classList.add("visible");
  if (timeoutMs) {
    setTimeout(() => statusEl.classList.remove("visible"), timeoutMs);
  }
}

function buildFrameTimes() {
  const now = new Date();
  const flooredMinutes = Math.floor(now.getUTCMinutes() / FRAME_STEP_MIN) * FRAME_STEP_MIN;
  const latest = new Date(now);
  latest.setUTCMinutes(flooredMinutes, 0, 0);
  latest.setUTCMinutes(latest.getUTCMinutes() - LAG_BUFFER_MIN);

  const frames = [];
  for (let i = FRAME_COUNT - 1; i >= 0; i--) {
    const t = new Date(latest.getTime() - i * FRAME_STEP_MIN * 60 * 1000);
    frames.push(t);
  }
  return frames;
}

function formatLocal(date) {
  return date.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

const map = L.map("map", {
  zoomControl: true,
  attributionControl: true,
}).setView(DEFAULT_CENTER, DEFAULT_ZOOM);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 12,
  attribution: '&copy; OpenStreetMap-Mitwirkende',
}).addTo(map);

const frames = buildFrameTimes();
let currentIndex = frames.length - 1;
let isPlaying = false;
let playTimer = null;

const radarLayer = L.tileLayer.wms(DWD_WMS_URL, {
  layers: DWD_LAYER,
  format: "image/png",
  transparent: true,
  version: "1.3.0",
  opacity: 0.75,
  time: frames[currentIndex].toISOString(),
  attribution: "Radardaten: Deutscher Wetterdienst (Open Data)",
}).addTo(map);

radarLayer.on("tileerror", () => showStatus("Radar-Kachel nicht verfügbar", 2500));

sliderEl.max = String(frames.length - 1);
sliderEl.value = String(currentIndex);

function renderFrame(index) {
  currentIndex = index;
  const t = frames[index];
  radarLayer.setParams({ time: t.toISOString() });
  sliderEl.value = String(index);
  timestampEl.textContent = formatLocal(t) + " Uhr";
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
    const next = (currentIndex + 1) % frames.length;
    renderFrame(next);
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

renderFrame(currentIndex);

// Alle 5 Minuten neue Frame-Liste nachziehen, damit der Loop nicht "einfriert".
setInterval(() => {
  const wasPlaying = isPlaying;
  stopPlaying();
  const newFrames = buildFrameTimes();
  frames.length = 0;
  frames.push(...newFrames);
  sliderEl.max = String(frames.length - 1);
  renderFrame(frames.length - 1);
  if (wasPlaying) startPlaying();
}, 5 * 60 * 1000);

if ("geolocation" in navigator) {
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      map.setView([pos.coords.latitude, pos.coords.longitude], DEFAULT_ZOOM);
    },
    () => {
      showStatus("Standort nicht verfügbar – zeige Berlin", 3000);
    },
    { timeout: 5000 }
  );
}
