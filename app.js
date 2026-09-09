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

const TEMPERATURE_MANIFEST_URL = "data/temperature/manifest.json";
// MOSMIX (die Datenquelle) aktualisiert eh nur alle 6h - hier oefter
// nachzufragen wuerde nichts bringen. Normales HTTP-Caching (kein
// no-store) reicht, da ein paar Minuten Verzoegerung nicht auffallen.
const TEMPERATURE_POLL_MS = 10 * 60 * 1000;

const DEFAULT_CENTER = [52.52, 13.405]; // Berlin, Fallback ohne Geolocation
const DEFAULT_ZOOM = 8;

const statusEl = document.getElementById("status");
const timestampEl = document.getElementById("timestamp");
const sliderEl = document.getElementById("slider");
const playBtn = document.getElementById("playBtn");
const forecastToggle = document.getElementById("forecastToggle");
const forecastSheet = document.getElementById("forecastSheet");
const forecastClose = document.getElementById("forecastClose");
const forecastStrip = document.getElementById("forecastStrip");
const forecastLocationName = document.getElementById("forecastLocationName");
const forecastDateLabel = document.getElementById("forecastDateLabel");

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
  updateTemperatureLabelsForTime(new Date(frame.time).getTime());

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

// Temperatur-Zahlen + Wolken/Sonne-Icon fuer eine Reihe deutscher
// Stationen, gleichzeitig mit dem Regenradar sichtbar. Fixe Stationsliste
// statt dynamischer Standort-Erkennung (siehe scripts/fetch_temperature.py)
// - reicht fuer den deutschlandweiten Kartenausschnitt. 12 grosse Staedte
// als Anker, dazu weitere Stationen fuer eine flaechigere Verteilung.
let temperatureMarkers = []; // {marker, station}

// Waehlt aus der stuendlichen Vorhersage-Reihe den Wert, der der
// uebergebenen Zeit am naechsten liegt. timeMs kommt vom aktuell
// angezeigten Regenradar-Frame - so zeigen Temperatur/Wolken-Icon immer
// den zur Slider-Position passenden Stundenwert, nicht die echte
// aktuelle Uhrzeit.
function closestSeriesEntry(series, timeMs) {
  let best = null;
  let bestDiff = Infinity;
  for (const entry of series) {
    if (entry.tempC == null) continue;
    const diff = Math.abs(new Date(entry.time).getTime() - timeMs);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = entry;
    }
  }
  return best;
}

function cloudIcon(cloudPct) {
  if (cloudPct == null) return "";
  if (cloudPct < 25) return "☀️";
  if (cloudPct < 75) return "⛅";
  return "☁️";
}

function temperatureLabelHtml(entry) {
  if (!entry) return "";
  return `<span class="cloud-icon">${cloudIcon(entry.cloudPct)}</span><span class="temp-num">${Math.round(entry.tempC)}</span>`;
}

// Aktuell angezeigte Zeit des Regenradars (bzw. "jetzt", solange noch
// keine Frames geladen sind) - das ist die gemeinsame Zeitbasis fuer die
// Temperatur/Wolken-Labels.
function currentRadarTimeMs() {
  const frame = frames[currentIndex];
  return frame ? new Date(frame.time).getTime() : Date.now();
}

function renderTemperatureLabels(stations) {
  temperatureMarkers.forEach(({ marker }) => map.removeLayer(marker));
  temperatureMarkers = [];

  // Nur die kuratierte Teilmenge (onMap) als Icons zeigen - sonst waere
  // die Karte mit allen 281 Stationen komplett ueberladen. Die "naechste
  // Station zu meinem Standort"-Suche fuer die 48h-Vorhersage nutzt
  // trotzdem alle Stationen aus allStations (siehe nearestStation()).
  for (const station of stations.filter((s) => s.onMap)) {
    const icon = L.divIcon({
      className: "temp-label",
      html: "",
      iconSize: [0, 0],
      iconAnchor: [-8, -8], // Label etwas versetzt neben dem Stationspunkt
    });
    const marker = L.marker([station.lat, station.lon], { icon, interactive: false }).addTo(map);
    temperatureMarkers.push({ marker, station });
  }
  updateTemperatureLabelsForTime(currentRadarTimeMs());
}

