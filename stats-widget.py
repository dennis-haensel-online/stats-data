#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stats-widget.py — backt ein HTML-Statistik-Vergleichs-Widget aus der Weltbank-API.

Volkswirtschaftliche Standard-Kennzahlen (BPE 19-22) fuer ALLE Laender + EU-Durchschnitt +
bestes/schlechtestes EU-Land, aus EINER Quelle (Weltbank Indicators API, anonym, kein Key —
s. AGENTS.md "Wirtschaftskennzahlen"). Jahreswerte.

Zwei Ausgabemodi:
  python _assets/stats-widget.py <bpe-ordner>            -> Include `_stats-widget.qmd` (Widget +
        kompakt gebackene Fallback-Daten fuer ALLE Laender + optionaler Live-Fetch von GitHub).
  python _assets/stats-widget.py --emit-json <datei>     -> nur die JSON (fuer die GitHub-Action,
        die sie jaehrlich neu backt; das Widget holt sie dann live, s. _assets/stats-github/).

Auto-Update (jaehrlich, s. #6): identisches Muster wie der Newsticker — eine GitHub-Action legt die
`wb-stats.json` in ein oeffentliches Daten-Repo, das Widget fetcht sie clientseitig
(`cache:"no-store"`) und ersetzt die gebackene Fallback-Schicht. Leeres GITHUB_STATS_REPO => nur
gebacken (die Seite bleibt schnell: async Fetch, unter dem Fold, Fallback rendert sofort).
"""
import sys, json, urllib.request, io, datetime

BASE = "https://api.worldbank.org/v2"
# Volle Historie: je Kennzahl von FIRST_YEAR bis heute (WB-Weltentwicklungsindikatoren beginnen ~1960).
# Damit reichen die Von-/Bis-Dropdowns der individuell-Auswahl bis zum fruehesten API-Jahr zurueck.
# Die Vorgabe-Optionen (letztes Jahr / 5 / 10 Jahre) rechnet das Widget clientseitig aus S.years.
FIRST_YEAR = 1960
LAST_YEAR = datetime.date.today().year

# Der gebackene INLINE-Fallback (in die _*.qmd geschriebener Datensatz) wird auf die letzten
# INLINE_YEARS Jahre gekappt -> kleine, schnelle Seite. Der --emit-json-Pfad bleibt VOLLHISTORIE
# (GitHub-Live). Die Vorgabe-Optionen (1/5/10 Jahre) + individuell reichen im Fallback 15 Jahre zurueck.
INLINE_YEARS = 15

# Oeffentliches Daten-Repo fuer den Live-Layer (Setup s. _assets/stats-github/README.md).
# Leer => Seite nur gebacken. Gemeinsames Daten-Repo mit dem Eurostat- und dem Newsticker-Widget.
GITHUB_STATS_REPO = "dennis-haensel-online/stats-data"

EU_AGG = "EU"           # Weltbank-Code fuer "European Union" (Durchschnitt)
EU27 = ["AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE","IT",
        "LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE"]
DEFAULT_COLS = ["DE"]   # Vorgabe: nur Deutschland sichtbar (absolute Zahlen)

# Deutsche Laendernamen fuer die wichtigsten Vergleichslaender; sonst engl. WB-Name als Fallback.
NAMES_DE = {
 "DE":"Deutschland","FR":"Frankreich","IT":"Italien","GB":"Großbritannien","US":"USA","AT":"Österreich",
 "BE":"Belgien","NL":"Niederlande","LU":"Luxemburg","DK":"Dänemark","SE":"Schweden","FI":"Finnland",
 "PL":"Polen","CZ":"Tschechien","SK":"Slowakei","HU":"Ungarn","RO":"Rumänien","BG":"Bulgarien",
 "GR":"Griechenland","ES":"Spanien","PT":"Portugal","IE":"Irland","HR":"Kroatien","SI":"Slowenien",
 "EE":"Estland","LV":"Lettland","LT":"Litauen","CY":"Zypern","MT":"Malta","CH":"Schweiz","NO":"Norwegen",
 "JP":"Japan","CN":"China","RU":"Russland","TR":"Türkei","CA":"Kanada","BR":"Brasilien","IN":"Indien",
}

# key -> (WB-Indikator, Anzeigename, Einheit, higher_is_better, grp abs/rel/"")
INDICATORS = [
    ("bip_wachstum", "NY.GDP.MKTP.KD.ZG", "BIP-Wachstum real", "%", True, ""),
    ("inflation",    "FP.CPI.TOTL.ZG",    "Inflationsrate (VPI)", "%", False, ""),
    ("arbeitslos",   "SL.UEM.TOTL.ZS",    "Arbeitslosenquote", "%", False, ""),
    ("leistungsbil", "BN.CAB.XOKA.GD.ZS", "Leistungsbilanzsaldo", "% des BIP", True, ""),
    # Aussenwirtschaft: Aussenbeitrag/Nettoexporte (NX = Ex - Im, Handels-/Dienstleistungsbilanz) ist NICHT
    # der Leistungsbilanzsaldo — die Leistungsbilanz enthaelt zusaetzlich Primaer-/Sekundaereinkommen.
    ("aussenbeitrag", "NE.RSB.GNFS.ZS",   "Außenbeitrag (Nettoexporte)", "% des BIP", True, ""),
    ("exporte",       "NE.EXP.GNFS.ZS",   "Exporte", "% des BIP", True, ""),
    ("importe",       "NE.IMP.GNFS.ZS",   "Importe", "% des BIP", True, ""),
    ("terms_trade",   "TT.PRI.MRCH.XD.WD","Terms of Trade", "2015=100", True, ""),
    # WB-Schuldenkennzahlen NICHT im Widget (Anti-Halluzination — keine erfundenen Werte). Geprueft
    # 2026-09-29 fuer DE + Peers (FR/IT/ES/NL/PL + EU-Aggregat) via mrv: Schuldenquote GC.DOD.TOTL.GD.ZS,
    # absoluter Staatsschuldenstand GC.DOD.TOTL.CN (Landeswaehrung) und GC.DOD.TOTL.CD (US-$) liefern fuer
    # DE, FR, IT, NL, PL UND das EU-Aggregat KEINE Werte (nur Einzellaender wie ES haben welche); CD
    # existiert gar nicht. Ein Schulden-PRO-KOPF liesse sich daher nicht bilden (Schuldenstand fehlt,
    # obwohl SP.POP.TOTL vorhanden ist) -> Schulden gesamt + pro Kopf weggelassen; voller Schuldenvergleich
    # in der Schulden-UE (Material 2). Ebenso Broad money (FM.LBL.BMNY.GD.ZS): fuer DE + gesamten Euroraum
    # keine Laenderwerte (Geldmenge wird eurosystemweit gefuehrt) -> nicht aufgenommen.
    ("finanzsaldo",  "GC.NLD.TOTL.GD.ZS", "Staatl. Finanzierungssaldo", "% des BIP", True, ""),
    # Zentralstaat (IMF GFS): Staatsausgaben-/Steuerquote hier auf Zentralstaatsebene (DE+EU bis ~2022/2024,
    # laggt wie schon der Gini) — daher im Namen als "(Zentralstaat)" gekennzeichnet.
    ("staatsausgaben","GC.XPN.TOTL.GD.ZS","Staatsausgabenquote (Zentralstaat)", "% des BIP", True, ""),
    ("steuerquote",  "GC.TAX.TOTL.GD.ZS", "Steuerquote (Zentralstaat)", "% des BIP", True, ""),
    ("sparquote",    "NY.GNS.ICTR.ZS",    "Sparquote (Bruttoersparnis)", "% des BIP", True, ""),
    ("gini",         "SI.POV.GINI",       "Gini-Koeffizient (Ungleichheit)", "Punkte", False, ""),
    # NY.GDP.MKTP.CD = BIP zu Marktpreisen in AKTUELLEN US-$ == nominales BIP-Niveau (kein reales/PPP).
    # Deshalb hier als "BIP nominal" gefuehrt (abs/rel-Umschalter: absolut vs. pro Kopf, beide nominal).
    ("bip_abs",      "NY.GDP.MKTP.CD",    "BIP nominal", "Mrd. US$", True, "abs"),
    ("bip_pk",       "NY.GDP.PCAP.CD",    "BIP pro Kopf (nominal)", "US$", True, "rel"),
    # Nachhaltigkeit (BPE 23) — erneuerbare Energien + CO2, Weltbank als EINE Quelle. CO2 aktuelle
    # AR5-Reihe (EN.ATM.CO2E.* ist abgekuendigt, geprueft 2026-10-07); Anteile sind laender-vergleichbar.
    ("erneuerbar_end",  "EG.FEC.RNEW.ZS",       "Erneuerbare Energien (Endenergie)", "%", True, ""),
    ("erneuerbar_strom","EG.ELC.RNEW.ZS",       "Erneuerbarer Strom (Stromerzeugung)", "%", True, ""),
    ("co2_gesamt",      "EN.GHG.CO2.MT.CE.AR5", "CO₂-Emissionen (gesamt)", "Mt", False, ""),
]

def _get(url, tries=4, timeout=180):
    # Vollhistorie-Payloads (v. a. NY.GDP.MKTP.CD, grosse Zahlen) sind gross -> laengeres Timeout + Retry
    # gegen transiente Read-Timeouts der WB-API (sonst faellt eine Kennzahl leer aus -> [WARN]).
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "quarto-stats-widget/2.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(io.TextIOWrapper(r, encoding="utf-8"))
        except Exception as e:
            last = e
            print(f"[..] retry {i+1}/{tries}: {e}", file=sys.stderr, flush=True)
    raise last

def country_list():
    """ISO2 -> Name aller ECHTEN Laender (Aggregate wie 'World'/'EU' ausgefiltert)."""
    out = {}
    data = _get(f"{BASE}/country?format=json&per_page=400")
    for row in data[1]:
        if (row.get("region") or {}).get("value", "") in ("Aggregates", ""):
            continue
        iso = row["id"] if len(row["id"]) == 2 else row.get("iso2Code", "")
        iso = row.get("iso2Code") or iso
        if not iso or len(iso) != 2:
            continue
        out[iso] = NAMES_DE.get(iso, row["name"])
    return out

def fetch(indicator):
    """indicator fuer ALLE Laender ueber die VOLLE Historie: iso2 -> {year: value}.
    date=FIRST_YEAR:LAST_YEAR-Range (statt mrv) -> eine Anfrage je Indikator; per_page gross genug,
    dass alle Entitaeten x Jahre in eine Seite passen (Pagination bleibt als Fallback)."""
    out = {}
    page, pages = 1, 1
    while page <= pages:
        data = _get(f"{BASE}/country/all/indicator/{indicator}?format=json&date={FIRST_YEAR}:{LAST_YEAR}&per_page=30000&page={page}")
        if not isinstance(data, list) or len(data) < 2 or data[1] is None:
            break
        pages = data[0].get("pages", 1)
        for row in data[1]:
            v = row.get("value")
            if v is None:
                continue
            iso = row["country"]["id"]
            out.setdefault(iso, {})[int(row["date"])] = v
        page += 1
    return out

def build_payload():
    countries = country_list()
    yset = set()
    raw_by_key = {}
    for key, wb, name, unit, hib, grp in INDICATORS:
        print(f"[..] fetch {key} ({wb})", file=sys.stderr, flush=True)
        try:
            raw = fetch(wb)
        except Exception as e:
            print(f"[WARN] {key} ({wb}): {e}"); raw = {}
        if key == "bip_abs":
            raw = {c: {y: val/1e9 for y, val in d.items()} for c, d in raw.items()}
        raw_by_key[key] = raw
    # Abgeleitete Kennzahl: nominales BIP-Wachstum = YoY-% des BIP zu jeweiligen Preisen in
    # LANDESWAEHRUNG (NY.GDP.MKTP.CN). Landeswaehrung bewusst statt US-$: die nominale Wachstumsrate
    # soll nicht durch Wechselkurs-Schwankungen der US-$-Reihe (NY.GDP.MKTP.CD) verfaelscht werden.
    # Analog zur Misery-Ableitung unten server-seitig gerechnet. Die CN-Niveau-Reihe selbst wird NICHT
    # angezeigt (Landeswaehrungs-Betraege sind nicht laenderuebergreifend vergleichbar) — nur die Rate.
    # Coverage DE + EU-Vergleichslaender ist ueber die volle Historie gut (CD/CN/KD.ZG geprueft); Laender/
    # Jahre ohne Vorjahreswert liefern hier keinen Wert und werden spaeter sauber als "–" gefuehrt.
    print("[..] fetch bip_wachstum_nom (NY.GDP.MKTP.CN)", file=sys.stderr, flush=True)
    try:
        gdp_cn = fetch("NY.GDP.MKTP.CN")
    except Exception as e:
        print(f"[WARN] bip_wachstum_nom (NY.GDP.MKTP.CN): {e}"); gdp_cn = {}
    bip_w_nom = {}
    for iso, d in gdp_cn.items():
        for y in d:
            if (y - 1) in d and d[y - 1]:   # nur wo Vorjahr vorhanden (sonst luecke -> "–")
                bip_w_nom.setdefault(iso, {})[y] = (d[y] / d[y - 1] - 1) * 100
    raw_by_key["bip_wachstum_nom"] = bip_w_nom
    # Abgeleitete Kennzahl: Misery-Index = Inflationsrate + Arbeitslosenquote (je Land/Jahr, wo beide da).
    infl = raw_by_key.get("inflation", {}); alos = raw_by_key.get("arbeitslos", {})
    misery = {}
    for iso in set(infl) | set(alos):
        di, da = infl.get(iso, {}), alos.get(iso, {})
        for y in set(di) & set(da):
            misery.setdefault(iso, {})[y] = di[y] + da[y]
    raw_by_key["misery"] = misery
    # Meta-Liste (key, name, unit, hib, grp): gefetchte Kennzahlen (ohne WB-Code) + die abgeleitete
    # Misery direkt hinter "arbeitslos" eingereiht.
    meta = []
    for (k, wb, n, u, h, g) in INDICATORS:
        meta.append((k, n, u, h, g))
        if k == "bip_wachstum":
            # nominales BIP-Wachstum direkt hinter dem realen einreihen (hib=True wie real: hoeher=besser)
            meta.append(("bip_wachstum_nom", "BIP-Wachstum nominal", "%", True, ""))
        if k == "arbeitslos":
            meta.append(("misery", "Misery-Index (Inflation + Arbeitslosenquote)", "Punkte", False, ""))
    for d_all in raw_by_key.values():
        for d in d_all.values():
            yset.update(d.keys())
    years = sorted(yset)   # VOLLE Historie (kein [-YEARS_BACK:]-Clip mehr) -> individuell bis zum fruehesten Jahr
    data = {}
    for key, name, unit, hib, grp in meta:
        raw = raw_by_key[key]
        series = {}
        for iso, d in raw.items():
            if iso in countries or iso == EU_AGG:
                series[iso] = [round(d[y], 3) if y in d else None for y in years]
        best, worst = [], []
        for y in years:
            vals = [(raw[c][y], c) for c in EU27 if y in raw.get(c, {})]
            if not vals:
                best.append(None); worst.append(None); continue
            hi, lo = max(vals), min(vals)
            b, w = (hi, lo) if hib else (lo, hi)
            best.append({"v": round(b[0], 3), "c": b[1]})
            worst.append({"v": round(w[0], 3), "c": w[1]})
        data[key] = {"s": series, "best": best, "worst": worst}
    names = {EU_AGG: "EU-Durchschnitt"}
    clist = sorted(([iso, nm] for iso, nm in countries.items() if any(iso in data[k]["s"] for k in data)),
                   key=lambda x: x[1])
    return {"years": years,
            "countries": clist,
            "agg": names,
            "indicators": [{"key": k, "name": n, "unit": u, "grp": g, "hib": h}
                           for (k, n, u, h, g) in meta],
            "data": data}

def _slice_inline(payload, keep):
    """Kappt den PAYLOAD auf die letzten `keep` Jahre — NUR fuer den gebackenen Inline-Fallback.
    years, best, worst und jede series-Liste sind index-parallel zu years, daher genuegt der
    Tail-Slice [-keep:] auf allen gleichmaessig. Der emit-json-Pfad ruft dies NICHT auf (Vollhistorie)."""
    years = payload["years"]
    if len(years) <= keep:
        return payload
    new_data = {}
    for key, d in payload["data"].items():
        new_data[key] = {"s": {iso: vals[-keep:] for iso, vals in d["s"].items()},
                         "best": d["best"][-keep:], "worst": d["worst"][-keep:]}
    out = dict(payload)
    out["years"] = years[-keep:]
    out["data"] = new_data
    return out

def main():
    args = sys.argv[1:]
    if args and args[0] == "--emit-json":
        payload = build_payload()
        out = args[1] if len(args) > 1 else "wb-stats.json"
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        print(f"[OK] {out} — {len(payload['countries'])} Laender, {len(payload['indicators'])} Kennzahlen, "
              f"Jahre {payload['years'][0]}-{payload['years'][-1]}")
        return
    if not args:
        print("Aufruf: python _assets/stats-widget.py <bpe-ordner> | --emit-json <datei>"); sys.exit(2)
    target = args[0].rstrip("/\\")
    payload = build_payload()
    # Inline-Bake NUR auf die letzten INLINE_YEARS Jahre kappen (kleiner Fallback). Der --emit-json-Pfad
    # oben bleibt VOLLHISTORIE (fuer GitHub); nur der in die _*.qmd gebackene Datensatz wird geslict.
    inline = _slice_inline(payload, INLINE_YEARS)
    data_js = json.dumps(inline, ensure_ascii=False, separators=(",", ":"))
    out = (TEMPLATE.replace("/*__DATA__*/", data_js)
                   .replace("__REPO__", GITHUB_STATS_REPO))
    with open(target + "/_stats-widget.qmd", "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print(f"[OK] {target}/_stats-widget.qmd — {len(payload['countries'])} Laender, "
          f"{len(payload['indicators'])} Kennzahlen, Fallback-Jahre {inline['years'][0]}-{inline['years'][-1]} (inline), "
          f"Vollhistorie {payload['years'][0]}-{payload['years'][-1]} (live), "
          f"Live-Repo: {GITHUB_STATS_REPO or '(nur gebacken)'}")

TEMPLATE = r'''::: {.content-visible when-format="html"}
```{=html}
<div class="wb-stats" id="wb-stats">
  <h3 style="margin:.2rem 0">Kennzahlen im Vergleich <span style="font-weight:400;font-size:.8em;color:#666">(Weltbank, Jahreswerte — alle Länder wählbar)</span></h3>
  <div class="wb-controls" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:center;margin:.4rem 0">
    <label>Zeithorizont:
      <select id="wb-time"><option value="1y" selected>letztes Jahr</option><option value="5y">letzte 5 Jahre</option><option value="10y">letzte 10 Jahre</option><option value="custom">individuell (von–bis)</option></select>
    </label><span id="wb-customrange" style="display:none">von <select id="wb-start" style="min-width:5rem"></select> bis <select id="wb-end" style="min-width:5rem"></select></span><span id="wb-timeinfo" style="color:#1565c0;font-weight:600;font-size:.9em;margin-left:-.2rem"></span>
    <label>Kennzahl: <select id="wb-ind"></select></label>
    <label>BIP als: <select id="wb-relabs"><option value="abs">absolut (Mrd. US$)</option><option value="rel">pro Kopf (US$)</option></select></label>
    <label>Diagramm: <select id="wb-chart"><option value="line" selected>Linie (Zeitreihe)</option><option value="column">Säulen</option><option value="bar">Balken</option><option value="pie">Torte</option></select></label>
  </div>
  <div id="wb-formula" style="font-size:.85em;background:#f5f8fd;border-left:3px solid #1565c0;padding:.35rem .6rem;margin:.2rem 0;border-radius:0 3px 3px 0"></div>
  <details style="margin:.3rem 0"><summary style="cursor:pointer;font-weight:600">Länder wählen</summary>
    <div style="display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin:.4rem 0">
      <button type="button" id="wb-all" style="cursor:pointer;padding:.15rem .55rem">Alle</button>
      <button type="button" id="wb-none" style="cursor:pointer;padding:.15rem .55rem">Keine</button>
      <input id="wb-search" type="text" placeholder="Land suchen…" style="padding:.2rem;width:12rem;margin-left:.3rem">
    </div>
    <div id="wb-cty" style="display:flex;flex-wrap:wrap;gap:.2rem .9rem;max-height:11rem;overflow:auto;font-size:.83em;border:1px solid #ddd;padding:.4rem"></div>
  </details>
  <div id="wb-table" style="overflow-x:auto"></div>
  <details style="margin:.3rem 0"><summary style="cursor:pointer;font-weight:600;font-size:.85em;color:#666">Hinweise &amp; Methodik</summary>
  <p style="font-size:.78em;color:#666;margin:.3rem 0">Matrix: eine Zeile je Entität (Land, EU-Durchschnitt, bestes/schlechtestes EU-Land), je Spalte ein Jahr des Zeithorizonts — konkrete Einzelwerte, keine Durchschnitte. „Letztes Jahr" = aktuellstes Jahr (Weltbank liefert nur Jahreswerte; monatlich s. Eurostat-Widget). „Individuell (von–bis)" zeigt alle Einzeljahre im gewählten Bereich; wird die Matrix dadurch zu breit, teilt sie sich in mehrere untereinander gestapelte Tabellen (je ≤ 10 Jahresspalten, mit wiederholtem Zeilenkopf). Bestes/schlechtestes EU-Land je Kennzahl und Jahr aus den EU-27 — der Ländername steht im Zeilenkopf (jüngstes Jahr) und je Zelle. Für die Balken-/Säulen-/Tortenansicht wird der jüngste Jahreswert des Fensters gezeigt; das Liniendiagramm zeigt die ganze Reihe. Quelle: Weltbank Indicators API.</p>
  </details>
  <div id="wb-canvas-wrap" style="max-width:760px;height:340px;position:relative"><canvas id="wb-canvas"></canvas></div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
(function(){
  var S = /*__DATA__*/;
  var REPO = "__REPO__";
  var el=document.getElementById('wb-stats'); if(!el) return;
  var SPECIAL=[["EU","EU-Durchschnitt"],["BEST","bestes EU-Land"],["WORST","schlechtestes EU-Land"]];
  // Zeithorizont -> Anzahl konkreter Jahreswerte. Weltbank ist jaehrlich (keine Monatsaufloesung),
  // daher gibt es KEINE "12 Monate"-Option mehr; "letztes Jahr" = juengster Jahreswert. "custom" =
  // individueller Von-bis-Bereich (Jahres-Dropdowns), siehe windowYears().
  var HN={"1y":1,"5y":5,"10y":10};
  var state={horizon:'1y',relabs:'abs',chart:'line',sel:null,cty:{DE:true},cstart:null,cend:null,sort:{col:null,dir:1}};
  // Formel + 1-Satz-Erklaerung je Kennzahl (Division als Bruch ÷; abgeleitete Kennzahlen als solche benannt).
  var FORMULAS={
    bip_wachstum:{f:"BIP-Wachstum real = (reales BIP dieses Jahr − reales BIP Vorjahr) ÷ reales BIP Vorjahr × 100 %",
      e:"Preisbereinigte Veränderung des BIP gegenüber dem Vorjahr — echtes Mengenwachstum ohne Preiseffekt."},
    bip_wachstum_nom:{f:"BIP-Wachstum nominal = (nominales BIP dieses Jahr − nominales BIP Vorjahr) ÷ nominales BIP Vorjahr × 100 %  (in Landeswährung)",
      e:"Veränderung des BIP zu jeweiligen Preisen — enthält anders als das reale Wachstum auch die Preissteigerung."},
    inflation:{f:"Inflationsrate = (Verbraucherpreisindex dieses Jahr − VPI Vorjahr) ÷ VPI Vorjahr × 100 %",
      e:"Prozentualer Anstieg des Verbraucherpreisindex (VPI) gegenüber dem Vorjahr — misst die Geldentwertung."},
    arbeitslos:{f:"Arbeitslosenquote = Arbeitslose ÷ Erwerbspersonen × 100 %",
      e:"Anteil der Arbeitslosen an allen Erwerbspersonen (Beschäftigte + Arbeitslose)."},
    misery:{f:"Misery-Index = Inflationsrate + Arbeitslosenquote",
      e:"„Elends-Index“ (abgeleitet): je höher, desto stärker belasten Teuerung und Arbeitslosigkeit die Menschen zugleich."},
    leistungsbil:{f:"Leistungsbilanzsaldo (% des BIP) = Leistungsbilanzsaldo ÷ BIP × 100 %",
      e:"Saldo aus Waren, Dienstleistungen sowie Primär- und Sekundäreinkommen mit dem Ausland, relativ zum BIP."},
    aussenbeitrag:{f:"Außenbeitrag = (Exporte − Importe) ÷ BIP × 100 %",
      e:"Nettoexporte (Waren + Dienstleistungen) im Verhältnis zum BIP — Teil der Leistungsbilanz ohne Einkommen."},
    exporte:{f:"Exportquote = Exporte (Waren + Dienstleistungen) ÷ BIP × 100 %",
      e:"Anteil der Ausfuhren am BIP — Maß für die Exportabhängigkeit einer Volkswirtschaft."},
    importe:{f:"Importquote = Importe (Waren + Dienstleistungen) ÷ BIP × 100 %",
      e:"Anteil der Einfuhren am BIP."},
    terms_trade:{f:"Terms of Trade = Exportpreisindex ÷ Importpreisindex × 100  (2015 = 100)",
      e:"Reales Austauschverhältnis im Außenhandel — steigt der Wert, bekommt das Land für seine Exporte mehr Importe."},
    finanzsaldo:{f:"Finanzierungssaldo (% des BIP) = (Staatseinnahmen − Staatsausgaben) ÷ BIP × 100 %",
      e:"Budgetsaldo des Staates relativ zum BIP — negativ = Defizit, positiv = Überschuss."},
    staatsausgaben:{f:"Staatsausgabenquote = Staatsausgaben (Zentralstaat) ÷ BIP × 100 %",
      e:"Anteil der Ausgaben des Zentralstaats am BIP — Maß für die Staatstätigkeit."},
    steuerquote:{f:"Steuerquote = Steuereinnahmen (Zentralstaat) ÷ BIP × 100 %",
      e:"Anteil der Steuereinnahmen am BIP (ohne Sozialbeiträge, Zentralstaatsebene)."},
    sparquote:{f:"Sparquote = Bruttoersparnis ÷ BIP × 100 %",
      e:"Anteil des nicht konsumierten Einkommens (brutto) am BIP."},
    gini:{f:"Gini-Koeffizient = Fläche zwischen Gleichverteilung und Lorenzkurve ÷ Gesamtfläche unter der Gleichverteilung  (0–100)",
      e:"Maß der Einkommensungleichheit: 0 = alle gleich, 100 = einer hat alles."},
    bip_abs:{f:"BIP nominal = Konsum + Investitionen + Staatsausgaben + (Exporte − Importe)",
      e:"Gesamtwert aller im Inland erzeugten Waren und Dienstleistungen eines Jahres zu laufenden Preisen (US$)."},
    bip_pk:{f:"BIP pro Kopf = BIP ÷ Bevölkerung",
      e:"Bruttoinlandsprodukt je Einwohner (nominal, US$) — grobes Maß für den durchschnittlichen Wohlstand."}
  };
  function nyears(){ return HN[state.horizon]||1; }
  function windowYears(){   // konkrete Einzeljahre, NIE gemittelt
    if(state.horizon==='custom'){
      var a=state.cstart, b=state.cend;
      if(a==null||b==null) return S.years.slice(-1);
      if(a>b){ var t=a; a=b; b=t; }
      return S.years.filter(function(y){ return y>=a && y<=b; });
    }
    return S.years.slice(-nyears()); }
  function rangeLabel(){ var y=windowYears(); if(!y.length)return '';
    return y.length===1?(''+y[0]):(y[0]+'–'+y[y.length-1]); }
  function cname(c){ if(c==='BEST')return 'bestes EU-Land'; if(c==='WORST')return 'schlechtestes EU-Land';
    if(S.agg[c])return S.agg[c]; var f=S.countries.find(function(x){return x[0]===c;}); return f?f[1]:c; }
  function activeInds(){ return S.indicators.filter(function(i){
    if(i.grp==='abs')return state.relabs==='abs'; if(i.grp==='rel')return state.relabs==='rel'; return true; }); }
  function activeCols(){ var c=[];
    S.countries.forEach(function(x){ if(state.cty[x[0]])c.push(x[0]); });
    ['EU','BEST','WORST'].forEach(function(s){ if(state.cty[s])c.push(s); }); return c; }
  // Zeilenreihenfolge der Matrix nach dem Sortier-Zustand (Klick auf Spaltenkopf). 'name' = erste
  // Spalte (alphabetisch), sonst ein Jahr; Fehlwerte "–" IMMER ans Ende, unabhaengig von der Richtung.
  function orderedCols(mi){
    var cols=activeCols().slice(), sc=state.sort;
    if(!sc||sc.col==null) return cols;
    if(sc.col==='name'){
      cols.sort(function(a,b){ return rowLabel(mi,a).localeCompare(rowLabel(mi,b),'de')*sc.dir; });
    } else {
      var y=sc.col;
      cols.sort(function(a,b){ var va=seriesAt(mi.key,a,y), vb=seriesAt(mi.key,b,y);
        if(va==null&&vb==null) return 0; if(va==null) return 1; if(vb==null) return -1;
        return (va-vb)*sc.dir; });
    }
    return cols;
  }
  function seriesAt(key,col,y){ var d=S.data[key]; if(!d)return null; var idx=S.years.indexOf(y);
    if(col==='BEST'){var b=d.best[idx];return b?b.v:null;} if(col==='WORST'){var w=d.worst[idx];return w?w.v:null;}
    var s=d.s[col]; return s?s[idx]:null; }
  // Konkreter Einzelwert der juengsten Periode im Fenster (fuer Balken/Saeulen/Torte) — KEIN Durchschnitt.
  function spotVal(key,col){ var y=windowYears();
    for(var i=y.length-1;i>=0;i--){ var v=seriesAt(key,col,y[i]); if(v!=null)return v; } return null; }
  function fmt(v,u){ if(v==null)return '–'; var a=Math.abs(v)>=100?Math.round(v):Math.round(v*10)/10;
    return (''+a).replace('.',',')+((''+u).indexOf('%')===0?' %':''); }
  // Name des in Jahr y besten/schlechtesten EU-Landes (fuer die Zelle).
  function euName(key,which,y){ var d=S.data[key]; if(!d)return null; var idx=S.years.indexOf(y);
    var e=(which==='BEST'?d.best:d.worst)[idx]; return e?cname(e.c):null; }
  // Name fuer das juengste Jahr des Fensters (fuer den Zeilenkopf) — faellt auf aeltere Jahre zurueck.
  function euNameLatest(key,which){ var y=windowYears();
    for(var i=y.length-1;i>=0;i--){ var n=euName(key,which,y[i]); if(n)return n; } return null; }
  function selInd(){ var inds=activeInds();
    if(!state.sel||!inds.find(function(i){return i.key===state.sel;})) state.sel=(inds[0]||{}).key;
    return S.indicators.find(function(i){return i.key===state.sel;}); }
  function renderIndOptions(){ var sel=document.getElementById('wb-ind'); if(!sel)return;
    var cur=(selInd()||{}).key;
    // Optionen alphabetisch nach Anzeigename sortiert; Default-Auswahl (cur via selInd()) bleibt inhaltlich gleich.
    var inds=activeInds().slice().sort(function(a,b){ return a.name.localeCompare(b.name,'de'); });
    sel.innerHTML=inds.map(function(i){
      return '<option value="'+i.key+'"'+(i.key===cur?' selected':'')+'>'+i.name+'</option>'; }).join(''); }
  // Eine Teiltabelle fuer einen Jahres-Chunk: Zeilen = gewaehlte Entitaeten, Spalten = Jahre, Zelle =
  // konkreter Einzelwert. Jede Teiltabelle wiederholt den Entitaets-/Laender-Zeilenkopf (Split-Regel).
  // Zeilenkopf-Beschriftung einer Entitaet (Best/Worst mit fuehrendem Laendernamen des juengsten Jahres).
  function rowLabel(mi,c){
    if(c==='BEST'){ var nb=euNameLatest(mi.key,'BEST'); return (nb?nb+' — ':'')+'bestes EU-Land'; }
    if(c==='WORST'){ var nw=euNameLatest(mi.key,'WORST'); return (nw?nw+' — ':'')+'schlechtestes EU-Land'; }
    return cname(c);
  }
  function sortArrow(active){ return active?(state.sort.dir>0?' ▲':' ▼'):''; }
  function tableChunk(mi,cols,yrs,isFirst){
    var cap=mi.name+' <span style="color:#888;font-weight:400">('+mi.unit+')'
      +(isFirst?'':' — Fortsetzung '+yrs[0]+(yrs.length>1?('–'+yrs[yrs.length-1]):''))+'</span>';
    // Header UND Zellen je Spalte identisch ausgerichtet (Land links, Jahre rechtsbuendig, gleiche
    // Mindestbreite) -> jede Zahl steht direkt unter "ihrem" Jahres-Spaltenkopf. Spaltenkoepfe sortierbar.
    var h='<table class="table" style="font-size:.85em;margin-bottom:.6rem;border-collapse:collapse">'
      +'<caption style="caption-side:top;text-align:left;font-weight:600;padding:.2rem 0">'+cap+'</caption>';
    var na=(state.sort.col==='name');
    h+='<thead><tr><th data-sort="name" style="text-align:left;cursor:pointer;white-space:nowrap;user-select:none">Entität'+sortArrow(na)+'</th>';
    yrs.forEach(function(y){ var ay=(state.sort.col===y);
      h+='<th data-sort="'+y+'" style="text-align:right;cursor:pointer;white-space:nowrap;user-select:none;min-width:3.4rem">'+y+sortArrow(ay)+'</th>'; });
    h+='</tr></thead><tbody>';
    cols.forEach(function(c){
      h+='<tr><td style="text-align:left;white-space:nowrap">'+rowLabel(mi,c)+'</td>';
      yrs.forEach(function(y){
        var v=seriesAt(mi.key,c,y);
        if(v==null){ h+='<td style="text-align:right;min-width:3.4rem">–</td>'; return; }
        var cell=fmt(v,mi.unit);
        if(c==='BEST'||c==='WORST'){ var nm=euName(mi.key,c,y);
          if(nm) cell='<span title="'+nm+'">'+cell+'<br><span style="font-size:.8em;color:#888">'+nm+'</span></span>'; }
        h+='<td style="text-align:right;min-width:3.4rem">'+cell+'</td>';
      });
      h+='</tr>';
    });
    return h+'</tbody></table>';
  }
  // Matrix: bei vielen Jahresspalten in mehrere gestapelte Tabellen aufteilen (je <= 10 Jahre).
  function renderTable(){
    var box=document.getElementById('wb-table');
    var mi=selInd(); if(!mi){ box.innerHTML=''; return; }
    var cols=orderedCols(mi), yrs=windowYears(), CHUNK=10;
    if(!yrs.length){ box.innerHTML=tableChunk(mi,cols,[],true); }
    else { var h=''; for(var i=0;i<yrs.length;i+=CHUNK){ h+=tableChunk(mi,cols,yrs.slice(i,i+CHUNK),i===0); } box.innerHTML=h; }
    // Spaltenkopf-Klick: aufsteigend, erneut absteigend (Toggle). Konsistent ueber alle Split-Tabellen,
    // weil cols einmal via orderedCols(mi) sortiert und an alle Chunks weitergereicht wird.
    Array.prototype.forEach.call(box.querySelectorAll('th[data-sort]'),function(th){
      th.onclick=function(){ var k=th.getAttribute('data-sort'); if(k!=='name')k=parseInt(k,10);
        if(state.sort.col===k) state.sort.dir=-state.sort.dir; else { state.sort.col=k; state.sort.dir=1; }
        renderTable(); };
    });
  }
  var chart=null;
  function draw(){
    var mi=selInd(); if(!mi)return; var key=mi.key; var cols=activeCols(), yrs=windowYears();
    var pal=['#1565c0','#c0392b','#2e7d32','#f39c12','#6a1b9a','#00838f','#5d4037','#455a64','#ad1457','#1b5e20'];
    // S/w-druckfest: je Reihe zusaetzlich zur Farbe eine eigene Strich- (borderDash) UND Marker-Kodierung
    // (pointStyle), zyklisch — so bleiben die Kurven im Graustufendruck eindeutig; Farbe nur redundant.
    var DASH=[[],[6,3],[2,3],[8,3,2,3],[10,4],[4,2],[1,3],[12,3,3,3]];
    var PTS=['circle','triangle','rect','rectRot','cross','star','crossRot','line'];
    var ctx=document.getElementById('wb-canvas').getContext('2d'); var cfg;
    if(state.chart==='line'){
      cfg={type:'line',data:{labels:yrs,datasets:cols.map(function(c,ix){return {label:cname(c),borderColor:pal[ix%10],backgroundColor:pal[ix%10],fill:false,tension:.2,spanGaps:true,
        borderDash:DASH[ix%DASH.length],pointStyle:PTS[ix%PTS.length],pointRadius:3,pointHoverRadius:5,
        data:yrs.map(function(y){return seriesAt(key,c,y);})};})}};
    } else if(state.chart==='pie'){ cfg={type:'pie',data:{labels:cols.map(cname),datasets:[{backgroundColor:pal,
        data:cols.map(function(c){var v=spotVal(key,c);return v==null?0:Math.abs(v);})}]}};
    } else { cfg={type:'bar',data:{labels:cols.map(cname),datasets:[{label:mi.name,backgroundColor:pal,barThickness:22,maxBarThickness:24,
        data:cols.map(function(c){return spotVal(key,c);})}]},options:{indexAxis:state.chart==='bar'?'y':'x',plugins:{legend:{display:false}}}};
    }
    var y=windowYears();
    var subtitle=state.chart==='line'?rangeLabel():(y.length?(''+y[y.length-1]):'');
    cfg.options=Object.assign({responsive:true,maintainAspectRatio:false,plugins:{title:{display:true,text:mi.name+' ('+mi.unit+')'+(subtitle?(' · '+subtitle):'')}}},cfg.options||{});
    // Feste Balkendicke (oben) + Canvas waechst mit der Laenderzahl nach unten (statt die Balken zu dehnen).
    var wrap=document.getElementById('wb-canvas-wrap');
    if(state.chart==='bar'||state.chart==='column'){ wrap.style.height=Math.max(200,70+cols.length*42)+'px'; }
    else { wrap.style.height='340px'; }
    if(chart)chart.destroy(); chart=new Chart(ctx,cfg);
  }
  function renderCty(){
    var box=document.getElementById('wb-cty'); var q=(document.getElementById('wb-search').value||'').toLowerCase();
    var list=SPECIAL.concat(S.countries);
    box.innerHTML=list.filter(function(x){return q===''||x[1].toLowerCase().indexOf(q)>=0;}).map(function(x){
      return '<label style="width:12rem"><input type="checkbox" data-c="'+x[0]+'"'+(state.cty[x[0]]?' checked':'')+'> '+x[1]+'</label>';
    }).join('');
    Array.prototype.forEach.call(box.querySelectorAll('input[data-c]'),function(cb){
      cb.onchange=function(){var c=cb.getAttribute('data-c'); if(cb.checked)state.cty[c]=true; else delete state.cty[c]; renderTable();draw();};});
  }
  function renderTimeInfo(){ var t=document.getElementById('wb-timeinfo'); if(!t)return; t.textContent=rangeLabel(); }
  // Formel + Erklaerung der aktuell gewaehlten Kennzahl unter dem Selektor anzeigen.
  function renderFormula(){ var box=document.getElementById('wb-formula'); if(!box)return;
    var mi=selInd(); var fx=mi?FORMULAS[mi.key]:null;
    if(!fx){ box.style.display='none'; box.innerHTML=''; return; }
    box.style.display=''; box.innerHTML='<b>'+fx.f+'</b><br><span style="color:#555">'+fx.e+'</span>'; }
  // Von-bis-Dropdowns (Jahres-Aufloesung) — nur bei horizon='custom' sichtbar. Werte auf verfuegbare
  // Jahre klemmen (falls ein Live-Fetch die Jahresliste aendert).
  function renderCustomRange(){
    var wrap=document.getElementById('wb-customrange'),
        ss=document.getElementById('wb-start'), es=document.getElementById('wb-end');
    if(!wrap||!S.years.length) return;
    if(state.cstart==null||S.years.indexOf(state.cstart)<0) state.cstart=S.years[0];
    if(state.cend==null||S.years.indexOf(state.cend)<0) state.cend=S.years[S.years.length-1];
    function opts(sel){ return S.years.map(function(y){
      return '<option value="'+y+'"'+(y===sel?' selected':'')+'>'+y+'</option>'; }).join(''); }
    ss.innerHTML=opts(state.cstart); es.innerHTML=opts(state.cend);
    wrap.style.display=(state.horizon==='custom')?'':'none';
  }
  document.getElementById('wb-time').onchange=function(e){state.horizon=e.target.value;renderCustomRange();renderTimeInfo();renderTable();draw();};
  document.getElementById('wb-start').onchange=function(e){state.cstart=parseInt(e.target.value,10);renderTimeInfo();renderTable();draw();};
  document.getElementById('wb-end').onchange=function(e){state.cend=parseInt(e.target.value,10);renderTimeInfo();renderTable();draw();};
  document.getElementById('wb-relabs').onchange=function(e){ state.relabs=e.target.value;
    if(state.sel==='bip_abs'&&state.relabs==='rel')state.sel='bip_pk';
    else if(state.sel==='bip_pk'&&state.relabs==='abs')state.sel='bip_abs';
    renderIndOptions();renderFormula();renderTable();draw(); };
  document.getElementById('wb-chart').onchange=function(e){state.chart=e.target.value;draw();};
  document.getElementById('wb-ind').onchange=function(e){state.sel=e.target.value;renderFormula();renderTable();draw();};
  document.getElementById('wb-search').oninput=renderCty;
  // "Alle"/"Keine": alle echten Laender an- bzw. alles abwaehlen, dann Liste + Matrix + Diagramm neu.
  document.getElementById('wb-all').onclick=function(){ S.countries.forEach(function(x){state.cty[x[0]]=true;}); renderCty();renderTable();draw(); };
  document.getElementById('wb-none').onclick=function(){ state.cty={}; renderCty();renderTable();draw(); };
  function boot(){ renderIndOptions(); renderFormula(); renderCty(); renderCustomRange(); renderTimeInfo(); renderTable(); draw(); }
  boot();
  // Live-Layer (jaehrliche Aktualisierung via GitHub, fail-safe): ersetzt die gebackenen
  // (15-Jahre-)Fallback-Daten durch die Vollhistorie. renderCustomRange() baut die Von-/Bis-Dropdowns
  // aus den nun vollen S.years neu auf (voller Zeitraum waehlbar); boot() zeichnet Selektor,
  // aufgeloesten Zeitraum, Matrix und Diagramm neu. Fehlender/fehlgeschlagener Fetch -> Fallback bleibt.
  if(REPO){ fetch("https://raw.githubusercontent.com/"+REPO+"/main/wb-stats.json",{cache:"no-store"})
    .then(function(r){ if(!r.ok) throw 0; return r.json(); })
    .then(function(j){ if(j&&j.data&&j.years){ S=j; renderCustomRange(); boot(); } }).catch(function(){}); }
})();
</script>
```
:::
'''

if __name__ == "__main__":
    main()
