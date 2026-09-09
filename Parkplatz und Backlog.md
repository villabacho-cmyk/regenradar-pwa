# Parkplatz und Backlog — Regenradar PWA

## Vorhersage-Frames (Nowcast) zusätzlich zum Vergangenheits-Loop
- **Was:** Das DWD-Layer `Radar_rv_product_1x1km_ger` enthält laut Titel auch Vorhersage-Daten (Analyse *und* Vorhersage), nicht nur Vergangenheit. WetterOnline zeigt typischerweise auch ein Stück Prognose mit an.
- **Warum zurückgestellt:** Nicht explizit gewünscht; erste Version bewusst auf reinen Vergangenheits-Loop (90 Min) beschränkt, um die Zeit-Logik einfach zu halten.
- **Wann wieder relevant:** Wenn der reine Rückblick-Loop im Alltag zu wenig Info liefert (z.B. "regnet es gleich noch?").
- **Implementierungs-Skizze:** In `buildFrameTimes()` in [app.js](app.js) zusätzliche Zeitstempel *nach* "jetzt" generieren; prüfen wie weit das RV-Produkt tatsächlich in die Zukunft reicht (via GetCapabilities `REFERENCE_TIME`-Dimension), visuell z.B. Slider-Bereich nach "jetzt" farblich abgrenzen.

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

## Service-Worker-Verhalten auf echtem Gerät nicht verifiziert
- **Was:** Im internen Browser-Preview schlug die Service-Worker-Registrierung fehl (Sandbox-Einschränkung des Preview-Tools, `[Likely]` kein echter Bug).
- **Warum zurückgestellt:** Kann nur auf echtem HTTPS-Hosting + echtem iPhone Safari verifiziert werden.
- **Wann wieder relevant:** Direkt nach dem ersten Deploy — kurz prüfen ob App offline/schnell neu öffnet.
- **Implementierungs-Skizze:** Falls Registrierung auf echtem Gerät auch fehlschlägt: Safari-Konsole per Mac (Web Inspector über Kabel) prüfen.
