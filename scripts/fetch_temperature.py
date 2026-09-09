#!/usr/bin/env python3
"""Holt Temperatur- und Sonnenschein-Vorhersagen (DWD MOSMIX_L, offene
Punktprognosen) fuer eine feste Liste deutscher Staedte und schreibt sie
kompakt als data/temperature/manifest.json. Wird per GitHub Actions alle
6 Stunden ausgefuehrt - siehe .github/workflows/update-temperature.yml
(MOSMIX_L selbst wird nur alle 6h neu veroeffentlicht, haeufigeres Holen
waere sinnlos).

Bewusst eine feste Staedteliste statt "naechste Station zum aktuellen
Kartenausschnitt": der Kartenausschnitt ist fix auf ganz Deutschland
gesetzt (siehe fetch_radar.py), nicht vom Nutzer-Standort abhaengig.
"""

import io
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

# Stations-IDs + Koordinaten aus dem DWD-Stationskatalog (dwd.de, MOSMIX-
# Stationskatalog), Koordinaten dort im Format Grad.Bogenminuten - bereits
# in Dezimalgrad umgerechnet.
CITIES = [
    {"name": "Berlin", "stationId": "10384", "lat": 52.4667, "lon": 13.4},
    {"name": "Hamburg", "stationId": "10147", "lat": 53.6333, "lon": 10.0},
    {"name": "München", "stationId": "10870", "lat": 48.3667, "lon": 11.8},
    {"name": "Köln", "stationId": "10513", "lat": 50.8667, "lon": 7.1667},
    {"name": "Frankfurt", "stationId": "10637", "lat": 50.05, "lon": 8.6},
    {"name": "Stuttgart", "stationId": "10738", "lat": 48.6833, "lon": 9.2167},
    {"name": "Düsseldorf", "stationId": "10400", "lat": 51.3, "lon": 6.7667},
    {"name": "Leipzig", "stationId": "10469", "lat": 51.4167, "lon": 12.2333},
    {"name": "Dresden", "stationId": "10488", "lat": 51.1333, "lon": 13.75},
    {"name": "Bremen", "stationId": "10224", "lat": 53.05, "lon": 8.8},
    {"name": "Hannover", "stationId": "10338", "lat": 52.4667, "lon": 9.6833},
    {"name": "Nürnberg", "stationId": "10763", "lat": 49.5, "lon": 11.05},
]

MOSMIX_URL_TEMPLATE = (
    "https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L/"
    "single_stations/{id}/kml/MOSMIX_L_LATEST_{id}.kmz"
)
SERIES_HOURS = 48  # Kurve/Anzeige braucht keine vollen 10 Tage MOSMIX liefert

KML_NS = {
    "kml": "http://www.opengis.net/kml/2.2",
    "dwd": "https://opendata.dwd.de/weather/lib/pointforecast_dwd_extension_V1_0.xsd",
}

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "temperature")


def fetch_kml(station_id):
    url = MOSMIX_URL_TEMPLATE.format(id=station_id)
    req = urllib.request.Request(url, headers={"User-Agent": "regenradar-pwa/1.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        if res.status != 200:
            raise RuntimeError(f"HTTP {res.status} fuer Station {station_id}")
        kmz_bytes = res.read()
    with zipfile.ZipFile(io.BytesIO(kmz_bytes)) as zf:
        kml_name = next(n for n in zf.namelist() if n.endswith(".kml"))
        return zf.read(kml_name)


def parse_series(kml_bytes):
    root = ET.fromstring(kml_bytes)
    timesteps = [
        el.text for el in root.iter("{%s}TimeStep" % KML_NS["dwd"])
    ]

    def values_for(element_name):
        for forecast in root.iter("{%s}Forecast" % KML_NS["dwd"]):
            if forecast.get("{%s}elementName" % KML_NS["dwd"]) == element_name:
                value_el = forecast.find("dwd:value", KML_NS)
                return value_el.text.split()
        return None

    ttt_raw = values_for("TTT")
    rsund_raw = values_for("RSunD")

    series = []
    for i, time_iso in enumerate(timesteps[:SERIES_HOURS]):
        temp_c = None
        if ttt_raw and i < len(ttt_raw) and ttt_raw[i] != "-":
            temp_c = round(float(ttt_raw[i]) - 273.15, 1)
        sun_pct = None
        if rsund_raw and i < len(rsund_raw) and rsund_raw[i] != "-":
            sun_pct = round(float(rsund_raw[i]))
        series.append({"time": time_iso, "tempC": temp_c, "sunPct": sun_pct})
    return series


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    cities_out = []
    failures = 0
    for city in CITIES:
        try:
            kml_bytes = fetch_kml(city["stationId"])
            series = parse_series(kml_bytes)
            if not any(entry["tempC"] is not None for entry in series):
                raise RuntimeError("keine gueltigen Temperaturwerte in der Antwort")
            cities_out.append(
                {"name": city["name"], "lat": city["lat"], "lon": city["lon"], "series": series}
            )
        except Exception as e:
            print(f"Warnung: {city['name']} fehlgeschlagen: {e}", file=sys.stderr)
            failures += 1

    if not cities_out:
        print("Fehler: keine einzige Stadt konnte geladen werden.", file=sys.stderr)
        sys.exit(1)

    manifest = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "cities": cities_out,
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"Fertig: {len(cities_out)}/{len(CITIES)} Staedte geladen, {failures} Fehler.")


if __name__ == "__main__":
    main()
