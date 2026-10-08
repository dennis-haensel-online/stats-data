#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eurostat-widget.py — backt ein HTML-Statistik-Vergleichs-Widget aus der Eurostat-API.

Europaeische Kennzahlen (BPE 19-22, wirtschaftspolitische Konzeptionen) fuer ALLE verfuegbaren geo
(alle EU-/EWR-Laender + Drittlaender, soweit Eurostat sie je Datensatz fuehrt, + Aggregate
EU27_2020, EA20/EA21 …), aus EINER Quelle (Eurostat JSON-stat Dissemination API, anonym, kein Key).

ZEITHORIZONT (gemeinsame Spezifikation mit dem WB-Widget): EIN Selektor mit fuenf Optionen —
letzte 12 Monate · letztes Jahr (DEFAULT) · letzte 5 Jahre · letzte 10 Jahre · individuell (von-bis).
Es werden immer die KONKRETEN EINZELWERTE jeder Periode gezeigt, NIE Durchschnitte. Darstellung =
Matrix-Tabelle (Zeile je Entitaet, Spalte je Periode) + Liniendiagramm (je Entitaet Einzelwerte ueber
die Zeit). DEFAULT: Zeithorizont "letztes Jahr", nur Deutschland vorausgewaehlt.

INDIVIDUELL (von-bis): zwei Felder Start/Ende in der NATIVEN Aufloesung der gewaehlten Kennzahl
(Monat/Quartal/Jahr). Die Matrix zeigt die konkreten Einzelwerte ALLER Perioden im Bereich; bei vielen
Spalten wird sie in mehrere, untereinander gestapelte Tabellen (je ~12 Perioden, Zeilenkoepfe
wiederholt) aufgeteilt. Das Liniendiagramm zeigt die ganze gewaehlte Reihe.

BESTES/SCHLECHTESTES EU-LAND (wie im WB-Widget, s. stats-widget.py): je Kennzahl/Periode wird das beste
bzw. schlechteste EU-27-Land als eigene Matrix-Zeile gefuehrt — mit tatsaechlichem Laendernamen (im
Zeilenkopf fuer die juengste Periode, je Zelle als Tooltip/Subskript). "Bestes/schlechtestes" richtet
sich nach higher_is_better der Kennzahl; nur EU-Mitglieder (EU27, Griechenland = EL) zaehlen.

GEMISCHTE FREQUENZEN (verbindlich sauber behandelt): monatlich, vierteljaehrlich und jaehrlich in
EINEM Widget. Jede Kennzahl traegt ihre eigene Frequenz (M/Q/A). Regeln:
  - "letzte 12 Monate": FEINSTE (native) Aufloesung — monatliche Reihe → 12 Monatswerte,
    vierteljaehrliche → 4 Quartalswerte, jaehrliche → juengster Jahreswert.
  - "letztes Jahr" / "letzte 5 Jahre" / "letzte 10 Jahre": JAHRESAUFLOESUNG (1 / 5 / 10 Einzel-
    Jahreswerte). Je Jahr wird der JUENGSTE verfuegbare Wert dieses Jahres genommen (monatliche
    Reihe: juengster Monat; vierteljaehrliche: juengstes Quartal) — KEIN Durchschnitt, Label = Jahr.
Deshalb backt der Generator je Kennzahl ZWEI Serien: `full` (ALLE nativen Perioden — traegt die
12-Monats-Ansicht als letzte FINE_N sowie die individuelle von-bis-Auswahl) und `ann` (Jahresaufloesung,
letzter Wert je Jahr, fuer 1/5/10 Jahre). Beide tragen zusaetzlich `best`/`worst` (bestes/schlechtestes
EU-27-Land je Periode). Der aufgeloeste Zeitraum wird konkret neben dem Selektor angezeigt (z. B.
„Okt 2025 – Sep 2026" bzw. „2021–2025").

Kennzahlen (18): monatlich HVPI-Inflation, Arbeitslosenquote, Misery-Index (= Inflation + Arbeits-
losenquote, serverseitig); vierteljaehrl. reales BIP-Wachstum, Leistungsbilanzsaldo % BIP; jaehrlich
nominales BIP-Wachstum, nominales BIP-Niveau (jeweilige Preise), Aussenbeitrag/Nettoexporte % BIP,
Exporte % BIP, Importe % BIP, Staatsschuldenquote, Schuldenstand gesamt (Mrd €, aus gov_10dd_edpt1
MIO_EUR), Schuldenstand pro Kopf (€, ÷ Bevoelkerung demo_pjan, serverseitig), staatl. Finanzierungssaldo
% BIP, Staatsausgaben-quote, Staatseinnahmenquote, kurzfr. Zinsen, Gini. Die %-BIP-Kennzahlen sind
bewusst so gewaehlt, dass sich der Vergleich mit den Weltbank-Werten (`stats-widget.py`) und die
BERECHNUNGSUNTERSCHIEDE zeigen lassen (Methodenhinweis im Widget-Kontext).

Zwei Ausgabemodi:
  python _assets/eurostat-widget.py <bpe-ordner>          -> Include `_eurostat-widget.qmd` (Widget +
        kompakt gebackene Fallback-Daten fuer ALLE geo + optionaler Live-Fetch von GitHub).
  python _assets/eurostat-widget.py --emit-json <datei>   -> nur die JSON (fuer die GitHub-Action,
        die sie regelmaessig neu backt; das Widget holt sie dann live, s. stats-widget.py-Muster).

