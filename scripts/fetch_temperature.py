#!/usr/bin/env python3
"""Holt Temperatur-, Wolken- und Sonnenschein-Vorhersagen (DWD MOSMIX_L,
offene Punktprognosen) fuer alle 281 deutschen MOSMIX-Stationen und
schreibt sie kompakt als data/temperature/manifest.json. Wird per GitHub
Actions alle 6 Stunden ausgefuehrt - siehe
.github/workflows/update-temperature.yml (MOSMIX_L selbst wird nur alle
6h neu veroeffentlicht, haeufigeres Holen waere sinnlos).

Warum alle 281 statt nur einer kleinen Auswahl: die "48h-Vorhersage fuer
meinen Standort"-Funktion im Client sucht sich die naechstgelegene
Station zu den echten GPS-Koordinaten. Mit nur ~40 Stationen kann das
bis zu 65-100km daneben liegen - mit allen 281 ist der Fehler minimal.
Die Karte selbst zeigt trotzdem nur eine kuratierte Teilmenge als Icons
(siehe ON_MAP_NAMES/onMap-Flag unten), sonst waere die Karte voll mit
Zahlen. Performance: MOSMIX-Dateien sind statische ~17KB-Dateien (kein
Server-seitiges Rendering wie beim Regenradar-WMS), gemessene
GH-Actions-Laufzeit fuer 41 Stationen lag bei ~35s - bei 6h-Cron-Takt
und paralleler Abfrage (ThreadPoolExecutor) ist das fuer alle 281 kein
Problem.
"""

import concurrent.futures
import io
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

