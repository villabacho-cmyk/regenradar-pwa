#!/usr/bin/env python3
"""Holt Temperatur-, Wolken- und Sonnenschein-Vorhersagen (DWD MOSMIX_L,
offene Punktprognosen) fuer eine feste Liste deutscher Stationen und
schreibt sie kompakt als data/temperature/manifest.json. Wird per GitHub
Actions alle 6 Stunden ausgefuehrt - siehe
.github/workflows/update-temperature.yml (MOSMIX_L selbst wird nur alle
6h neu veroeffentlicht, haeufigeres Holen waere sinnlos).

Bewusst eine feste Stationsliste statt "naechste Station zum aktuellen
Kartenausschnitt": der Kartenausschnitt ist fix auf ganz Deutschland
gesetzt (siehe fetch_radar.py), nicht vom Nutzer-Standort abhaengig.
Die 12 grossen Staedte sind als Anker drin, dazu ~30 weitere Stationen
(per Mindestabstand-Filter aus dem DWD-Stationskatalog ausgewaehlt) fuer
eine breitere flaechige Verteilung als nur die Grossstaedte.
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
# in Dezimalgrad umgerechnet. Erste 12 = die grossen Staedte (Anker),
# Rest = zusaetzliche Stationen fuer eine flaechigere Verteilung, per
# Mindestabstand-Filter (>=65km) aus den 281 deutschen Stationen gewaehlt.
STATIONS = [
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
    {"name": "Westerland", "stationId": "10018", "lat": 54.9167, "lon": 8.35},
    {"name": "Arkona", "stationId": "10091", "lat": 54.6833, "lon": 13.4333},
    {"name": "Eggebek", "stationId": "10034", "lat": 54.6333, "lon": 9.35},
    {"name": "Fehmarn", "stationId": "10055", "lat": 54.5333, "lon": 11.0667},
    {"name": "Nordsee", "stationId": "10004", "lat": 54.1667, "lon": 6.35},
    {"name": "Nordholz", "stationId": "10136", "lat": 53.7667, "lon": 8.6667},
    {"name": "Malchin", "stationId": "10273", "lat": 53.7333, "lon": 12.9333},
    {"name": "Emden", "stationId": "10203", "lat": 53.35, "lon": 7.2},
    {"name": "Angermünde", "stationId": "10291", "lat": 53.0333, "lon": 14.0},
    {"name": "Kyritz", "stationId": "10267", "lat": 52.9333, "lon": 12.4167},
    {"name": "Frankfurt (Oder)", "stationId": "10396", "lat": 52.55, "lon": 14.55},
    {"name": "Rheine", "stationId": "10306", "lat": 52.3, "lon": 7.3833},
    {"name": "Magdeburg", "stationId": "10361", "lat": 52.1167, "lon": 11.5833},
    {"name": "Bielefeld", "stationId": "10326", "lat": 51.9667, "lon": 8.55},
    {"name": "Braunlage", "stationId": "10452", "lat": 51.7167, "lon": 10.6},
    {"name": "Görlitz", "stationId": "10499", "lat": 51.1667, "lon": 14.95},
    {"name": "Fritzlar", "stationId": "10439", "lat": 51.1167, "lon": 9.2833},
    {"name": "Erfurt", "stationId": "10554", "lat": 50.9833, "lon": 10.9667},
    {"name": "Aue", "stationId": "10575", "lat": 50.6, "lon": 12.7167},
    {"name": "Fulda", "stationId": "10536", "lat": 50.55, "lon": 9.65},
    {"name": "Eifel", "stationId": "10613", "lat": 50.1667, "lon": 7.0667},
    {"name": "Bayreuth", "stationId": "10677", "lat": 49.9833, "lon": 11.6333},
    {"name": "Niederstetten", "stationId": "10743", "lat": 49.4, "lon": 9.9667},
    {"name": "Saarbrücken", "stationId": "10708", "lat": 49.2167, "lon": 7.1167},
    {"name": "Karlsruhe", "stationId": "10722", "lat": 48.7833, "lon": 8.0833},
    {"name": "Passau", "stationId": "10895", "lat": 48.55, "lon": 13.35},
    {"name": "Chiemsee", "stationId": "10982", "lat": 47.8833, "lon": 12.5333},
    {"name": "Kempten", "stationId": "10954", "lat": 47.8333, "lon": 10.8667},
    {"name": "Friedrichshafen", "stationId": "10935", "lat": 47.6667, "lon": 9.5167},
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
    rsund_raw = values_for("RSunD")  # Tageswert (nur alle 24h ein Wert)
    n_raw = values_for("N")  # Gesamtbedeckungsgrad in %, stuendlich

    series = []
    for i, time_iso in enumerate(timesteps[:SERIES_HOURS]):
        temp_c = None
        if ttt_raw and i < len(ttt_raw) and ttt_raw[i] != "-":
            temp_c = round(float(ttt_raw[i]) - 273.15, 1)
        sun_pct = None
        if rsund_raw and i < len(rsund_raw) and rsund_raw[i] != "-":
            sun_pct = round(float(rsund_raw[i]))
        cloud_pct = None
        if n_raw and i < len(n_raw) and n_raw[i] != "-":
            cloud_pct = round(float(n_raw[i]))
        series.append({"time": time_iso, "tempC": temp_c, "sunPct": sun_pct, "cloudPct": cloud_pct})
    return series


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    stations_out = []
    failures = 0
    for station in STATIONS:
        try:
            kml_bytes = fetch_kml(station["stationId"])
            series = parse_series(kml_bytes)
            if not any(entry["tempC"] is not None for entry in series):
                raise RuntimeError("keine gueltigen Temperaturwerte in der Antwort")
            stations_out.append(
                {"name": station["name"], "lat": station["lat"], "lon": station["lon"], "series": series}
            )
        except Exception as e:
            print(f"Warnung: {station['name']} fehlgeschlagen: {e}", file=sys.stderr)
            failures += 1

    if not stations_out:
        print("Fehler: keine einzige Station konnte geladen werden.", file=sys.stderr)
        sys.exit(1)

    manifest = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "stations": stations_out,
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"Fertig: {len(stations_out)}/{len(STATIONS)} Stationen geladen, {failures} Fehler.")


if __name__ == "__main__":
    main()