Auto-Update (optional): identisches Muster wie stats-widget.py/Newsticker — eine GitHub-Action legt
die `eurostat-stats.json` in ein oeffentliches Daten-Repo, das Widget fetcht sie clientseitig
(`cache:"no-store"`) und ersetzt die gebackene Fallback-Schicht. Leeres GITHUB_STATS_REPO => nur
gebacken (die Seite bleibt schnell: async Fetch, Fallback rendert sofort).
"""
import sys, json, urllib.request, io
from datetime import date

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

# VOLLE HISTORIE: je Kennzahl wird die GESAMTE verfuegbare Historie gebacken (nicht nur ~10 Jahre),
# damit die individuell-Start/Ende-Dropdowns bis zum fruehesten API-Zeitpunkt zurueckreichen. Wir
# begrenzen den Fetch nur durch einen frueher-als-alles liegenden sinceTimePeriod (Effizienz: EIN
# Request je Dataset, Eurostat liefert ab dem tatsaechlichen Reihenbeginn). Vorgegebene Horizont-
# Optionen (12m/1/5/10 Jahre) unveraendert.
HISTORY_SINCE = {"M": "1980-01", "Q": "1980-Q1", "A": "1970"}
# Native Periodenzahl der FEINEN Ansicht ("letzte 12 Monate") je Frequenz.
FINE_N = {"M": 12, "Q": 4, "A": 1}

# Der gebackene INLINE-Fallback (in die _*.qmd) wird auf die letzten INLINE_YEARS Kalenderjahre je
# Reihe gekappt (Monats-/Quartals-/Jahresreihen entsprechend) -> kleine, schnelle Seite. Der
# --emit-json-Pfad bleibt VOLLHISTORIE (GitHub-Live). Die Horizont-Optionen (12m/1/5/10 J.) + individuell
# funktionieren mit 15 Jahren weiter; individuell reicht im Fallback 15 Jahre zurueck.
INLINE_YEARS = 15

# Oeffentliches Daten-Repo fuer den Live-Layer (Setup s. stats-widget.py / _assets/stats-github/).
# Leer => Seite nur gebacken. Gemeinsames Daten-Repo mit dem WB- und dem Newsticker-Widget.
GITHUB_STATS_REPO = "dennis-haensel-online/stats-data"

DEFAULT_COLS = ["DE"]   # Vorgabe: nur Deutschland sichtbar (Zeithorizont = letztes Jahr)

# Eurostat-geo-Codes, die AGGREGATE sind (keine Einzellaender) — kommen im Multiselect oben.
AGG_CODES = {"EU", "EU27_2020", "EU28", "EA", "EA12", "EA19", "EA20", "EA21", "EEA"}

# EU-27-Mitgliedstaaten (Eurostat-geo-Codes; Griechenland = EL, nicht GR). Basis fuer das
# bestes/schlechtestes EU-Land je Kennzahl/Periode (nur Mitglieder, keine Aggregate/Drittlaender).
EU27 = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "EL", "HU", "IE", "IT",
        "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}

# Kurz-Anzeigenamen fuer Aggregate (statt der langen amtlichen Eurostat-Labels).
AGG_NAMES_DE = {
    "EU27_2020": "EU (27 Länder)", "EU": "EU (alle)", "EU28": "EU (28 Länder)",
    "EA": "Euroraum", "EA20": "Euroraum (20)", "EA21": "Euroraum (21)", "EA19": "Euroraum (19)",
    "EA12": "Euroraum (12)", "EEA": "EWR",
}

# BASIS-Serien (Eurostat-Fetches): fid -> (Dataset, Zusatzfilter, Frequenz M/Q/A).
# WICHTIG: fetch() dekodiert nur geo+time aus dem flachen JSON-stat-Index. Jede weitere Dimension
# MUSS per Filter auf eine einzige Auspraegung reduziert werden (Groesse 1), sonst wuerde
# out[geo][time] mehrfach ueberschrieben. Alle Filter sind gegen die API verifiziert (2026-09).
BASE_SERIES = {
    "hvpi":         ("prc_hicp_manr", {"coicop": "CP00"}, "M"),
    # HVPI als INDEX (monatlich, 2015=100) — zusaetzlich zur Inflationsrate. Am =100-Punkt (2015)
    # ist das Basisjahr erkennbar. Datensatz prc_hicp_midx fuehrt drei Basisjahre (I15/I05/I96) ->
    # unit=I15 pinnen (2015=100). Verifiziert DE (2015 ~ 100, 2025-08 = 132,5).
    "hvpi_index":   ("prc_hicp_midx", {"coicop": "CP00", "unit": "I15"}, "M"),
    "arbeitslos":   ("une_rt_m",
                     {"s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"}, "M"),
    "bip_real":     ("namq_10_gdp",
                     {"unit": "CLV_PCH_SM", "s_adj": "SCA", "na_item": "B1GQ"}, "Q"),
    "leistungsbil": ("bop_gdp6_q",
                     {"freq": "Q", "unit": "PC_GDP", "s_adj": "NSA", "bop_item": "CA",
                      "stk_flow": "BAL", "partner": "WRL_REST"}, "Q"),
    "schulden":     ("gov_10dd_edpt1", {"unit": "PC_GDP", "sector": "S13", "na_item": "GD"}, "A"),
    # Staatl. Finanzierungssaldo (net lending +/net borrowing -, ESA2010 EDP), selber Datensatz wie
    # die Schuldenquote, nur na_item B9. Verifiziert DE + EU27_2020.
    "finanzsaldo":  ("gov_10dd_edpt1", {"unit": "PC_GDP", "sector": "S13", "na_item": "B9"}, "A"),
    # Staatsausgaben-/Staatseinnahmenquote (Gesamtstaat S13, % BIP) aus gov_10a_main (unit PC_GDP
    # direkt vorhanden). TR = total revenue (Einnahmen); eine reine STEUERquote braeuchte
    # gov_10a_taxag (mischt sonst Sozialbeitraege ein) -> hier bewusst Einnahmenquote (TR).
    "staatsausg":   ("gov_10a_main", {"unit": "PC_GDP", "sector": "S13", "na_item": "TE"}, "A"),
    "staatseinn":   ("gov_10a_main", {"unit": "PC_GDP", "sector": "S13", "na_item": "TR"}, "A"),
    # Aussenwirtschaft: Exporte/Importe % BIP direkt als nama_10_gdp unit=PC_GDP (P6/P7). Der
    # Aussenbeitrag/Nettoexporte (na_item B11) ist bei Eurostat WEDER als CP_MEUR NOCH als PC_GDP
    # publiziert (verifiziert leer) -> serverseitig als Exporte - Importe berechnet (s. unten).
    "exporte":      ("nama_10_gdp", {"unit": "PC_GDP", "na_item": "P6"}, "A"),
    "importe":      ("nama_10_gdp", {"unit": "PC_GDP", "na_item": "P7"}, "A"),
    # Nominales BIP zu jeweiligen Preisen (current prices), Mio. Euro -> Niveau + nominales Wachstum.
    "gdp_cp":       ("nama_10_gdp", {"unit": "CP_MEUR", "na_item": "B1GQ"}, "A"),
    "zinsen":       ("irt_st_a", {"int_rt": "IRT_M3"}, "A"),
    "gini":         ("ilc_di12", {"age": "TOTAL"}, "A"),
    # Absoluter Maastricht-Schuldenstand (Mio. Euro), selber Datensatz wie die Schuldenquote, nur
    # unit MIO_EUR statt PC_GDP -> "Schuldenstand gesamt" (Mrd €, /1000) + Pro-Kopf (÷ Bevoelkerung).
    # Verifiziert DE (2025 = 2 838 238,9 Mio €).
    "schuldenstand_abs": ("gov_10dd_edpt1", {"unit": "MIO_EUR", "sector": "S13", "na_item": "GD"}, "A"),
    # Bevoelkerung am 1. Januar (demo_pjan; sex=T, age=TOTAL). freq/unit sind je 1 Auspraegung ->
    # sauber dekodierbar. Wird NICHT angezeigt, nur fuer die Pro-Kopf-Division (juengstes Jahr je Land).
    "bev":          ("demo_pjan", {"sex": "T", "age": "TOTAL"}, "A"),
}

# ANZEIGE-Kennzahlen: (key, Quell-fid, Anzeigename, Einheit, Nachkommastellen, Frequenz, higher_is_better).
# Quell-fid verweist auf eine BASE_SERIES-Serie ODER auf eine abgeleitete Serie (misery, bip_nominal,
# bip_wachstum_nom, aussenbeitrag, schuldenstand_gesamt, schuldenstand_pk), die in build_payload()
# erzeugt und in raw_by_id abgelegt wird. higher_is_better steuert, welches EU-Land als "bestes"
# bzw. "schlechtestes" gilt (True = hoeher ist besser, z. B. Wachstum; False = niedriger ist besser,
# z. B. Inflation/Arbeitslosigkeit/Schulden).
DISPLAY = [
    ("hvpi",             "hvpi",             "HVPI-Inflationsrate (Jahresrate)",              "%",         1, "M", False),
    ("arbeitslos",       "arbeitslos",       "Arbeitslosenquote (saisonbereinigt)",           "%",         1, "M", False),
    ("misery",           "misery",           "Misery-Index (Inflation + Arbeitslosenquote)",  "Punkte",    1, "M", False),
    ("hvpi_index",       "hvpi_index",       "HVPI (Index, 2015=100)",                        "Index",     1, "M", False),
    ("bip_wachstum",     "bip_real",         "Reales BIP-Wachstum (ggü. Vorjahresquartal)",   "%",         1, "Q", True),
    ("bip_wachstum_nom", "bip_wachstum_nom", "Nominales BIP-Wachstum (ggü. Vorjahr)",         "%",         1, "A", True),
    ("bip_nominal",      "bip_nominal",      "Nominales BIP (jeweilige Preise)",              "Mrd. €",    0, "A", True),
    ("leistungsbil",     "leistungsbil",     "Leistungsbilanzsaldo",                          "% des BIP", 1, "Q", True),
    ("aussenbeitrag",    "aussenbeitrag",    "Außenbeitrag (Nettoexporte)",                   "% des BIP", 1, "A", True),
    ("exporte",          "exporte",          "Exporte",                                       "% des BIP", 1, "A", True),
    ("importe",          "importe",          "Importe",                                       "% des BIP", 1, "A", True),
    ("schuldenquote",    "schulden",         "Staatsschuldenquote",                           "% des BIP", 1, "A", False),
    ("schuldenstand_ges","schuldenstand_gesamt", "Schuldenstand gesamt",                      "Mrd. €",    0, "A", False),
    ("schuldenstand_pk", "schuldenstand_pk", "Schuldenstand pro Kopf",                        "€",         0, "A", False),
    ("finanzsaldo",      "finanzsaldo",      "Staatl. Finanzierungssaldo",                    "% des BIP", 1, "A", True),
    ("staatsausgaben",   "staatsausg",       "Staatsausgabenquote",                           "% des BIP", 1, "A", True),
    ("staatseinnahmen",  "staatseinn",       "Staatseinnahmenquote",                          "% des BIP", 1, "A", True),
    ("zinsen_kurz",      "zinsen",           "Kurzfristige Zinsen (3-Monats-Satz)",           "%",         2, "A", True),
    ("gini",             "gini",             "Gini-Koeffizient (Einkommensungleichheit)",     "Punkte",    1, "A", False),
]

# Berechnungsformel + 1-Satz-Erlaeuterung je Kennzahl (unter dem Selektor angezeigt). Division als
# ÷, Multiplikation ×, Minus −. Fachlich korrekt; die Quotienten-Kennzahlen zeigen die kanonische
# Formel, auch wenn die Rohreihe bei Eurostat schon als %-Anteil vorliegt.
FORMULA = {
    "hvpi":            ("Inflationsrate = (HVPIₜ ÷ HVPIₜ₋₁₂ − 1) × 100 %",
                        "Prozentuale Veränderung des harmonisierten Verbraucherpreisindex gegenüber dem Vorjahresmonat."),
    "arbeitslos":      ("Arbeitslosenquote = Arbeitslose ÷ Erwerbspersonen × 100 %",
                        "Anteil der Arbeitslosen an allen Erwerbspersonen (saisonbereinigt, ILO-Konzept)."),
    "misery":          ("Misery-Index = Inflationsrate + Arbeitslosenquote",
                        "Summe aus Inflationsrate und Arbeitslosenquote — je höher, desto belastender für die Bevölkerung."),
    "hvpi_index":      ("HVPI-Index = Preisniveauₜ ÷ Preisniveau₂₀₁₅ × 100",
                        "Harmonisierter Verbraucherpreisindex; im Basisjahr 2015 = 100 — am =100-Punkt ist das Basisjahr erkennbar."),
    "bip_wachstum":    ("reales BIP-Wachstum = (BIPᵣₑₐₗ,ₜ ÷ BIPᵣₑₐₗ,Vorjahresquartal − 1) × 100 %",
                        "Preisbereinigte Veränderung des BIP gegenüber dem Vorjahresquartal."),
    "bip_wachstum_nom":("nominales BIP-Wachstum = (BIPₜ ÷ BIPₜ₋₁ − 1) × 100 %",
                        "Veränderung des BIP zu jeweiligen (laufenden) Preisen gegenüber dem Vorjahr — enthält den Preisanstieg."),
    "bip_nominal":     ("nominales BIP = Wert aller Endprodukte zu jeweiligen Preisen",
                        "Wert aller im Inland erzeugten Waren und Dienstleistungen zu laufenden Preisen (in Mrd. €)."),
    "leistungsbil":    ("Leistungsbilanzsaldo = Leistungsbilanz ÷ BIP × 100 %",
                        "Saldo aus Waren, Dienstleistungen, Primär- und Sekundäreinkommen gegenüber dem Ausland, in % des BIP."),
    "aussenbeitrag":   ("Außenbeitrag = (Exporte − Importe) ÷ BIP × 100 %",
                        "Nettoexporte (Exporte minus Importe) in % des BIP; positiv = Exportüberschuss."),
    "exporte":         ("Exportquote = Exporte ÷ BIP × 100 %",
                        "Wert der Exporte von Waren und Dienstleistungen in % des BIP."),
    "importe":         ("Importquote = Importe ÷ BIP × 100 %",
                        "Wert der Importe von Waren und Dienstleistungen in % des BIP."),
    "schuldenquote":   ("Schuldenquote = Staatsschulden ÷ BIP × 100 %",
                        "Öffentlicher Schuldenstand (Maastricht) in % des BIP; Referenzwert 60 %."),
    "schuldenstand_ges":("Schuldenstand gesamt = Maastricht-Schuldenstand (in Mrd. €)",
                        "Absoluter öffentlicher Schuldenstand des Gesamtstaats in Mrd. €."),
    "schuldenstand_pk":("Schuldenstand pro Kopf = Schuldenstand ÷ Bevölkerung",
                        "Öffentlicher Schuldenstand je Einwohner in €."),
    "finanzsaldo":     ("Finanzierungssaldo = (Einnahmen − Ausgaben) ÷ BIP × 100 %",
                        "Staatlicher Finanzierungssaldo in % des BIP; negativ = Defizit (Referenzwert −3 %)."),
    "staatsausgaben":  ("Staatsausgabenquote = Staatsausgaben ÷ BIP × 100 %",
                        "Gesamte Ausgaben des Staates in % des BIP."),
    "staatseinnahmen": ("Staatseinnahmenquote = Staatseinnahmen ÷ BIP × 100 %",
                        "Gesamte Einnahmen des Staates in % des BIP."),
    "zinsen_kurz":     ("kurzfristiger Zins = 3-Monats-Geldmarktsatz",
                        "Zinssatz für Dreimonatsgeld am Interbankenmarkt (in %)."),
    "gini":            ("Gini = Fläche zwischen Gleichverteilung und Lorenzkurve ÷ Fläche unter Gleichverteilung × 100",
                        "Maß der Einkommensungleichheit von 0 (völlig gleich) bis 100 (maximal ungleich)."),
}


def _since(freq):
    """sinceTimePeriod passend zur Frequenz — frueher als jeder Reihenbeginn (volle Historie, EIN Request)."""
    return HISTORY_SINCE.get(freq, "1970")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "quarto-eurostat-widget/3.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(io.TextIOWrapper(r, encoding="utf-8"))


def fetch(dataset, filters, since):
    """Ein Eurostat-Dataset holen -> ({geo: {period: value}}, {geo: dt.Label}).

    JSON-stat wird generisch geparst: der flache `value`-Array (als Dict, sparse) ist row-major
    ueber die Dimensionen in `id`-Reihenfolge (Groessen `size`) indexiert. Wir dekodieren jeden
    flachen Index in seine Dimensions-Positionen und lesen geo + time heraus. Alle uebrigen Dims
    sind per `filters` auf Groesse 1 gepinnt (s. BASE_SERIES).
    """
    qs = f"?format=JSON&lang=DE&sinceTimePeriod={since}"
    for k, v in filters.items():
        qs += f"&{k}={v}"
    d = _get(BASE + "/" + dataset + qs)
    ids, size = d["id"], d["size"]
    n = len(ids)
    strides = [1] * n
    for i in range(n - 2, -1, -1):
        strides[i] = strides[i + 1] * size[i + 1]
    gi, ti = ids.index("geo"), ids.index("time")
    geo_cat = d["dimension"]["geo"]["category"]
    time_cat = d["dimension"]["time"]["category"]
    ginv = {p: c for c, p in geo_cat["index"].items()}
    tinv = {p: c for c, p in time_cat["index"].items()}
    labels = geo_cat.get("label", {})
    out = {}
    for k, v in d["value"].items():
        if v is None:
            continue
        k = int(k)
        gpos = (k // strides[gi]) % size[gi]
        tpos = (k // strides[ti]) % size[ti]
        out.setdefault(ginv[gpos], {})[tinv[tpos]] = v
    return out, labels


def _combine(a, b, fn):
    """Elementweise zwei raw-Dicts ({geo:{period:val}}) auf gemeinsamen geo/period verknuepfen."""
    out = {}
    for g in set(a) & set(b):
        da, db = a[g], b[g]
        for p in set(da) & set(db):
            out.setdefault(g, {})[p] = fn(da[p], db[p])
    return out


def _yoy(raw):
    """Jahres-Veraenderungsrate (%) einer Jahresreihe ({geo:{'YYYY':val}}) — nur aufeinanderfolgende Jahre."""
    out = {}
    for g, dm in raw.items():
        yrs = sorted(dm)
        for i in range(1, len(yrs)):
            y, yp = yrs[i], yrs[i - 1]
            if int(y) == int(yp) + 1 and dm[yp]:
                out.setdefault(g, {})[y] = (dm[y] / dm[yp] - 1.0) * 100.0
    return out


def _bestworst(period_values, hib, dec):
    """period_values: {geo: value}. Bestes/schlechtestes EU-27-Land nach hib -> ({v,c}|None, {v,c}|None)."""
    vals = [(v, g) for g, v in period_values.items() if g in EU27 and v is not None]
    if not vals:
        return None, None
    hi, lo = max(vals), min(vals)
    b, w = (hi, lo) if hib else (lo, hi)
    return {"v": round(b[0], dec), "c": b[1]}, {"v": round(w[0], dec), "c": w[1]}


def build_series(raw, freq, dec, hib):
    """Aus einem raw-Dict ({geo:{period:val}}) die zwei Ansichten backen — je mit best/worst-Zeile.

    full = ALLE nativen Perioden (Monat/Quartal/Jahr) — traegt die 12-Monats-Ansicht (letzte
           FINE_N[freq]), die monatliche/quartalsweise Aufloesung ueber jeden Horizont UND die
           individuelle von-bis-Auswahl (beliebiger Ausschnitt, volle Historie).
    ann  = Jahresaufloesung, ALLE Jahre der Historie, je Jahr der JUENGSTE verfuegbare Wert (kein Ø) —
           traegt die 1/5/10-Jahres-Optionen sowie (bei monatlichen Kennzahlen im Jahres-Modus) die
           jaehrliche individuell-Auswahl bis zum fruehesten Jahr.
    Jede Ansicht traegt zusaetzlich `best`/`worst` (Liste je Periode: bestes/schlechtestes EU-27-Land
    als {v, c} nach hib, sonst None). Rueckgabe: (full, ann, asof, geos_mit_daten).
    """
    pset = set()
    for dm in raw.values():
        pset.update(dm.keys())
    allper = sorted(pset)
    annyears = sorted({p[:4] for p in allper})   # VOLLE Historie (alle Jahre), nicht mehr gekappt

    full_s, ann_s = {}, {}
    ann_val = {}          # geo -> {year: roher juengster Jahreswert} (fuer best/worst je Jahr)
    asof, geos = None, set()
    for g, dm in raw.items():
        full_s[g] = [round(dm[p], dec) if p in dm else None for p in allper]
        row, av = [], {}
        for y in annyears:
            cand = [p for p in dm if p[:4] == y]
            if cand:
                row.append(round(dm[max(cand)], dec)); av[y] = dm[max(cand)]
            else:
                row.append(None)
        ann_s[g] = row
        ann_val[g] = av
        gmax = max(dm) if dm else None
        if gmax and (asof is None or gmax > asof):
            asof = gmax
        if any(v is not None for v in full_s[g]) or any(v is not None for v in row):
            geos.add(g)

    full_best, full_worst = [], []
    for p in allper:
        b, w = _bestworst({g: dm.get(p) for g, dm in raw.items()}, hib, dec)
        full_best.append(b); full_worst.append(w)
    ann_best, ann_worst = [], []
    for y in annyears:
        b, w = _bestworst({g: av.get(y) for g, av in ann_val.items()}, hib, dec)
        ann_best.append(b); ann_worst.append(w)

    return ({"p": allper, "s": full_s, "best": full_best, "worst": full_worst},
            {"p": annyears, "s": ann_s, "best": ann_best, "worst": ann_worst},
            asof, geos)


def build_payload():
    labels_all = {}
    raw_by_id = {}
    for fid, (dataset, filters, freq) in BASE_SERIES.items():
        try:
            raw, labels = fetch(dataset, filters, _since(freq))
        except Exception as e:
            print(f"[WARN] {fid} ({dataset}): {e}")
            raw, labels = {}, {}
        raw_by_id[fid] = raw
        for g, lbl in labels.items():
            labels_all.setdefault(g, lbl)

    # Abgeleitete Serien (serverseitig, aus den Basis-raw-Dicts):
    #  misery      = HVPI-Inflation + Arbeitslosenquote (monatlich, je gemeinsamer Monat)
    #  bip_nominal = nominales BIP-Niveau in Mrd. € (CP_MEUR / 1000)
    #  bip_wachstum_nom = Vorjahresveraenderung der nominalen (current-price) BIP-Reihe
    #  aussenbeitrag    = Exporte - Importe (% BIP), da B11 bei Eurostat nicht publiziert ist
    raw_by_id["misery"] = _combine(raw_by_id.get("hvpi", {}), raw_by_id.get("arbeitslos", {}),
                                   lambda a, b: a + b)
    raw_by_id["bip_nominal"] = {g: {p: v / 1000.0 for p, v in d.items()}
                                for g, d in raw_by_id.get("gdp_cp", {}).items()}
    raw_by_id["bip_wachstum_nom"] = _yoy(raw_by_id.get("gdp_cp", {}))
    raw_by_id["aussenbeitrag"] = _combine(raw_by_id.get("exporte", {}), raw_by_id.get("importe", {}),
                                          lambda a, b: a - b)
    #  schuldenstand_gesamt = absoluter Schuldenstand in Mrd € (MIO_EUR / 1000)
    #  schuldenstand_pk     = Schuldenstand pro Kopf in € (MIO_EUR * 1e6 / Bevoelkerung), Bevoelkerung =
    #                         juengster verfuegbarer Jahreswert je Land (demo_pjan), fuer alle Jahre gleich.
    raw_by_id["schuldenstand_gesamt"] = {g: {p: v / 1000.0 for p, v in d.items()}
                                         for g, d in raw_by_id.get("schuldenstand_abs", {}).items()}
    pop_latest = {g: d[max(d)] for g, d in raw_by_id.get("bev", {}).items() if d}
    raw_by_id["schuldenstand_pk"] = {
        g: {p: v * 1e6 / pop_latest[g] for p, v in d.items()}
        for g, d in raw_by_id.get("schuldenstand_abs", {}).items() if g in pop_latest and pop_latest[g]}

    data = {}
    ind_meta = []
    geos_all = set()
    for key, src, name, unit, dec, freq, hib in DISPLAY:
        raw = raw_by_id.get(src, {})
        full, ann, asof, geos = build_series(raw, freq, dec, hib)
        data[key] = {"freq": freq, "asof": asof, "full": full, "ann": ann}
        geos_all |= geos
        fml, dsc = FORMULA.get(key, ("", ""))
        ind_meta.append({"key": key, "name": name, "unit": unit, "dec": dec, "freq": freq,
                         "hib": hib, "formula": fml, "desc": dsc})

    # Laender (Einzelstaaten) und Aggregate trennen, jeweils mit deutschem Label.
    countries, aggs = [], {}
    for g in geos_all:
        nm = labels_all.get(g, g)
        if g in AGG_CODES:
            aggs[g] = AGG_NAMES_DE.get(g, nm)
        else:
            countries.append([g, nm])
    countries.sort(key=lambda x: x[1])

    return {
        "countries": countries,
        "agg": aggs,
        "default": DEFAULT_COLS,
        "indicators": ind_meta,
        "data": data,
    }


def _summary(payload):
    parts = []
    for i in payload["indicators"]:
        d = payload["data"].get(i["key"], {})
        parts.append(f"{i['key']}[{i['freq']}]={d.get('asof') or '-'}")
    return ", ".join(parts)


def _slice_view(view, keep_years):
    """Eine Ansicht {p,s,best,worst} auf die letzten `keep_years` KALENDERJAHRE kappen.
    p ist aufsteigend sortiert -> die zu behaltenden Perioden bilden ein Suffix (die Jahreszahl im
    Praefix ist monoton nicht-fallend); alle Listen (s[geo], best, worst) sind index-parallel zu p,
    daher genuegt EIN gemeinsamer Tail-Slice ab dem ersten Index >= cutoff-Jahr."""
    p = view.get("p", [])
    if not p:
        return view
    cutoff = int(p[-1][:4]) - (keep_years - 1)
    i0 = 0
    for i, per in enumerate(p):
        if int(per[:4]) >= cutoff:
            i0 = i
            break
    return {"p": p[i0:],
            "s": {g: vals[i0:] for g, vals in view.get("s", {}).items()},
            "best": (view.get("best") or [])[i0:],
            "worst": (view.get("worst") or [])[i0:]}


def _slice_inline(payload, keep_years):
    """Kappt beide Ansichten je Kennzahl auf die letzten `keep_years` Jahre — NUR fuer den gebackenen
    Inline-Fallback: `full` (native Monats-/Quartals-/Jahresperioden) und `ann` (Jahresaufloesung).
    Der emit-json-Pfad ruft dies NICHT auf (Vollhistorie fuer GitHub)."""
    out = dict(payload)
    new_data = {}
    for key, d in payload["data"].items():
        nd = dict(d)
        nd["full"] = _slice_view(d.get("full", {}), keep_years)
        nd["ann"] = _slice_view(d.get("ann", {}), keep_years)
        new_data[key] = nd
    out["data"] = new_data
    return out


def main():
    args = sys.argv[1:]
    if args and args[0] == "--emit-json":
        payload = build_payload()
        out = args[1] if len(args) > 1 else "eurostat-stats.json"
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        print(f"[OK] {out} — {len(payload['countries'])} Laender, {len(payload['agg'])} Aggregate, "
              f"{len(payload['indicators'])} Kennzahlen | {_summary(payload)}")
        return
    if not args:
        print("Aufruf: python _assets/eurostat-widget.py <bpe-ordner> | --emit-json <datei>")
        sys.exit(2)
    target = args[0].rstrip("/\\")
    payload = build_payload()
    # Inline-Bake NUR auf die letzten INLINE_YEARS Jahre je Reihe kappen (kleiner Fallback);
    # --emit-json oben bleibt VOLLHISTORIE (fuer GitHub). Nur der gebackene Datensatz wird geslict.
    inline = _slice_inline(payload, INLINE_YEARS)
    data_js = json.dumps(inline, ensure_ascii=False, separators=(",", ":"))
    out = (TEMPLATE.replace("/*__DATA__*/", data_js)
                   .replace("__REPO__", GITHUB_STATS_REPO))
    with open(target + "/_eurostat-widget.qmd", "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print(f"[OK] {target}/_eurostat-widget.qmd — {len(payload['countries'])} Laender, "
          f"{len(payload['agg'])} Aggregate, {len(payload['indicators'])} Kennzahlen "
          f"(Inline-Fallback letzte {INLINE_YEARS} J., emit-json Vollhistorie) | "
          f"{_summary(payload)} | Live-Repo: {GITHUB_STATS_REPO or '(nur gebacken)'}")


TEMPLATE = r'''::: {.content-visible when-format="html"}
```{=html}
<div class="es-stats" id="es-stats">
  <h3 style="margin:.2rem 0">Europäische Kennzahlen im Vergleich <span style="font-weight:400;font-size:.8em;color:#666">(Eurostat — Monats-, Quartals- &amp; Jahreswerte, alle Länder wählbar)</span></h3>
  <div class="es-controls" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:center;margin:.4rem 0">
    <label>Zeithorizont:
      <select id="es-hz"><option value="1y">letztes Jahr</option><option value="5y">letzte 5 Jahre</option><option value="10y">letzte 10 Jahre</option><option value="custom">individuell (von–bis)</option></select>
    </label><span id="es-customwrap" style="display:none;gap:.4rem;align-items:center"><label>Start: <select id="es-cstart"></select></label><label>Ende: <select id="es-cend"></select></label></span><span id="es-range" style="color:#1565c0;font-weight:600;font-size:.9em"></span>
    <label>Kennzahl: <select id="es-ind" style="max-width:22rem"></select></label>
    <label id="es-mjwrap" style="display:none">Auflösung: <select id="es-mj" style="margin-left:.3rem"><option value="M">monatlich</option><option value="A">jährlich</option></select></label>
    <label>Diagramm: <select id="es-chart"><option value="line">Linie (Zeitreihe)</option><option value="bar">Balken (letzter Wert)</option><option value="column">Säulen (letzter Wert)</option></select></label>
  </div>
  <div id="es-formula" style="display:none;font-size:.85em;color:#333;margin:.1rem 0 .4rem;padding:.35rem .6rem;background:#f5f7fa;border-left:3px solid #1565c0"></div>
  <details style="margin:.3rem 0"><summary style="cursor:pointer;font-weight:600">Länder wählen</summary>
    <div style="margin:.4rem 0"><button type="button" id="es-all" style="cursor:pointer">Alle</button> <button type="button" id="es-none" style="cursor:pointer">Keine</button></div>
    <input id="es-search" type="text" placeholder="Land suchen…" style="margin:.4rem 0;padding:.2rem;width:14rem">
    <div id="es-cty" style="display:flex;flex-wrap:wrap;gap:.2rem .9rem;max-height:11rem;overflow:auto;font-size:.83em;border:1px solid #ddd;padding:.4rem"></div>
  </details>
  <div style="overflow-x:auto"><div id="es-table"></div></div>
  <details style="margin:.5rem 0"><summary style="cursor:pointer;font-weight:600;font-size:.85em;color:#555">Hinweise &amp; Methodik</summary>
  <p style="font-size:.78em;color:#666;margin:.3rem 0">Wählen Sie <strong>Zeithorizont</strong> und <strong>Kennzahl</strong>: Die Matrix zeigt je gewähltem Land/Aggregat (Zeile) und Periode (Spalte) den <strong>konkreten Einzelwert</strong> (kein Durchschnitt), das Liniendiagramm den Verlauf; klicken Sie ein Land in „Länder wählen" an. Bei <strong>„letztes Jahr / 5 / 10 Jahre"</strong> gilt <strong>Jahresauflösung</strong> (je Jahr der jüngste verfügbare Wert). Mit <strong>„individuell (von–bis)"</strong> wählen Sie <strong>Start</strong> und <strong>Ende</strong> in der nativen Auflösung der Kennzahl (Monat/Quartal/Jahr); die Matrix zeigt alle Einzelperioden im Bereich (bei vielen Spalten in mehrere gestapelte Teil-Tabellen aufgeteilt), das Liniendiagramm die ganze Reihe — die individuell-Auswahl reicht bis zum <strong>frühesten verfügbaren Zeitpunkt</strong> der Reihe zurück. Bei <strong>monatlich</strong> geführten Kennzahlen (HVPI-Inflation, Arbeitslosenquote, Misery-Index, HVPI-Index) schalten Sie mit <strong>Auflösung</strong> zwischen monatlichen und jährlichen (Jahresend-)Werten um — <strong>keine Durchschnitte</strong>; die Auflösung folgt dieser Wahl über Zeithorizont und individuell-Auswahl. Über <strong>Alle</strong>/<strong>Keine</strong> wählen Sie alle Länder/Aggregate auf einmal aus bzw. ab; ein Klick auf einen <strong>Spaltenkopf</strong> sortiert die Tabelle aufsteigend, ein weiterer absteigend (▲/▼, „–" ans Ende). Direkt unter dem Selektor steht die <strong>Berechnungsformel</strong> der gewählten Kennzahl mit kurzer Erläuterung. Zusätzlich wählbar: <strong>bestes/schlechtestes EU-Land</strong> je Kennzahl und Periode (aus den EU-27; der Ländername steht im Zeilenkopf und je Zelle) — „bestes"/„schlechtestes" je nachdem, ob bei der Kennzahl ein höherer oder niedrigerer Wert günstiger ist. Quelle: <strong>Eurostat</strong> (JSON-stat API). <strong>Methodik:</strong> Eurostat rechnet harmonisiert (HVPI statt nationalem VPI; Staatskennzahlen nach ESA&nbsp;2010/EDP; Anteile am BIP zu jeweiligen Preisen) — Werte können daher von Weltbank/IWF abweichen. Nominales BIP = jeweilige (laufende) Preise, nominales Wachstum = Vorjahresveränderung dieser Reihe; reales Wachstum ist preisbereinigt. Außenbeitrag = Exporte − Importe. Misery-Index = HVPI-Inflation + Arbeitslosenquote (serverseitig). HVPI-Index: 2015 = 100 (am =100-Punkt ist das Basisjahr erkennbar). Stand je Kennzahl: <span id="es-asof"></span>.</p>
  </details>
  <div id="es-canvaswrap" style="position:relative;height:360px;max-width:820px;margin-top:.4rem"><canvas id="es-canvas"></canvas></div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
(function(){
  var S = /*__DATA__*/;
  var REPO = "__REPO__";
  var el=document.getElementById('es-stats'); if(!el) return;
  var FREQNAME={M:'monatlich',Q:'vierteljährlich',A:'jährlich'};
  var MON=['Jan','Feb','Mär','Apr','Mai','Jun','Jul','Aug','Sep','Okt','Nov','Dez'];
  var HZN={'1y':1,'5y':5,'10y':10};      // Jahre in der Jahresaufloesung (ann)
  var MAXCOLS=12;                        // max. Perioden-Spalten je (Teil-)Tabelle -> sonst stapeln
  // Bestes/schlechtestes EU-Land als eigene, auswaehlbare "Spalten" (wie im WB-Widget).
  var SPECIAL=[['BEST','bestes EU-Land'],['WORST','schlechtestes EU-Land']];
  // mj = Aufloesung fuer MONATLICHE Kennzahlen: 'M' monatlich | 'A' jaehrlich (Jahresendwert, kein Ø).
  // sort = {key:'name'|Periode, dir:1|-1} — Tabellen-Spaltensortierung (null = natuerliche Reihenfolge).
  var state={hz:'1y',chart:'line',sel:null,cty:{},cstart:null,cend:null,mj:'M',sort:null};
  function initState(){ state.cty={}; (S.default||['DE']).forEach(function(c){state.cty[c]=true;});
    state.sel=(S.indicators[0]||{}).key; state.cstart=null; state.cend=null; state.mj='M'; state.sort=null; }
  function isMonthly(key){ return (S.data[key]||{}).freq==='M'; }
  function effRes(d){ return d.freq==='M' ? state.mj : d.freq; }
  function cname(c){ if(c==='BEST')return 'bestes EU-Land'; if(c==='WORST')return 'schlechtestes EU-Land';
    if(S.agg&&S.agg[c])return S.agg[c];
    var f=S.countries.find(function(x){return x[0]===c;}); return f?f[1]:c; }
  function isAgg(c){ return !!(S.agg&&S.agg[c]); }
  function isSpecial(c){ return c==='BEST'||c==='WORST'; }
  function meta(key){ return S.indicators.find(function(i){return i.key===key;})||{}; }
  function activeCols(){ var c=[];
    Object.keys(S.agg||{}).sort(function(a,b){ var na=cname(a).toLowerCase(), nb=cname(b).toLowerCase();
      return na<nb?-1:(na>nb?1:0); }).forEach(function(a){ if(state.cty[a])c.push(a); });
    S.countries.forEach(function(x){ if(state.cty[x[0]])c.push(x[0]); });
    ['BEST','WORST'].forEach(function(s){ if(state.cty[s])c.push(s); }); return c; }
  // Wert einer Zelle: normale Entitaet -> s[col][j]; BEST/WORST -> best/worst[j].v (EU-Land-Wert).
  function cellVal(v,c,j){ if(c==='BEST'){var b=v.best[j];return b?b.v:null;}
    if(c==='WORST'){var w=v.worst[j];return w?w.v:null;} var s=v.s[c]; return s?s[j]:null; }
  // Name des besten/schlechtesten EU-Landes in Periode j bzw. fuer die juengste belegte Periode.
  function euName(v,which,j){ var e=(which==='BEST'?v.best:v.worst)[j]; return e?cname(e.c):null; }
  function euNameLatest(v,which){ for(var i=(v.p||[]).length-1;i>=0;i--){var n=euName(v,which,i); if(n)return n;} return null; }
  // Ansicht je Kennzahl+Horizont: {p:[Perioden], s:{geo:[Werte]}, best:[…], worst:[…]}.
  //  1/5/10y = letzte 1/5/10 Jahre der Jahresaufloesung (ann); monatliche Kennzahl im Monats-Modus:
  //            letzte span*12 Monatswerte der nativen (full) Serie
  //  custom  = beliebiger von-bis-Ausschnitt der nativen (full) Serie
  // IMMER konkrete Einzelwerte, nie Ø.
  function sliceEnd(o,n){ var s={}; Object.keys(o.s||{}).forEach(function(g){s[g]=(o.s[g]||[]).slice(-n);});
    return {p:(o.p||[]).slice(-n),s:s,best:(o.best||[]).slice(-n),worst:(o.worst||[]).slice(-n)}; }
  function sliceRange(o,i0,i1){ var s={}; Object.keys(o.s||{}).forEach(function(g){s[g]=(o.s[g]||[]).slice(i0,i1+1);});
    return {p:(o.p||[]).slice(i0,i1+1),s:s,best:(o.best||[]).slice(i0,i1+1),worst:(o.worst||[]).slice(i0,i1+1)}; }
  // Basisreihe fuer custom: bei MONATLICHER Kennzahl im Jahres-Modus die Jahresreihe (ann),
  // sonst die native (full). So folgt die Aufloesung der Umschalter-Wahl.
  function baseSeries(d){ return (d.freq==='M' && state.mj==='A') ? (d.ann||{p:[],s:{},best:[],worst:[]})
                                                                  : (d.full||{p:[],s:{},best:[],worst:[]}); }
  function view(key){ var d=S.data[key]; if(!d) return {p:[],s:{},best:[],worst:[]};
    var ann=d.ann||{p:[],s:{},best:[],worst:[]}, base=baseSeries(d);
    if(state.hz==='custom'){ var p=base.p||[], i0=p.indexOf(state.cstart), i1=p.indexOf(state.cend);
      if(i0<0)i0=0; if(i1<0)i1=p.length-1; if(i1<i0){var t=i0;i0=i1;i1=t;}
      return sliceRange(base,i0,i1); }
    // 1/5/10 Jahre: monatliche Kennzahl im Monats-Modus -> monatliche Aufloesung ueber die Spanne;
    // sonst Jahresaufloesung (letzter Wert je Jahr).
    var span=HZN[state.hz]||5;
    if(d.freq==='M' && state.mj==='M') return sliceEnd(d.full||ann,span*12);
    return sliceEnd(ann,span); }
  function flabel(p){ if(/^\d{4}$/.test(p))return p;
    var q=/^(\d{4})-Q(\d)$/.exec(p); if(q)return 'Q'+q[2]+' '+q[1];
    var m=/^(\d{4})-(\d{2})$/.exec(p); if(m)return MON[(+m[2])-1]+' '+m[1]; return p; }
  function rangeStr(v){ var p=v.p||[]; if(!p.length)return '–'; if(p.length===1)return flabel(p[0]);
    if(/^\d{4}$/.test(p[0]))return p[0]+'–'+p[p.length-1];
    return flabel(p[0])+' – '+flabel(p[p.length-1]); }
  function resNote(d){ var freq=d.freq;
    if(state.hz==='custom'){ var res=effRes(d);
      if(res==='M')return 'monatlich'; if(res==='Q')return 'vierteljährlich';
      return (freq==='A')?'jährlich':'Jahresauflösung (je Jahr letzter Wert)'; }
    if(freq==='M'&&state.mj==='M')return 'monatlich';
    return (freq==='A')?'jährlich':'Jahresauflösung (je Jahr letzter Wert)'; }
  function lastVal(arr){ if(!arr)return null; for(var i=arr.length-1;i>=0;i--){ if(arr[i]!=null)return arr[i]; } return null; }
  // Juengster konkreter Einzelwert einer Entitaet im Fenster (fuer Balken/Saeulen), auch BEST/WORST.
  function spotVal(v,c){ for(var j=(v.p||[]).length-1;j>=0;j--){ var x=cellVal(v,c,j); if(x!=null)return x; } return null; }
  function fmt(v,u,dec){ if(v==null)return '–'; if(dec==null)dec=1;
    var n=Math.round(v*Math.pow(10,dec))/Math.pow(10,dec), parts=n.toFixed(dec).split('.');
    parts[0]=parts[0].replace(/\B(?=(\d{3})+(?!\d))/g,'.');
    var s=parts.length>1?parts[0]+','+parts[1]:parts[0];
    return s+((''+u).indexOf('%')===0?' %':''); }
  function renderRange(){ var t=document.getElementById('es-range'); if(!t)return;
    var d=S.data[state.sel]||{}, v=view(state.sel);
    t.textContent=rangeStr(v)+' · '+resNote(d); }
  // Zeilenkopf je Entitaet; BEST/WORST tragen den Laendernamen der juengsten belegten Periode.
  function rowHead(c,v){
    if(c==='BEST'){ var nb=euNameLatest(v,'BEST'); return (nb?nb+' — ':'')+'bestes EU-Land'; }
    if(c==='WORST'){ var nw=euNameLatest(v,'WORST'); return (nw?nw+' — ':'')+'schlechtestes EU-Land'; }
    return isAgg(c)?'<strong>'+cname(c)+'</strong>':cname(c); }
  // Sortierung: state.sort={key:'name'|Periode, dir:1|-1}. Klick auf Spaltenkopf -> auf-, erneut absteigend.
  // Erste Spalte alphabetisch; fehlende Werte ("–") immer ans Ende; ueber Split-Tabellen konsistent
  // (globale Zeilenreihenfolge, in jedem Chunk gleich).
  function sortedCols(v){ var cols=activeCols(); if(!state.sort) return cols;
    var sk=state.sort.key, dir=state.sort.dir, arr=cols.slice();
    if(sk==='name'){ arr.sort(function(a,b){ var na=cname(a).toLowerCase(), nb=cname(b).toLowerCase();
        return na<nb?-1:(na>nb?1:0); }); if(dir<0)arr.reverse(); return arr; }
    var j=(v.p||[]).indexOf(sk); if(j<0) return cols;
    arr.sort(function(a,b){ var xa=cellVal(v,a,j), xb=cellVal(v,b,j);
      if(xa==null&&xb==null)return 0; if(xa==null)return 1; if(xb==null)return -1;
      return dir*(xa-xb); }); return arr; }
  function arrowFor(k){ return (state.sort&&state.sort.key===k)?(state.sort.dir>0?' ▲':' ▼'):''; }
  // Matrix: Zeilen = gewaehlte Entitaeten (inkl. bestes/schlechtestes EU-Land), Spalten = Perioden.
  // Bei > MAXCOLS Perioden in mehrere, untereinander gestapelte Teil-Tabellen aufteilen (Koepfe wiederholt).
  function renderTable(){
    var key=state.sel, mi=meta(key), v=view(key), P=v.p||[];
    if(state.sort&&state.sort.key!=='name'&&P.indexOf(state.sort.key)<0) state.sort=null; // stale Periodenschluessel
    var cols=sortedCols(v);
    var nchunks=Math.max(1,Math.ceil(P.length/MAXCOLS)), html='';
    for(var ci=0;ci<nchunks;ci++){
      var a=ci*MAXCOLS, b=Math.min(P.length,a+MAXCOLS);
      var h='<table class="table" style="font-size:.85em;margin:0 0 .5rem">';
      if(nchunks>1) h+='<caption style="caption-side:top;text-align:left;color:#1565c0;font-weight:600;padding:.1rem 0">Teil '+(ci+1)+' von '+nchunks+'</caption>';
      h+='<thead><tr><th data-sk="name" style="text-align:left;cursor:pointer" title="alphabetisch sortieren">Land / Aggregat'+arrowFor('name')+'</th>';
      for(var j=a;j<b;j++){ h+='<th data-sk="'+P[j]+'" style="text-align:right;cursor:pointer" title="nach dieser Spalte sortieren">'+flabel(P[j])+arrowFor(P[j])+'</th>'; }
      h+='</tr></thead><tbody>';
      cols.forEach(function(c){
        h+='<tr><td style="text-align:left">'+rowHead(c,v)+'</td>';
        for(var j=a;j<b;j++){
          var val=cellVal(v,c,j), cell=fmt(val,mi.unit,mi.dec);
          if(isSpecial(c)&&val!=null){ var nm=euName(v,c,j);
            if(nm) cell='<span title="'+nm+'">'+cell+'<br><span style="font-size:.8em;color:#888">'+nm+'</span></span>'; }
          h+='<td style="text-align:right">'+cell+'</td>';
        }
        h+='</tr>';
      });
      h+='</tbody></table>'; html+=h;
    }
    var tbl=document.getElementById('es-table'); tbl.innerHTML=html;
    Array.prototype.forEach.call(tbl.querySelectorAll('th[data-sk]'),function(th){
      th.onclick=function(){ var k=th.getAttribute('data-sk');
        if(state.sort&&state.sort.key===k) state.sort.dir=-state.sort.dir; else state.sort={key:k,dir:1};
        renderTable(); }; });
  }
  var chart=null;
  function draw(){
    var key=state.sel; if(!key)return; var mi=meta(key), v=view(key), cols=activeCols();
    var pal=['#1565c0','#c0392b','#2e7d32','#f39c12','#6a1b9a','#00838f','#5d4037','#455a64','#ad1457','#1b5e20'];
    // Je Reihe zusaetzlich zur Farbe ein borderDash- UND pointStyle-Zyklus -> im Graustufendruck
    // unterscheidbar (Farbe bleibt, nur redundant). Beide Zyklen laufen je Reihe eins weiter.
    var dash=[[],[6,4],[2,3],[9,3,2,3],[1,3],[12,3,3,3]];
    var pts=['circle','rect','triangle','rectRot','star','crossRot','line'];
    var wrap=document.getElementById('es-canvaswrap');
    var ctx=document.getElementById('es-canvas').getContext('2d'); var cfg; var ttl=mi.name+' ('+mi.unit+')';
    if(state.chart==='line'){
      var labs=v.p.map(flabel), pr=(v.p.length>18?0:4);
      cfg={type:'line',data:{labels:labs,datasets:cols.map(function(c,ix){var sp=(isAgg(c)||isSpecial(c));return {
        label:cname(c),borderColor:pal[ix%10],backgroundColor:pal[ix%10],
        borderDash:dash[ix%dash.length],borderWidth:sp?2.6:1.6,
        pointStyle:pts[ix%pts.length],pointRadius:pr,pointHoverRadius:pr+2,
        fill:false,tension:.2,spanGaps:true,
        data:v.p.map(function(_,j){return cellVal(v,c,j);})};})},
        options:{maintainAspectRatio:false,plugins:{legend:{labels:{usePointStyle:true}}},scales:{x:{ticks:{maxRotation:90,minRotation:0,autoSkip:true,maxTicksLimit:18}}}}};
      wrap.style.height='360px';
    } else {
      ttl+=' — '+(v.p.length?flabel(v.p[v.p.length-1]):'');
      cfg={type:'bar',data:{labels:cols.map(cname),datasets:[{label:mi.name,backgroundColor:pal,
        barThickness:22,maxBarThickness:24,data:cols.map(function(c){return spotVal(v,c);})}]},
        options:{maintainAspectRatio:false,indexAxis:state.chart==='bar'?'y':'x',plugins:{legend:{display:false}}}};
      // feste Balkendicke -> Chart-Hoehe waechst mit der Laenderzahl (nur horizontale Balken).
      wrap.style.height=(state.chart==='bar' ? Math.max(200,70+cols.length*34) : 360)+'px';
    }
    cfg.options=cfg.options||{}; cfg.options.responsive=true;
    cfg.options.plugins=Object.assign({title:{display:true,text:ttl}},cfg.options.plugins||{});
    if(chart)chart.destroy(); chart=new Chart(ctx,cfg);
  }
  function renderCty(){
    var box=document.getElementById('es-cty'); var q=(document.getElementById('es-search').value||'').toLowerCase();
    var aggList=Object.keys(S.agg||{}).map(function(a){return [a,S.agg[a]];})
      .sort(function(a,b){return a[1]<b[1]?-1:1;});
    var list=SPECIAL.concat(aggList).concat(S.countries);
    box.innerHTML=list.filter(function(x){return q===''||x[1].toLowerCase().indexOf(q)>=0;}).map(function(x){
      var bold=isSpecial(x[0])||isAgg(x[0]);
      return '<label style="width:12rem"><input type="checkbox" data-c="'+x[0]+'"'+(state.cty[x[0]]?' checked':'')
        +'> '+(bold?'<strong>'+x[1]+'</strong>':x[1])+'</label>';
    }).join('');
    Array.prototype.forEach.call(box.querySelectorAll('input[data-c]'),function(cb){
      cb.onchange=function(){var c=cb.getAttribute('data-c'); if(cb.checked)state.cty[c]=true; else delete state.cty[c]; renderTable();draw();};});
  }
  function renderIndSelect(){
    var sel=document.getElementById('es-ind'); sel.innerHTML='';
    var inds=(S.indicators||[]).slice().sort(function(a,b){ var na=a.name.toLowerCase(), nb=b.name.toLowerCase();
      return na<nb?-1:(na>nb?1:0); });
    inds.forEach(function(i){ var o=document.createElement('option');
      o.value=i.key; o.textContent=i.name+' ('+i.unit+')'; if(i.key===state.sel)o.selected=true; sel.appendChild(o); });
    sel.onchange=function(e){ state.sel=e.target.value; updateMjUI(); renderFormula();
      if(state.hz==='custom')populateCustom(); renderRange(); renderTable(); draw(); };
  }
  // Berechnungsformel + 1-Satz-Erlaeuterung der gewaehlten Kennzahl unter dem Selektor.
  function renderFormula(){ var f=document.getElementById('es-formula'); if(!f)return;
    var mi=meta(state.sel); if(!mi||!mi.formula){ f.style.display='none'; f.innerHTML=''; return; }
    f.style.display='block';
    f.innerHTML='<strong>Formel:</strong> '+mi.formula+(mi.desc?' &nbsp;<span style="color:#666">'+mi.desc+'</span>':''); }
  // M/J-Umschalter nur bei monatlich gefuehrten Kennzahlen zeigen (sonst ausgeblendet).
  function updateMjUI(){ var w=document.getElementById('es-mjwrap'); if(!w)return;
    w.style.display=isMonthly(state.sel)?'inline-flex':'none';
    var mj=document.getElementById('es-mj'); if(mj)mj.value=state.mj; }
  // Start/Ende-Dropdowns aus den nativen Perioden der gewaehlten Kennzahl fuellen (von-bis).
  function populateCustom(){ var d=S.data[state.sel]||{}, p=(baseSeries(d)||{}).p||[];
    var cs=document.getElementById('es-cstart'), ce=document.getElementById('es-cend'); if(!cs||!ce)return;
    var opts=p.map(function(pp){return '<option value="'+pp+'">'+flabel(pp)+'</option>';}).join('');
    cs.innerHTML=opts; ce.innerHTML=opts;
    if(p.indexOf(state.cstart)<0) state.cstart=p.length?p[0]:null;
    if(p.indexOf(state.cend)<0) state.cend=p.length?p[p.length-1]:null;
    if(state.cstart!=null)cs.value=state.cstart; if(state.cend!=null)ce.value=state.cend; }
  function updateHzUI(){ var w=document.getElementById('es-customwrap');
    if(w) w.style.display=(state.hz==='custom')?'inline-flex':'none';
    if(state.hz==='custom') populateCustom(); }
  document.getElementById('es-hz').onchange=function(e){state.hz=e.target.value;updateHzUI();renderRange();renderTable();draw();};
  document.getElementById('es-cstart').onchange=function(e){state.cstart=e.target.value;renderRange();renderTable();draw();};
  document.getElementById('es-cend').onchange=function(e){state.cend=e.target.value;renderRange();renderTable();draw();};
  document.getElementById('es-chart').onchange=function(e){state.chart=e.target.value;draw();};
  document.getElementById('es-search').oninput=renderCty;
  // Aufloesungs-Umschalter (monatlich<->jaehrlich): Periodenmenge wechselt (Monat<->Jahr) -> custom zuruecksetzen.
  document.getElementById('es-mj').onchange=function(e){ state.mj=e.target.value; state.cstart=null; state.cend=null;
    if(state.hz==='custom')populateCustom(); renderRange(); renderTable(); draw(); };
  function selectAll(v){ state.cty={};
    if(v){ ['BEST','WORST'].forEach(function(s){state.cty[s]=true;});
      Object.keys(S.agg||{}).forEach(function(a){state.cty[a]=true;});
      S.countries.forEach(function(x){state.cty[x[0]]=true;}); }
    renderCty(); renderTable(); draw(); }
  document.getElementById('es-all').onclick=function(){selectAll(true);};
  document.getElementById('es-none').onclick=function(){selectAll(false);};
  function boot(){ document.getElementById('es-hz').value=state.hz; document.getElementById('es-chart').value=state.chart;
    var mj=document.getElementById('es-mj'); if(mj)mj.value=state.mj;
    document.getElementById('es-asof').textContent=S.indicators.map(function(i){var d=S.data[i.key]||{};return i.name.replace(/\s*\(.*/,'')+' '+(FREQNAME[d.freq]||'')+' '+(d.asof||'–');}).join(' · ');
    renderIndSelect(); updateMjUI(); renderFormula(); updateHzUI(); renderCty(); renderRange(); renderTable(); draw(); }
  initState(); boot();
  // Live-Layer (regelmaessige Aktualisierung via GitHub, fail-safe): ersetzt die gebackenen
  // (15-Jahre-)Fallback-Daten durch die Vollhistorie. Nach S=j baut populateCustom() die Start-/Ende-
  // Dropdowns aus den nun vollen Perioden neu auf (voller Zeitraum waehlbar, auch vor dem Umschalten
  // auf "individuell"); boot() rendert Selektor, Zeitraum, Matrix und Diagramm neu. Fehlender/
  // fehlgeschlagener Fetch -> 15-Jahre-Fallback bleibt.
  if(REPO){ fetch("https://raw.githubusercontent.com/"+REPO+"/main/eurostat-stats.json",{cache:"no-store"})
    .then(function(r){ if(!r.ok) throw 0; return r.json(); })
    .then(function(j){ if(j&&j.data&&j.indicators){ S=j; initState(); boot(); populateCustom(); } }).catch(function(){}); }
})();
</script>
```
:::
'''

if __name__ == "__main__":
    main()