# Alle 281 deutschen MOSMIX-Stationen (WMO-Block 10xxx) aus dem DWD-
# Stationskatalog (dwd.de, MOSMIX-Stationskatalog). Koordinaten dort im
# Format Grad.Bogenminuten - hier bereits in Dezimalgrad umgerechnet.
ALL_STATIONS = [
    {"stationId": "10004", "name": "Ufs Tw Ems", "lat": 54.1667, "lon": 6.35},
    {"stationId": "10007", "name": "Ufs Deutsche Bucht", "lat": 54.1667, "lon": 7.45},
    {"stationId": "10015", "name": "Helgoland", "lat": 54.1667, "lon": 7.8833},
    {"stationId": "10018", "name": "Westerland", "lat": 54.9167, "lon": 8.35},
    {"stationId": "10020", "name": "List/Sylt", "lat": 55.0167, "lon": 8.4167},
    {"stationId": "10022", "name": "Leck", "lat": 54.8, "lon": 8.95},
    {"stationId": "10026", "name": "Husum", "lat": 54.5167, "lon": 9.15},
    {"stationId": "10028", "name": "St. Peter Ording", "lat": 54.3333, "lon": 8.6},
    {"stationId": "10033", "name": "Flensburg", "lat": 54.8333, "lon": 9.5},
    {"stationId": "10034", "name": "Eggebek", "lat": 54.6333, "lon": 9.35},
    {"stationId": "10035", "name": "Schleswig", "lat": 54.5333, "lon": 9.55},
    {"stationId": "10037", "name": "Schleswig-Jagel", "lat": 54.4667, "lon": 9.5167},
    {"stationId": "10038", "name": "Hohn", "lat": 54.3167, "lon": 9.5333},
    {"stationId": "10042", "name": "Olpenitz", "lat": 54.6667, "lon": 10.0333},
    {"stationId": "10044", "name": "Leuchtturm Kiel", "lat": 54.5, "lon": 10.2667},
    {"stationId": "10046", "name": "Kiel", "lat": 54.3833, "lon": 10.15},
    {"stationId": "10055", "name": "Westermarkelsdorf", "lat": 54.5333, "lon": 11.0667},
    {"stationId": "10063", "name": "Puttgarden", "lat": 54.5, "lon": 11.2167},
    {"stationId": "10091", "name": "Arkona", "lat": 54.6833, "lon": 13.4333},
    {"stationId": "10093", "name": "Putbus", "lat": 54.3667, "lon": 13.4833},
    {"stationId": "10097", "name": "Greifswalder Oie", "lat": 54.2333, "lon": 13.9167},
    {"stationId": "10113", "name": "Norderney", "lat": 53.7167, "lon": 7.15},
    {"stationId": "10122", "name": "Jever", "lat": 53.5333, "lon": 7.8833},
    {"stationId": "10124", "name": "Leuchtturm A. Weser", "lat": 53.85, "lon": 8.1167},
    {"stationId": "10125", "name": "Wilhelmshaven", "lat": 53.5, "lon": 8.05},
    {"stationId": "10126", "name": "Wittmundhaven", "lat": 53.55, "lon": 7.6667},
    {"stationId": "10129", "name": "Bremerhaven", "lat": 53.5333, "lon": 8.5833},
    {"stationId": "10130", "name": "Elpersbuettel", "lat": 54.0667, "lon": 9.0167},
    {"stationId": "10131", "name": "Cuxhaven", "lat": 53.8667, "lon": 8.7167},
    {"stationId": "10136", "name": "Nordholz", "lat": 53.7667, "lon": 8.6667},
    {"stationId": "10139", "name": "Bremervoerde", "lat": 53.5, "lon": 9.1667},
    {"stationId": "10142", "name": "Itzehoe", "lat": 54.0, "lon": 9.5833},
    {"stationId": "10143", "name": "Neumuenster", "lat": 54.0833, "lon": 9.9333},
    {"stationId": "10146", "name": "Quickborn", "lat": 53.7333, "lon": 9.8833},
    {"stationId": "10147", "name": "Hamburg", "lat": 53.6333, "lon": 10.0},
    {"stationId": "10150", "name": "Doernick", "lat": 54.1667, "lon": 10.35},
    {"stationId": "10152", "name": "Pelzerhaken", "lat": 54.0833, "lon": 10.8833},
    {"stationId": "10156", "name": "Luebeck", "lat": 53.8167, "lon": 10.7},
    {"stationId": "10161", "name": "Boltenhagen", "lat": 54.0, "lon": 11.1833},
    {"stationId": "10162", "name": "Schwerin", "lat": 53.6333, "lon": 11.3833},
    {"stationId": "10168", "name": "Goldberg", "lat": 53.6167, "lon": 12.1},
    {"stationId": "10170", "name": "Warnemuende", "lat": 54.1833, "lon": 12.0833},
    {"stationId": "10172", "name": "Laage", "lat": 53.9167, "lon": 12.2833},
    {"stationId": "10177", "name": "Teterow", "lat": 53.7667, "lon": 12.6167},
    {"stationId": "10180", "name": "Barth", "lat": 54.3333, "lon": 12.7167},
    {"stationId": "10181", "name": "Parow", "lat": 54.3667, "lon": 13.0833},
    {"stationId": "10184", "name": "Greifswald", "lat": 54.1, "lon": 13.4167},
    {"stationId": "10193", "name": "Ueckermuende", "lat": 53.7333, "lon": 14.0667},
    {"stationId": "10200", "name": "Emden-Flugplatz", "lat": 53.3833, "lon": 7.2333},
    {"stationId": "10203", "name": "Emden", "lat": 53.35, "lon": 7.2},
    {"stationId": "10210", "name": "Friesoythe-Altenoyth", "lat": 53.0667, "lon": 7.9},
    {"stationId": "10215", "name": "Oldenburg", "lat": 53.1833, "lon": 8.1667},
    {"stationId": "10218", "name": "Ahlhorn", "lat": 52.8833, "lon": 8.2333},
    {"stationId": "10224", "name": "Bremen", "lat": 53.05, "lon": 8.8},
    {"stationId": "10234", "name": "Rotenburg", "lat": 53.1333, "lon": 9.35},
    {"stationId": "10235", "name": "Soltau", "lat": 52.9667, "lon": 9.7833},
    {"stationId": "10238", "name": "Bergen-Hohne", "lat": 52.8167, "lon": 9.9333},
    {"stationId": "10246", "name": "Fassberg", "lat": 52.9167, "lon": 10.1833},
    {"stationId": "10249", "name": "Boizenburg", "lat": 53.3833, "lon": 10.6833},
    {"stationId": "10253", "name": "Luechow", "lat": 52.9667, "lon": 11.1333},
    {"stationId": "10261", "name": "Seehausen", "lat": 52.8833, "lon": 11.7333},
    {"stationId": "10264", "name": "Marnitz", "lat": 53.3167, "lon": 11.9333},
    {"stationId": "10267", "name": "Kyritz", "lat": 52.9333, "lon": 12.4167},
    {"stationId": "10268", "name": "Waren", "lat": 53.5167, "lon": 12.6667},
    {"stationId": "10270", "name": "Neuruppin", "lat": 52.9, "lon": 12.8167},
    {"stationId": "10271", "name": "Neuruppin-Alt Ruppin", "lat": 52.95, "lon": 12.85},
    {"stationId": "10272", "name": "Wittstock", "lat": 53.1833, "lon": 12.5167},
    {"stationId": "10273", "name": "Malchin", "lat": 53.7333, "lon": 12.9333},
    {"stationId": "10277", "name": "Neuglobsow", "lat": 53.15, "lon": 13.0333},
    {"stationId": "10280", "name": "Neubrandenburg", "lat": 53.55, "lon": 13.2},
    {"stationId": "10281", "name": "Trollenhagen", "lat": 53.6, "lon": 13.3},
    {"stationId": "10282", "name": "Feldberg/Mecklenburg", "lat": 53.3167, "lon": 13.4167},
    {"stationId": "10289", "name": "Gruenow", "lat": 53.3167, "lon": 13.9333},
    {"stationId": "10291", "name": "Angermünde", "lat": 53.0333, "lon": 14.0},
    {"stationId": "10303", "name": "Lingen-Baccum", "lat": 52.5167, "lon": 7.4167},
    {"stationId": "10306", "name": "Rheine", "lat": 52.3, "lon": 7.3833},
    {"stationId": "10308", "name": "Nordhorn", "lat": 52.55, "lon": 7.1667},
    {"stationId": "10309", "name": "Ahaus", "lat": 52.0833, "lon": 6.9333},
    {"stationId": "10312", "name": "Belm", "lat": 52.3167, "lon": 8.1667},
    {"stationId": "10314", "name": "Hopsten", "lat": 52.3333, "lon": 7.55},
    {"stationId": "10315", "name": "Muenster/Osnabr.", "lat": 52.1333, "lon": 7.7},
    {"stationId": "10317", "name": "Osnabrueck", "lat": 52.25, "lon": 8.05},
    {"stationId": "10320", "name": "Guetersloh", "lat": 51.9167, "lon": 8.3},
    {"stationId": "10321", "name": "Diepholz", "lat": 52.5833, "lon": 8.35},
    {"stationId": "10324", "name": "Minden", "lat": 52.3167, "lon": 8.85},
    {"stationId": "10325", "name": "Bad Salzuflen", "lat": 52.1, "lon": 8.75},
    {"stationId": "10326", "name": "Bielefeld", "lat": 51.9667, "lon": 8.55},
    {"stationId": "10334", "name": "Wunstorf", "lat": 52.45, "lon": 9.4333},
    {"stationId": "10335", "name": "Bueckeburg", "lat": 52.2833, "lon": 9.0833},
    {"stationId": "10338", "name": "Hannover", "lat": 52.4667, "lon": 9.6833},
    {"stationId": "10343", "name": "Celle", "lat": 52.6, "lon": 10.0167},
    {"stationId": "10348", "name": "Braunschweig", "lat": 52.2833, "lon": 10.45},
    {"stationId": "10356", "name": "Ummendorf", "lat": 52.1667, "lon": 11.1833},
    {"stationId": "10359", "name": "Gardelegen", "lat": 52.5167, "lon": 11.3833},
    {"stationId": "10361", "name": "Magdeburg", "lat": 52.1167, "lon": 11.5833},
    {"stationId": "10365", "name": "Genthin", "lat": 52.3833, "lon": 12.1667},
    {"stationId": "10368", "name": "Wiesenburg", "lat": 52.1167, "lon": 12.4667},
    {"stationId": "10376", "name": "Baruth", "lat": 52.0667, "lon": 13.5},
    {"stationId": "10379", "name": "Potsdam", "lat": 52.3833, "lon": 13.0667},
    {"stationId": "10381", "name": "Berlin-Dahlem", "lat": 52.4667, "lon": 13.3},
    {"stationId": "10382", "name": "Berlin-Tegel", "lat": 52.5667, "lon": 13.3167},
    {"stationId": "10384", "name": "Berlin", "lat": 52.4667, "lon": 13.4},
    {"stationId": "10385", "name": "Berlin-Brandenburg", "lat": 52.3833, "lon": 13.5167},
    {"stationId": "10389", "name": "Berlin-Alex.", "lat": 52.5167, "lon": 13.4167},
    {"stationId": "10393", "name": "Lindenberg", "lat": 52.2167, "lon": 14.1167},
    {"stationId": "10396", "name": "Frankfurt (Oder)", "lat": 52.55, "lon": 14.55},
    {"stationId": "10400", "name": "Düsseldorf", "lat": 51.3, "lon": 6.7667},
    {"stationId": "10401", "name": "Brueggen", "lat": 51.2, "lon": 6.1333},
    {"stationId": "10403", "name": "Moenchengladbach", "lat": 51.2333, "lon": 6.5},
    {"stationId": "10404", "name": "Kalkar", "lat": 51.7333, "lon": 6.2667},
    {"stationId": "10405", "name": "Niederrhein", "lat": 51.6, "lon": 6.15},
    {"stationId": "10406", "name": "Bocholt", "lat": 51.8333, "lon": 6.5333},
    {"stationId": "10410", "name": "Essen", "lat": 51.4, "lon": 6.9667},
    {"stationId": "10416", "name": "Dortmund", "lat": 51.5167, "lon": 7.6167},
    {"stationId": "10418", "name": "Luedenscheid", "lat": 51.25, "lon": 7.6333},
    {"stationId": "10424", "name": "Werl", "lat": 51.5833, "lon": 7.8833},
    {"stationId": "10426", "name": "Paderborn", "lat": 51.6167, "lon": 8.6167},
    {"stationId": "10427", "name": "K.Asten", "lat": 51.1833, "lon": 8.4833},
    {"stationId": "10430", "name": "Bad Lippspringe", "lat": 51.7833, "lon": 8.8333},
    {"stationId": "10432", "name": "Koeterberg", "lat": 51.85, "lon": 9.3167},
    {"stationId": "10433", "name": "Luedge", "lat": 51.8667, "lon": 9.2667},
    {"stationId": "10435", "name": "Warburg", "lat": 51.5, "lon": 9.1167},
    {"stationId": "10438", "name": "Kassel", "lat": 51.3, "lon": 9.45},
    {"stationId": "10439", "name": "Fritzlar", "lat": 51.1167, "lon": 9.2833},
    {"stationId": "10441", "name": "Schauenburg-Elgersh.", "lat": 51.2833, "lon": 9.3667},
    {"stationId": "10442", "name": "Alfeld", "lat": 51.9667, "lon": 9.8},
    {"stationId": "10444", "name": "Goettingen", "lat": 51.5, "lon": 9.95},
    {"stationId": "10449", "name": "Leinefelde", "lat": 51.3833, "lon": 10.3167},
    {"stationId": "10452", "name": "Braunlage", "lat": 51.7167, "lon": 10.6},
    {"stationId": "10453", "name": "Brocken", "lat": 51.8, "lon": 10.6167},
    {"stationId": "10454", "name": "Wernigerode", "lat": 51.85, "lon": 10.7667},
    {"stationId": "10457", "name": "Cochstedt", "lat": 51.85, "lon": 11.4167},
    {"stationId": "10458", "name": "Harzgerode", "lat": 51.65, "lon": 11.1333},
    {"stationId": "10460", "name": "Artern", "lat": 51.3667, "lon": 11.2833},
    {"stationId": "10466", "name": "Halle", "lat": 51.5167, "lon": 11.95},
    {"stationId": "10469", "name": "Leipzig", "lat": 51.4167, "lon": 12.2333},
    {"stationId": "10471", "name": "Leipzig-Stadt", "lat": 51.3167, "lon": 12.4167},
    {"stationId": "10474", "name": "Wittenberg", "lat": 51.8833, "lon": 12.6333},
    {"stationId": "10476", "name": "Holzdorf", "lat": 51.7667, "lon": 13.1833},
    {"stationId": "10480", "name": "Oschatz", "lat": 51.3, "lon": 13.0833},
    {"stationId": "10487", "name": "Dresden-Stadt", "lat": 51.05, "lon": 13.7333},
    {"stationId": "10488", "name": "Dresden", "lat": 51.1333, "lon": 13.75},
    {"stationId": "10490", "name": "Doberlug-Kirchhain", "lat": 51.65, "lon": 13.5667},
    {"stationId": "10492", "name": "Cottbus/Flugplatz", "lat": 51.7667, "lon": 14.2833},
    {"stationId": "10493", "name": "Preschen", "lat": 51.6667, "lon": 14.6333},
    {"stationId": "10495", "name": "Hoyerswerda", "lat": 51.45, "lon": 14.25},
    {"stationId": "10496", "name": "Cottbus", "lat": 51.7833, "lon": 14.3167},
    {"stationId": "10499", "name": "Görlitz", "lat": 51.1667, "lon": 14.95},
    {"stationId": "10500", "name": "Geilenkirchen", "lat": 50.9667, "lon": 6.05},
    {"stationId": "10501", "name": "Aachen", "lat": 50.7833, "lon": 6.1},
    {"stationId": "10502", "name": "Noervenich", "lat": 50.8333, "lon": 6.6667},
    {"stationId": "10505", "name": "Aachen-Orsbach", "lat": 50.8, "lon": 6.0333},
    {"stationId": "10506", "name": "Nuerburg-Barweiler", "lat": 50.3667, "lon": 6.8667},
    {"stationId": "10510", "name": "Nuerburg", "lat": 50.3333, "lon": 6.95},
    {"stationId": "10513", "name": "Köln", "lat": 50.8667, "lon": 7.1667},
    {"stationId": "10514", "name": "Mendig", "lat": 50.3667, "lon": 7.3167},
    {"stationId": "10515", "name": "Koblenz", "lat": 50.4167, "lon": 7.5833},
    {"stationId": "10516", "name": "Koblenz-Falkenstein", "lat": 50.3667, "lon": 7.5833},
    {"stationId": "10517", "name": "Bonn-Friesdorf", "lat": 50.7, "lon": 7.15},
    {"stationId": "10519", "name": "Bonn-Roleber", "lat": 50.7333, "lon": 7.1833},
    {"stationId": "10520", "name": "Andernach", "lat": 50.4333, "lon": 7.4333},
    {"stationId": "10521", "name": "Rothaargebirge", "lat": 50.9333, "lon": 8.2},
    {"stationId": "10522", "name": "Euskirchen", "lat": 50.65, "lon": 6.7833},
    {"stationId": "10526", "name": "Bad Marienberg", "lat": 50.6667, "lon": 7.9667},
    {"stationId": "10532", "name": "Giessen", "lat": 50.6, "lon": 8.6333},
    {"stationId": "10534", "name": "Hoherodskopf", "lat": 50.5167, "lon": 9.2167},
    {"stationId": "10535", "name": "Wahlen", "lat": 50.8167, "lon": 9.1333},
    {"stationId": "10536", "name": "Fulda", "lat": 50.55, "lon": 9.65},
    {"stationId": "10537", "name": "Neu-Ulrichstein", "lat": 50.75, "lon": 9.0167},
    {"stationId": "10540", "name": "Eisenach", "lat": 51.0, "lon": 10.3667},
    {"stationId": "10542", "name": "Bad Hersfeld", "lat": 50.85, "lon": 9.7333},
    {"stationId": "10544", "name": "Wasserkuppe", "lat": 50.5, "lon": 9.9333},
    {"stationId": "10546", "name": "Kaltennordheim", "lat": 50.6333, "lon": 10.15},
    {"stationId": "10548", "name": "Meiningen", "lat": 50.5667, "lon": 10.3833},
    {"stationId": "10552", "name": "Schmuecke", "lat": 50.65, "lon": 10.7667},
    {"stationId": "10554", "name": "Erfurt", "lat": 50.9833, "lon": 10.9667},
    {"stationId": "10555", "name": "Weimar", "lat": 50.9833, "lon": 11.3167},
    {"stationId": "10557", "name": "Neuhaus Am Rennweg", "lat": 50.5, "lon": 11.1333},
    {"stationId": "10558", "name": "Sonneberg", "lat": 50.3833, "lon": 11.1833},
    {"stationId": "10564", "name": "Schleiz", "lat": 50.5667, "lon": 11.8},
    {"stationId": "10565", "name": "Osterfeld", "lat": 51.0833, "lon": 11.9333},
    {"stationId": "10567", "name": "Gera", "lat": 50.8833, "lon": 12.1333},
    {"stationId": "10569", "name": "Plauen", "lat": 50.4833, "lon": 12.1333},
    {"stationId": "10574", "name": "Carlsfeld", "lat": 50.4333, "lon": 12.6167},
    {"stationId": "10575", "name": "Aue", "lat": 50.6, "lon": 12.7167},
    {"stationId": "10577", "name": "Chemnitz", "lat": 50.7833, "lon": 12.8667},
    {"stationId": "10578", "name": "Fichtelberg", "lat": 50.4333, "lon": 12.95},
    {"stationId": "10579", "name": "Marienberg", "lat": 50.65, "lon": 13.15},
    {"stationId": "10582", "name": "Zinnwald", "lat": 50.7333, "lon": 13.75},
    {"stationId": "10591", "name": "Lichtenhain", "lat": 50.9333, "lon": 14.2167},
    {"stationId": "10609", "name": "Trier", "lat": 49.75, "lon": 6.6667},
    {"stationId": "10613", "name": "Eifel", "lat": 50.1667, "lon": 7.0667},
    {"stationId": "10615", "name": "Deuselbach", "lat": 49.7667, "lon": 7.05},
    {"stationId": "10616", "name": "Hahn", "lat": 49.95, "lon": 7.2667},
    {"stationId": "10617", "name": "Traben-Trarbach", "lat": 49.9667, "lon": 7.1167},
    {"stationId": "10618", "name": "Idar-Oberstein", "lat": 49.7, "lon": 7.3333},
    {"stationId": "10619", "name": "Baumholder", "lat": 49.6167, "lon": 7.35},
    {"stationId": "10628", "name": "Geisenheim", "lat": 49.9833, "lon": 7.95},
    {"stationId": "10633", "name": "Wiesbaden", "lat": 50.05, "lon": 8.3333},
    {"stationId": "10635", "name": "Kleiner Feldberg", "lat": 50.2167, "lon": 8.45},
    {"stationId": "10637", "name": "Frankfurt", "lat": 50.05, "lon": 8.6},
    {"stationId": "10640", "name": "Frankfurt-Fechenheim", "lat": 50.1167, "lon": 8.7333},
    {"stationId": "10641", "name": "Offenbach", "lat": 50.0833, "lon": 8.7833},
    {"stationId": "10645", "name": "Breitsol", "lat": 49.9, "lon": 9.4333},
    {"stationId": "10646", "name": "Neuhuetten", "lat": 50.0167, "lon": 9.4167},
    {"stationId": "10648", "name": "Michelstadt", "lat": 49.7167, "lon": 9.1},
    {"stationId": "10655", "name": "Würzburg", "lat": 49.7667, "lon": 9.9667},
    {"stationId": "10658", "name": "Bad Kissingen", "lat": 50.2, "lon": 10.0833},
    {"stationId": "10671", "name": "Lautertal", "lat": 50.2833, "lon": 10.9833},
    {"stationId": "10675", "name": "Bamberg", "lat": 49.8833, "lon": 10.9167},
    {"stationId": "10677", "name": "Bayreuth", "lat": 49.9833, "lon": 11.6333},
    {"stationId": "10684", "name": "Hof/Flughafen", "lat": 50.2833, "lon": 11.85},
    {"stationId": "10685", "name": "Hof", "lat": 50.3167, "lon": 11.8833},
    {"stationId": "10686", "name": "Wunsiedel", "lat": 50.0333, "lon": 11.9667},
    {"stationId": "10688", "name": "Weiden", "lat": 49.6667, "lon": 12.1833},
    {"stationId": "10704", "name": "Berus", "lat": 49.2667, "lon": 6.6833},
    {"stationId": "10706", "name": "Tholey", "lat": 49.4833, "lon": 7.05},
    {"stationId": "10708", "name": "Saarbrücken", "lat": 49.2167, "lon": 7.1167},
    {"stationId": "10714", "name": "Zweibrücken", "lat": 49.2167, "lon": 7.4},
    {"stationId": "10722", "name": "Karlsruhe", "lat": 48.7833, "lon": 8.0833},
    {"stationId": "10724", "name": "Weinbiet", "lat": 49.3833, "lon": 8.1167},
    {"stationId": "10727", "name": "Karlsruhe-Rheinstett.", "lat": 49.0333, "lon": 8.3667},
    {"stationId": "10729", "name": "Mannheim", "lat": 49.5167, "lon": 8.55},
    {"stationId": "10731", "name": "Rheinstetten", "lat": 48.9667, "lon": 8.3167},
    {"stationId": "10733", "name": "Waibstadt", "lat": 49.2833, "lon": 8.9167},
    {"stationId": "10735", "name": "Sinsheim", "lat": 49.25, "lon": 8.8833},
    {"stationId": "10736", "name": "Muehlacker", "lat": 48.9667, "lon": 8.8667},
    {"stationId": "10738", "name": "Stuttgart", "lat": 48.6833, "lon": 9.2167},
    {"stationId": "10739", "name": "Stuttgart-Schnarrenb.", "lat": 48.8333, "lon": 9.2},
    {"stationId": "10742", "name": "Oehringen", "lat": 49.2167, "lon": 9.5167},
    {"stationId": "10743", "name": "Niederstetten", "lat": 49.4, "lon": 9.9667},
    {"stationId": "10747", "name": "Kaisersbach", "lat": 48.9167, "lon": 9.6833},
    {"stationId": "10755", "name": "Ansbach", "lat": 49.3167, "lon": 10.6333},
    {"stationId": "10756", "name": "Feuchtwangen", "lat": 49.1667, "lon": 10.3667},
    {"stationId": "10761", "name": "Weissenburg", "lat": 49.0167, "lon": 10.9333},
    {"stationId": "10763", "name": "Nürnberg", "lat": 49.5, "lon": 11.05},
    {"stationId": "10765", "name": "Roth", "lat": 49.2167, "lon": 11.1},
    {"stationId": "10771", "name": "Kuemmersbruck", "lat": 49.4333, "lon": 11.9},
    {"stationId": "10776", "name": "Regensburg", "lat": 49.0333, "lon": 12.1},
    {"stationId": "10777", "name": "Gelbelsee", "lat": 48.95, "lon": 11.4333},
    {"stationId": "10782", "name": "Waldmuenchen", "lat": 49.3833, "lon": 12.6833},
    {"stationId": "10788", "name": "Straubing", "lat": 48.8333, "lon": 12.5667},
    {"stationId": "10791", "name": "Grosser Arber", "lat": 49.1167, "lon": 13.1333},
    {"stationId": "10796", "name": "Zwiesel", "lat": 49.0333, "lon": 13.2333},
    {"stationId": "10803", "name": "Freiburg", "lat": 48.0167, "lon": 7.8333},
    {"stationId": "10805", "name": "Lahr", "lat": 48.3667, "lon": 7.8333},
    {"stationId": "10815", "name": "Freudenstadt", "lat": 48.45, "lon": 8.4167},
    {"stationId": "10818", "name": "Klippeneck", "lat": 48.1167, "lon": 8.75},
    {"stationId": "10827", "name": "Messstetten", "lat": 48.1833, "lon": 9.0},
    {"stationId": "10828", "name": "Sigmaringen", "lat": 48.1, "lon": 9.25},
    {"stationId": "10836", "name": "Stoetten", "lat": 48.6667, "lon": 9.8667},
    {"stationId": "10837", "name": "Laupheim", "lat": 48.2167, "lon": 9.9167},
    {"stationId": "10838", "name": "Ulm", "lat": 48.3833, "lon": 9.95},
    {"stationId": "10840", "name": "Ulm-Maehringen", "lat": 48.45, "lon": 9.9167},
    {"stationId": "10850", "name": "Harburg", "lat": 48.7833, "lon": 10.7167},
    {"stationId": "10852", "name": "Augsburg", "lat": 48.4333, "lon": 10.9333},
    {"stationId": "10853", "name": "Neuburg/Donau", "lat": 48.7167, "lon": 11.2167},
    {"stationId": "10856", "name": "Lechfeld", "lat": 48.1833, "lon": 10.85},
    {"stationId": "10857", "name": "Landsberg", "lat": 48.0667, "lon": 10.9},
    {"stationId": "10858", "name": "Fuerstenfeldbruck", "lat": 48.2, "lon": 11.2667},
    {"stationId": "10860", "name": "Ingolstadt", "lat": 48.7167, "lon": 11.5333},
    {"stationId": "10863", "name": "Weihenstephan", "lat": 48.4, "lon": 11.7},
    {"stationId": "10865", "name": "München-Stadt", "lat": 48.1667, "lon": 11.5333},
    {"stationId": "10870", "name": "München", "lat": 48.3667, "lon": 11.8},
    {"stationId": "10872", "name": "Gottfrieding", "lat": 48.6667, "lon": 12.5333},
    {"stationId": "10875", "name": "Muehldorf", "lat": 48.2833, "lon": 12.5},
    {"stationId": "10893", "name": "Passau-Stadt", "lat": 48.5833, "lon": 13.4667},
    {"stationId": "10895", "name": "Passau", "lat": 48.55, "lon": 13.35},
    {"stationId": "10908", "name": "Feldberg/Schwarzwald", "lat": 47.8833, "lon": 8.0},
    {"stationId": "10929", "name": "Konstanz", "lat": 47.6833, "lon": 9.1833},
    {"stationId": "10935", "name": "Friedrichshafen", "lat": 47.6667, "lon": 9.5167},
    {"stationId": "10945", "name": "Leutkirch", "lat": 47.8, "lon": 10.0333},
    {"stationId": "10946", "name": "Kempten", "lat": 47.7167, "lon": 10.3333},
    {"stationId": "10947", "name": "Memmingen", "lat": 47.9833, "lon": 10.2333},
    {"stationId": "10948", "name": "Oberstdorf", "lat": 47.4, "lon": 10.2833},
    {"stationId": "10954", "name": "Altenstadt", "lat": 47.8333, "lon": 10.8667},
    {"stationId": "10961", "name": "Zugspitze", "lat": 47.4167, "lon": 10.9833},
    {"stationId": "10962", "name": "Hohenpeissenberg", "lat": 47.8, "lon": 11.0167},
    {"stationId": "10963", "name": "Garmisch", "lat": 47.4833, "lon": 11.0667},
    {"stationId": "10980", "name": "Wendelstein", "lat": 47.7, "lon": 12.0167},
    {"stationId": "10982", "name": "Chiemsee", "lat": 47.8833, "lon": 12.5333},
]

