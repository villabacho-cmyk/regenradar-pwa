# Regenradar PWA

Werbefreie Regenradar-App für iPhone (PWA, "Zum Home-Bildschirm hinzufügen"), gebaut auf offenen Daten des Deutschen Wetterdienstes. Kein Backend, kein Tracking, keine API-Keys im Client.

Live: https://villabacho-cmyk.github.io/regenradar-pwa/

## Architektur-Überblick

Statische Seite (`index.html` / `app.js` / `style.css`) mit Leaflet-Karte auf OSM-Basiskarte. Drei unabhängige Datenquellen, alle als vorgebackene JSON/PNG-Dateien unter `data/` ausgeliefert (Client lädt nie live bei DWD/MOSMIX, das wäre wegen DWD's Serverzeit von 3-4s pro Bild zu langsam):

### 1. Regenradar (DWD)
- **Quelle:** DWD-WMS-Layer `Radar_rv_product_1x1km_ger` ("Deutsches Radarkomposit Analyse und Vorhersage").
- **Skript:** [scripts/fetch_radar.py](scripts/fetch_radar.py) — holt 12 Vergangenheits-Frames (60 Min, 5-Min-Takt) + 24 Vorhersage-Frames (120 Min, reine Radarecho-Extrapolation, kein Modell-Nowcasting).
- **Ausgabe:** `data/radar/frame-*.png` + `data/radar/manifest.json` (enthält `nowIndex`, `isForecast` pro Frame).
- **Bekannte Einschränkung:** Das DWD-Netz hat zeitlich schwankende, nicht-permanente Abdeckungslücken an den Nahtstellen zwischen Radarstationen (z.B. gelegentlich bei Berlin/Eberswalde) — siehe RainViewer-Toggle als Ausweichmöglichkeit.

### 2. Temperatur / Wolken / Regenwahrscheinlichkeit (DWD MOSMIX)
- **Quelle:** DWD MOSMIX_L Punktprognosen (`opendata.dwd.de/weather/local_forecasts/mos/`).
- **Skript:** [scripts/fetch_temperature.py](scripts/fetch_temperature.py) — holt alle 281 deutschen MOSMIX-Stationen parallel (ThreadPoolExecutor, da statische Dateien ohne Server-Rendering, ~30-40s Laufzeit), je Station 48h stündliche Serie (Temperatur, Bedeckungsgrad, Regenwahrscheinlichkeit `R101`, Sonnenschein `RSunD`).
- **Ausgabe:** `data/temperature/manifest.json`. Jede Station hat ein `onMap`-Flag: nur ~41 kuratierte Stationen (Großstädte + flächige Verteilung) werden als Icons auf der Karte gezeigt, alle 281 fließen aber in die "nächste Station zu meinem Standort"-Suche für die 48h-Vorhersageleiste ein (für Genauigkeit unter 65-100km Abstand).
- Temperatur/Wolken-Icons auf der Karte sind an die Zeit des aktuell angezeigten Radar-Frames gekoppelt (nicht an die echte Uhrzeit) — beim Scrubben in die Radar-Prognose zeigen sie den passenden Vorhersagewert.

### 3. RainViewer (Ergänzung, client-seitig)
- Toggle-Button oben rechts auf der Karte wechselt zwischen DWD (mit 120-Min-Prognose) und RainViewer (global aggregiertes Radarkomposit, letzte ~2h, keine Prognose).
- Komplett client-seitig, keine eigene Vorback-Pipeline — RainViewer liefert fertige Kacheln direkt (`api.rainviewer.com`).
- Gedacht als Ausweichmöglichkeit für die DWD-Netzlücken (Punkt 1), nicht als Ersatz — RainViewer hat aktuell keine Nowcast-Frames in der kostenlosen API.

## Update-Pipeline

Zwei GitHub-Actions-Workflows: [.github/workflows/update-radar.yml](.github/workflows/update-radar.yml) (Radar) und [.github/workflows/update-temperature.yml](.github/workflows/update-temperature.yml) (Temperatur).

**Wichtig — externer Cron-Trigger:** GitHub's eigener `schedule`-Cron hat sich in der Praxis als unzuverlässig erwiesen (hat über Stunden hinweg fast nie von selbst ausgelöst). Die tatsächliche, verlässliche Auslösung läuft daher über einen **externen Cronjob bei [cron-job.org](https://cron-job.org)**, der per HTTP POST die GitHub-API (`.../actions/workflows/<name>.yml/dispatches`) mit einem Fine-grained Personal Access Token (Repo-Scope `regenradar-pwa`, Permission `Actions: Read and write`) anstößt:
- Radar: alle 10 Minuten.
- Temperatur: alle 6h, um `:20` nach der vollen 6h-Stunde (MOSMIX braucht laut Messung 1h12m-1h17m nach der Veröffentlichung bis die Datei verfügbar ist — `:20` gibt sicheren Puffer).

Der `schedule:`-Trigger in den Workflow-Dateien bleibt als Fallback bestehen, falls GitHub's Scheduler doch mal zuverlässig greift — die Hauptlast trägt aber cron-job.org. **Falls der Token abläuft oder widerrufen wird, muss ein neuer Fine-grained Token erstellt und bei cron-job.org im Authorization-Header aktualisiert werden**, sonst bleiben die Daten dauerhaft veraltet (keine Fehlermeldung im Client, nur ein alter Zeitstempel im Header).

**Commit-Strategie:** Beide Workflows amenden ihren letzten *eigenen* Bot-Commit (Prüfung über die Commit-Message, nicht nur den Autornamen — sonst amenden sich Radar- und Temperatur-Workflow gegenseitig kaputt, ist schon passiert) statt jedes Mal einen neuen Commit anzuhängen, sonst würde das Repo bei 10-Minuten-Takt schnell auf mehrere hundert MB wachsen. `actions/checkout` läuft mit `fetch-depth: 0` (volle Historie) — ein flacher Checkout hat in Kombination mit `git commit --amend` einmal dazu geführt, dass die komplette Repo-Historie beim Push auf einen wurzellosen Einzel-Commit kollabiert ist.

## Deployment

Cloudflare Pages, deployed automatisch bei jedem Push auf `main` (Cloudflare beobachtet das GitHub-Repo direkt). Kein Build-Schritt — reine statische Dateien.

**Warum nicht mehr GitHub Pages:** Dessen CDN (Fastly) cached `data/radar/manifest.json` fix mit `Cache-Control: max-age=600` — unabhängig vom 10-Minuten-Cron-Takt, dadurch bis zu 10 Min zusätzliche, nicht vorhersehbare Verzögerung obendrauf. Lässt sich clientseitig nicht zuverlässig umgehen (empirisch getestet: Query-String-Cache-Busting und ein `Cache-Control: no-cache`-Request-Header werden beide vom Fastly-Edge ignoriert). Cloudflare Pages unterstützt dagegen eine [`_headers`](_headers)-Datei, die `Cache-Control: no-store` gezielt für die beiden Manifest-Dateien (Radar + Temperatur) setzt. Die Radar-Frame-PNGs bleiben normal gecacht — jeder Frame hat ohnehin einen eigenen, zeitstempel-basierten Dateinamen und ist damit inhaltlich stabil, Caching dort ist unproblematisch.

## Lokale Entwicklung

```bash
python3 -m http.server 8000
```

Einzelne Fetch-Skripte lokal testen:

```bash
python3 scripts/fetch_radar.py
python3 scripts/fetch_temperature.py
```

## Service Worker

[sw.js](sw.js) cached die App-Shell-Dateien network-first (nicht cache-first) — bei jedem Aufruf wird zuerst versucht, die aktuelle Version vom Netz zu laden, der Cache dient nur als Offline-Fallback. `data/radar/*` und `data/temperature/*` sind bewusst vom Service-Worker-Cache ausgenommen (würden sonst als wachsender, nie aufgeräumter Cache landen — die Zeitstempel-basierten Dateinamen sind eh schon über normales HTTP-Caching abgedeckt).

## Offene Ideen / zurückgestellte Optionen

Siehe [Parkplatz und Backlog.md](Parkplatz und Backlog.md).
