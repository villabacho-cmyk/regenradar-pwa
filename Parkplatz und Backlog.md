# Parkplatz und Backlog — Regenradar PWA

## ~~Vorhersage-Frames (Nowcast) zusätzlich zum Vergangenheits-Loop~~ — erledigt
Per `GetCapabilities` verifiziert: das RV-Layer liefert 120 Minuten Vorhersage (reine Radarecho-Extrapolation) im 5-Minuten-Takt nach der aktuellen Analysezeit. `build_frame_times()` in [scripts/fetch_radar.py](scripts/fetch_radar.py) erzeugt jetzt 12 Vergangenheits- + 24 Vorhersage-Frames, Manifest trägt `nowIndex` + `isForecast` pro Frame, `app.js` startet standardmäßig am "Jetzt"-Frame und markiert Prognose-Zeitpunkte im Timestamp-Label.

## Farblegende für Niederschlagsintensität
- **Was:** Kleine Legende (mm/h-Farbskala) am Kartenrand einblenden.
- **Warum zurückgestellt:** Nice-to-have, kein funktionaler Blocker für den Grund-Use-Case.
- **Wann wieder relevant:** Wenn Intensitätsunterschiede auf der Karte schwer einzuschätzen sind.
- **Implementierungs-Skizze:** DWD-Style/Legende über `GetLegendGraphic`-Request des WMS abrufen und als Bild in eine Ecke der Karte legen.

## Standortsuche / gespeicherter Lieblingsort
- **Was:** Aktuell nur einmalige Browser-Geolocation beim Laden (Fallback Berlin). Kein manuelles Suchen/Speichern eines Orts.
- **Warum zurückgestellt:** Für den persönlichen Gebrauch auf einem Gerät reicht Geolocation.
- **Wann wieder relevant:** Falls auf mehreren Geräten/Standorten genutzt oder Ort sich oft ändert.
- **Implementierungs-Skizze:** Leaflet-Suchfeld (z.B. Nominatim-Geocoding) + `localStorage` für zuletzt gewählten Ort.

## ~~Hosting-Alternative Cloudflare Pages~~ — in Arbeit
Grund für den Umzug war am Ende nicht Domain/Repo-Präferenz, sondern ein konkreter Bug: GitHub Pages' CDN (Fastly) cached `data/radar/manifest.json` fix mit `max-age=600`, unabhängig vom 10-Minuten-Cron-Takt — bis zu 10 Min zusätzliche Verzögerung, clientseitig nicht umgehbar (siehe README, Abschnitt Deployment). Cloudflare Pages per `_headers`-Datei (`Cache-Control: no-store` nur für die Manifest-Dateien) löst das. Cloudflare-Account ist angelegt und mit GitHub verbunden; `_headers`-Datei liegt im Repo bereit. Offen: Cloudflare-Pages-Projekt im Dashboard anlegen (Repo verbinden), neue `*.pages.dev`-URL in README eintragen, PWA auf dem iPhone neu speichern.

## ~~Service-Worker-Verhalten auf echtem Gerät~~ — erledigt
Auf dem echten GitHub-Pages-Host (HTTPS) registriert sich der Service Worker sauber, keine Fehler in der Konsole. Der frühere Fehlschlag war nur eine Einschränkung des internen Test-Tools.

## Bild-Auflösung / Qualität der vorgebackenen Frames
- **Was:** Die per GitHub Action erzeugten Radar-Bilder liegen fest bei 1000×974px für den kompletten DWD-Abdeckungsbereich (Deutschland + Grenzregion). Näher rangezoomt wirkt das etwas unschärfer als die frühere Live-Variante (die exakt pixelgenau für den jeweiligen Kartenausschnitt gerendert hat).
- **Warum zurückgestellt:** Kein Blocker — auf dem iPhone-Bildschirm in der Praxis kaum wahrnehmbar, und Live-Rendering war wegen der 3-4s DWD-Serverzeit pro Bild ohnehin keine Option mehr.
- **Wann wieder relevant:** Falls beim Reinzoomen auf eine kleine Region die Pixeligkeit störend auffällt.
- **Implementierungs-Skizze:** `IMAGE_WIDTH`/`IMAGE_HEIGHT` in [scripts/fetch_radar.py](scripts/fetch_radar.py) erhöhen (mehr Aufloesung = groessere PNGs = etwas laengere Action-Laufzeit, aber egal da im Hintergrund).

## Wolken-Layer (Satellitenbild)
- **Was:** Wolken wie bei WetterOnline als animierten Layer über der Karte anzeigen.
- **Warum zurückgestellt:** DWD-WMS bietet dafür nur Satellitenbilder (`Satellite_meteosat_1km_euat_rgb_day_hrv_and_night_ir108_3h`), die nur alle 3 Stunden aktualisiert werden (Opendata-Freigabetakt). Ein Loop daraus wäre ruckelig (8 Standbilder/Tag), nicht das flüssige "Wolken ziehen"-Bild wie beim Regenradar. User hat sich stattdessen für Sonnenschein-Vorhersage über MOSMIX entschieden (siehe Temperatur/Sonnenschein-Feature).
- **Wann wieder relevant:** Falls trotz des ruckeligen Looks Interesse besteht, oder eine bessere/schnellere Satellitenquelle gefunden wird.
- **Implementierungs-Skizze:** Analog zu `fetch_radar.py` einen Layer-Toggle mit den 3h-Satellitenframes bauen; alternativ MOSMIX-Bewölkungsgrad (`N`/`Neff`/`Nl`/`Nm`/`Nh`, im selben Datensatz wie Temperatur/Sonnenschein vorhanden) als numerische Alternative statt Kartenlayer.

## ~~Weltweite Abdeckung~~ — erledigt (mit Einschränkung)
RainViewer als Toggle-Layer eingebaut (siehe unten) — deckt auch außerhalb Deutschlands ab. Einschränkung: nur ~2h Vergangenheit, keine Prognose, geringere native Auflösung als DWD (Zoom-Stufe 7 gecappt).

## ~~DWD-Netzlücken (z.B. bei Berlin/Eberswalde)~~ — erledigt
DWD's Radarkomposit hat zeitlich schwankende (nicht permanente!) Abdeckungslücken an Nahtstellen zwischen Radarstationen — empirisch über mehrere Zeitpunkte verifiziert, kein fester geometrischer Fehler. RainViewer als zweite Datenquelle per Toggle-Button (oben rechts auf der Karte) eingebaut: global aggregiert aus 1200+ Stationen, umgeht die DWD-spezifischen Lücken. Eigener Zeitregler für RainViewer (letzte ~2h, keine Prognose vorhanden). Details siehe [README.md](README.md).

## ~~GitHub-Actions-Cron unzuverlässig~~ — erledigt
GitHub's eigener `schedule`-Trigger hat über Stunden hinweg fast nie von selbst ausgelöst (nur 1x autonom beobachtet). Externer Cronjob bei cron-job.org triggert jetzt zuverlässig per GitHub-API + Fine-grained PAT (siehe README.md, Abschnitt "Update-Pipeline"). **Wiedervorlage:** Falls der PAT abläuft/widerrufen wird, muss er erneuert werden, sonst frieren die Daten wieder ein.