# Diese Stationen (Grossstaedte + flaechige Verteilung) werden als Icons
# auf der Karte angezeigt - alle anderen fliessen nur in die "naechste
# Station zu meinem Standort"-Suche fuer die 48h-Vorhersage ein, sonst
# waere die Karte mit 281 Zahlen komplett ueberladen.
ON_MAP_IDS = {
    "10384", "10147", "10870", "10513", "10637", "10738", "10400", "10469",
    "10488", "10224", "10338", "10763", "10018", "10091", "10034", "10055",
    "10004", "10136", "10273", "10203", "10291", "10267", "10396", "10306",
    "10361", "10326", "10452", "10499", "10439", "10554", "10575", "10536",
    "10613", "10677", "10743", "10708", "10722", "10895", "10982", "10954",
    "10935",
}

MOSMIX_URL_TEMPLATE = (
    "https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L/"
    "single_stations/{id}/kml/MOSMIX_L_LATEST_{id}.kmz"
)
SERIES_HOURS = 48  # Kurve/Anzeige braucht keine vollen 10 Tage MOSMIX liefert
MAX_WORKERS = 12  # MOSMIX-Dateien sind statisch (kein Server-Rendering) -
# parallele Abfrage ist unproblematisch und haelt die Laufzeit niedrig.

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
    timesteps = [el.text for el in root.iter("{%s}TimeStep" % KML_NS["dwd"])]

    def values_for(element_name):
        for forecast in root.iter("{%s}Forecast" % KML_NS["dwd"]):
            if forecast.get("{%s}elementName" % KML_NS["dwd"]) == element_name:
                value_el = forecast.find("dwd:value", KML_NS)
                return value_el.text.split()
        return None

    ttt_raw = values_for("TTT")
    rsund_raw = values_for("RSunD")  # Tageswert (nur alle 24h ein Wert)
    n_raw = values_for("N")  # Gesamtbedeckungsgrad in %, stuendlich
    r101_raw = values_for("R101")  # Niederschlagswahrscheinlichkeit >0.1mm/1h in %, stuendlich

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
        rain_pct = None
        if r101_raw and i < len(r101_raw) and r101_raw[i] != "-":
            rain_pct = round(float(r101_raw[i]))
        series.append(
            {
                "time": time_iso,
                "tempC": temp_c,
                "sunPct": sun_pct,
                "cloudPct": cloud_pct,
                "rainPct": rain_pct,
            }
        )
    return series


def fetch_one(station):
    kml_bytes = fetch_kml(station["stationId"])
    series = parse_series(kml_bytes)
    if not any(entry["tempC"] is not None for entry in series):
        raise RuntimeError("keine gueltigen Temperaturwerte in der Antwort")
    return {
        "name": station["name"],
        "lat": station["lat"],
        "lon": station["lon"],
        "onMap": station["stationId"] in ON_MAP_IDS,
        "series": series,
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    stations_out = []
    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_station = {pool.submit(fetch_one, s): s for s in ALL_STATIONS}
        for future in concurrent.futures.as_completed(future_to_station):
            station = future_to_station[future]
            try:
                stations_out.append(future.result())
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

    print(f"Fertig: {len(stations_out)}/{len(ALL_STATIONS)} Stationen geladen, {failures} Fehler.")


if __name__ == "__main__":
    main()
