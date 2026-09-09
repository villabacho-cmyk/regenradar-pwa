#!/usr/bin/env python3
"""Holt die aktuellen DWD-Radar-Frames (offene Geodaten) und legt sie als
feste Datei-Namen unter data/radar/ ab, dazu ein manifest.json mit den
tatsaechlichen Zeitstempeln. Wird per GitHub Actions alle 10 Minuten
ausgefuehrt - siehe .github/workflows/update-radar.yml.

Der Bild-Ausschnitt entspricht exakt der vollen Abdeckung des DWD-Layers
(Deutschland + Grenzregion) - mehr Daten gibt es bei diesem Layer nicht,
es wird also nichts eingeschraenkt.
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

DWD_WMS_URL = "https://maps.dwd.de/geoserver/dwd/wms"
DWD_LAYER = "Radar_rv_product_1x1km_ger"

# Volle Abdeckung des Layers (EPSG:3857), siehe GetCapabilities.
BBOX_3857 = [163152.40840662256, 5730101.503917769, 2083209.8854073866, 7600452.973715202]
BBOX_LATLNG = {
    "south": 45.68555450940017,
    "west": 1.4656230213298098,
    "north": 56.21059036783446,
    "east": 18.713792803508305,
}
IMAGE_WIDTH = 1000
IMAGE_HEIGHT = 974

FRAME_COUNT = 12  # 12 * 5 min = 60 Minuten
FRAME_STEP_MIN = 5
LAG_BUFFER_MIN = 10  # DWD braucht ein paar Minuten bis das neueste Bild verfuegbar ist

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "radar")


def build_frame_times():
    now = datetime.now(timezone.utc)
    floored_minute = (now.minute // FRAME_STEP_MIN) * FRAME_STEP_MIN
    latest = now.replace(minute=floored_minute, second=0, microsecond=0)
    latest -= timedelta(minutes=LAG_BUFFER_MIN)
    return [latest - timedelta(minutes=i * FRAME_STEP_MIN) for i in range(FRAME_COUNT - 1, -1, -1)]


def build_wms_url(time_iso):
    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetMap",
        "layers": DWD_LAYER,
        "styles": "",
        "format": "image/png",
        "transparent": "true",
        "crs": "EPSG:3857",
        "bbox": ",".join(str(v) for v in BBOX_3857),
        "width": str(IMAGE_WIDTH),
        "height": str(IMAGE_HEIGHT),
        "time": time_iso,
    }
    return f"{DWD_WMS_URL}?{urllib.parse.urlencode(params)}"


def fetch_frame(time_iso, dest_path):
    url = build_wms_url(time_iso)
    req = urllib.request.Request(url, headers={"User-Agent": "regenradar-pwa/1.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        if res.status != 200:
            raise RuntimeError(f"HTTP {res.status} fuer {time_iso}")
        data = res.read()
    with open(dest_path, "wb") as f:
        f.write(data)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    frames = build_frame_times()

    manifest_frames = []
    failures = 0
    for i, dt in enumerate(frames):
        time_iso = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        filename = f"frame-{i:02d}.png"
        dest_path = os.path.join(OUT_DIR, filename)
        try:
            fetch_frame(time_iso, dest_path)
            manifest_frames.append({"file": filename, "time": time_iso})
        except Exception as e:
            print(f"Warnung: Frame {time_iso} fehlgeschlagen: {e}", file=sys.stderr)
            failures += 1

    if not manifest_frames:
        print("Fehler: kein einziger Frame konnte geladen werden.", file=sys.stderr)
        sys.exit(1)

    manifest = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "bbox": BBOX_LATLNG,
        "frames": manifest_frames,
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Fertig: {len(manifest_frames)}/{FRAME_COUNT} Frames geladen, {failures} Fehler.")


if __name__ == "__main__":
    main()