// Aktualisiert nur den Inhalt der bestehenden Marker (kein Entfernen/
// Neuanlegen) - wird bei jedem Radar-Frame-Wechsel aufgerufen, auch
// waehrend der Wiedergabe alle 450ms, muss also billig sein.
function updateTemperatureLabelsForTime(timeMs) {
  for (const { marker, station } of temperatureMarkers) {
    const entry = closestSeriesEntry(station.series, timeMs);
    const el = marker.getElement();
    if (el) el.innerHTML = temperatureLabelHtml(entry);
  }
}

let allStations = [];
let userLatLng = null;

async function refreshTemperature() {
  try {
    const res = await fetch(TEMPERATURE_MANIFEST_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const manifest = await res.json();
    allStations = manifest.stations;
    renderTemperatureLabels(manifest.stations);
    if (forecastSheet.classList.contains("open")) renderForecastStrip();
  } catch (e) {
    // Stumm scheitern - Temperatur-Zahlen sind ein Zusatz, kein Blocker
    // fuer den Regenradar-Grund-Use-Case.
  }
}

refreshTemperature();
setInterval(refreshTemperature, TEMPERATURE_POLL_MS);

// 48h-Vorhersage fuer den eigenen Standort: naechstgelegene Station zu
// userLatLng, keine eigene Geocoding-Loesung noetig - die 41 Stationen
// sind eh schon flaechig verteilt (siehe scripts/fetch_temperature.py).
function nearestStation(latlng, stations) {
  let best = null;
  let bestDist = Infinity;
  for (const station of stations) {
    const dLat = station.lat - latlng[0];
    const dLon = station.lon - latlng[1];
    const dist = dLat * dLat + dLon * dLon;
    if (dist < bestDist) {
      bestDist = dist;
      best = station;
    }
  }
  return best;
}

function formatWeekdayDate(date) {
  return date.toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" });
}

function renderForecastStrip() {
  if (!userLatLng || allStations.length === 0) {
    forecastStrip.innerHTML = `<div class="forecast-empty">Standort/Daten noch nicht verfügbar</div>`;
    forecastDateLabel.textContent = "";
    return;
  }
  const station = nearestStation(userLatLng, allStations);
  forecastLocationName.textContent = station.name;

  const cutoff = Date.now() - 30 * 60 * 1000; // kleiner Puffer, damit die laufende Stunde nicht rausfaellt
  const upcoming = station.series.filter(
    (entry) => entry.tempC != null && new Date(entry.time).getTime() >= cutoff
  );
  forecastStrip.innerHTML = upcoming
    .map((entry) => {
      const date = new Date(entry.time);
      return `
      <div class="forecast-hour" data-date-label="${formatWeekdayDate(date)}">
        <span class="fh-time">${formatLocal(date)}</span>
        <span class="fh-icon">${cloudIcon(entry.cloudPct)}</span>
        <span class="fh-temp">${Math.round(entry.tempC)}°</span>
        <span class="fh-rain">${entry.rainPct != null ? entry.rainPct + "%" : "–"}</span>
      </div>`;
    })
    .join("");
  forecastStrip.scrollLeft = 0;
  updateForecastDateIndicator();
}

// Datum/Wochentag im Header: zeigt beim Scrollen das Datum der zweiten
// von links sichtbaren Stunden-Karte an (nicht die mittlere - auf dem
// schmalen iPhone-Screen mit nur ~6-7 sichtbaren Karten lag die Mitte
// sonst schon 3-4h vor der linken Kante, der Tageswechsel kam zu frueh).
function updateForecastDateIndicator() {
  const hours = Array.from(forecastStrip.querySelectorAll(".forecast-hour"));
  if (hours.length === 0) return;

  const stripLeft = forecastStrip.getBoundingClientRect().left;
  let firstVisibleIndex = hours.findIndex((el) => el.getBoundingClientRect().right > stripLeft);
  if (firstVisibleIndex === -1) firstVisibleIndex = 0;
  const anchorIndex = Math.min(firstVisibleIndex + 1, hours.length - 1);
  forecastDateLabel.textContent = hours[anchorIndex].dataset.dateLabel;
}

forecastStrip.addEventListener("scroll", updateForecastDateIndicator, { passive: true });

forecastToggle.addEventListener("click", () => {
  const isOpen = forecastSheet.classList.toggle("open");
  forecastToggle.setAttribute("aria-expanded", String(isOpen));
  if (isOpen) renderForecastStrip();
});

forecastClose.addEventListener("click", () => {
  forecastSheet.classList.remove("open");
  forecastToggle.setAttribute("aria-expanded", "false");
});

if ("geolocation" in navigator) {
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const latlng = [pos.coords.latitude, pos.coords.longitude];
      userLatLng = latlng;
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
