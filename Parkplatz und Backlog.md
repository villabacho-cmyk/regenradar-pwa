# Parkplatz und Backlog — Regenradar PWA

## Vorhersage-Frames (Nowcast) zusätzlich zum Vergangenheits-Loop
- **Was:** Das DWD-Layer `Radar_rv_product_1x1km_ger` enthält laut Titel auch Vorhersage-Daten (Analyse *und* Vorhersage), nicht nur Vergangenheit. WetterOnline zeigt typischerweise auch ein Stück Prognose mit an.
- **Warum zurückgestellt:** Nicht explizit gewünscht; erste Version bewusst auf reinen Vergangenheits-Loop (60 Min) beschränkt, um die Zeit-Logik einfach zu halten.
- **Wann wieder relevant:** Wenn der reine Rückblick-Loop im Alltag zu wenig Info liefert (z.B. "regnet es gleich noch?").
- **Implementierungs-Skizze:** In `build_frame_times()` in [scripts/fetch_radar.py](scripts/fetch_radar.py) zusätzliche Zeitstempel *nach* "jetzt" generieren (das Skript laeuft jetzt serverseitig per GitHub Action, nicht mehr im Client); prüfen wie weit das RV-Produkt tatsächlich in die Zukunft reicht (via GetCapabilities `REFERENCE_TIME`-Dimension).

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

## Hosting-Alternative Cloudflare Pages
- **Was:** Deployment aktuell auf GitHub Pages ausgelegt (siehe Chat-Anleitung).
- **Warum zurückgestellt:** GitHub Pages war Default-Vorschlag, nicht explizit vom User bestätigt.
- **Wann wieder relevant:** Falls kein GitHub-Repo gewünscht ist oder eigene Domain gebraucht wird.
- **Implementierungs-Skizze:** Gleicher Static-Files-Ordner, einfach bei Cloudflare Pages "Direct Upload" statt Git-Push.

## ~~Service-Worker-Verhalten auf echtem Gerät~~ — erledigt
Auf dem echten GitHub-Pages-Host (HTTPS) registriert sich der Service Worker sauber, keine Fehler in der Konsole. Der frühere Fehlschlag war nur eine Einschränkung des internen Test-Tools.

## Bild-Auflösung / Qualität der vorgebackenen Frames
- **Was:** Die per GitHub Action erzeugten Radar-Bilder liegen fest bei 1000×974px für den kompletten DWD-Abdeckungsbereich (Deutschland + Grenzregion). Näher rangezoomt wirkt das etwas unschärfer als die frühere Live-Variante (die exakt pixelgenau für den jeweiligen Kartenausschnitt gerendert hat).
- **Warum zurückgestellt:** Kein Blocker — auf dem iPhone-Bildschirm in der Praxis kaum wahrnehmbar, und Live-Rendering war wegen der 3-4s DWD-Serverzeit pro Bild ohnehin keine Option mehr.
- **Wann wieder relevant:** Falls beim Reinzoomen auf eine kleine Region die Pixeligkeit störend auffällt.
- **Implementierungs-Skizze:** `IMAGE_WIDTH`/`IMAGE_HEIGHT` in [scripts/fetch_radar.py](scripts/fetch_radar.py) erhöhen (mehr Aufloesung = groessere PNGs = etwas laengere Action-Laufzeit, aber egal da im Hintergrund).

## Weltweite Abdeckung (aktuell nicht möglich)
- **Was:** User-Frage, ob auch außerhalb Deutschlands Radardaten gezeigt werden können.
- **Warum nicht möglich:** Der DWD betreibt seine Wetterradare nur in/um Deutschland — das ist eine Datenverfügbarkeits-Grenze, keine Speicher- oder Auflösungsfrage. Für weltweite Abdeckung bräuchte es eine andere Datenquelle.
- **Wann wieder relevant:** Falls häufig im Ausland genutzt.
- **Implementierungs-Skizze:** Alternative Datenquelle wie RainViewer (globaler Radar-Mosaik-Dienst) prüfen — eigene Recherche zu Kosten/Lizenz nötig, noch nicht gemacht.
