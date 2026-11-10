#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ezb-wechselkurs-widget.py — backt ein HTML-Widget: der EURO gegenueber (fast) allen Waehrungen der Welt.

Zeigt die Euro-Referenzkurse der EZB fuer ALLE Waehrungen, die die EZB fuehrt oder gefuehrt hat
(aktiv notierte, beendete Reihen wie RUB/TWD, Altwaehrungen der Euro-Beitrittslaender wie BGN/HRK),
als Liniendiagramm ueber einen FREI WAEHLBAREN Zeitraum zurueck bis Januar 1999 (Start des Euro),
mit Umschalter MENGENNOTIERUNG (indirect quotation, 1 EUR = x Fremdwaehrung) <-> PREISNOTIERUNG
(direct quotation, 1 [100, 1000 …] Fremdwaehrung = x EUR) und Ansicht Kurs | Index (Periodenstart = 100).
Erste Nutzung: wg13iw BPE 22 Modul 2 (Wechselkurse, Mengen-/Preisnotierung).

Quelle (anonym, kein API-Key, s. AGENTS.md "Wirtschaftskennzahlen" — EINE Quelle fuer alle Zahlen):
  European Central Bank (ECB), Data Portal, Datensatz EXR (euro foreign exchange reference rates)
    EXR.M.<CUR>.EUR.SP00.A  Monatsdurchschnitt, Fremdwaehrung je 1 EUR   (Diagramm, ab 1999-01)
    EXR.D.<CUR>.EUR.SP00.A  Tageskurs, lastNObservations=1               (Tabelle "aktueller Kurs")
  https://data-api.ecb.europa.eu/service/data/EXR  ·  https://data.ecb.europa.eu/data/datasets/EXR

GEBACKEN + LIVE-LAYER (Muster eurostat-widget.py, s. _assets/stats-github/README.md): Die Daten sind in
die Seite gebacken (Fallback, sofort sichtbar, offline/Moodle). Zusaetzlich holt das Widget asynchron
`ezb-wechselkurse.json` aus dem oeffentlichen Daten-Repo GITHUB_STATS_REPO (raw.githubusercontent.com,
cache:"no-store"); ist sie neuer als der gebackene Stand, ersetzt sie die Daten — sonst bleibt der
Fallback (fail-safe). Die JSON backt dort die Action `refresh-ezb-wechselkurse.yml` werktags nach der
EZB-Veroeffentlichung. Reale Zahlen = HTML-Aktualitaetsschicht; das Include ist when-format=html und
@media print verborgen.

    python _assets/ezb-wechselkurs-widget.py <bpe-ordner> [--lang en|de]   -> holt frisch + backt
    python _assets/ezb-wechselkurs-widget.py <bpe-ordner> --offline [...]  -> backt aus dem Cache
    python _assets/ezb-wechselkurs-widget.py --emit-json <datei>          -> nur Live-JSON (GitHub-Action;
                                                   sprachneutral, braucht weder Template noch Cache)
Ausgabe: <bpe-ordner>/_ezb-wechselkurs-widget.qmd (Template: _assets/ezb-wechselkurs-template.html).
"""
import sys, csv, io, json, math, time, argparse, datetime, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "ezb-wechselkurs-cache.json"
TEMPLATE = HERE / "ezb-wechselkurs-template.html"
API = "https://data-api.ecb.europa.eu/service/data/EXR/{freq}..EUR.SP00.A?format=csvdata&{q}"
PORTAL = "https://data.ecb.europa.eu/data/datasets/EXR"
START = "1999-01"
# Oeffentliches Daten-Repo des Live-Layers (dasselbe wie eurostat-widget.py). Leer => nur gebacken.
GITHUB_STATS_REPO = "dennis-haensel-online/stats-data"
LIVE_FILE = "ezb-wechselkurse.json"

# code: (Name EN, Name DE, Land/Region EN, Land/Region DE, Gruppe, Notiz EN, Notiz DE)
# Gruppe: "live" = aktuelle EZB-Referenzkurse · "ended" = Reihe eingestellt · "euro" = durch den Euro ersetzt
CUR = {
    "USD": ("US dollar", "US-Dollar", "USA", "USA", "live", "", ""),
    "GBP": ("pound sterling", "Pfund Sterling", "United Kingdom", "Großbritannien", "live", "", ""),
    "CHF": ("Swiss franc", "Schweizer Franken", "Switzerland", "Schweiz", "live", "", ""),
    "CNY": ("Chinese yuan renminbi", "Chinesischer Yuan Renminbi", "China", "China", "live", "", ""),
    "JPY": ("Japanese yen", "Japanischer Yen", "Japan", "Japan", "live", "", ""),
    "AUD": ("Australian dollar", "Australischer Dollar", "Australia", "Australien", "live", "", ""),
    "BRL": ("Brazilian real", "Brasilianischer Real", "Brazil", "Brasilien", "live", "", ""),
    "CAD": ("Canadian dollar", "Kanadischer Dollar", "Canada", "Kanada", "live", "", ""),
    "CZK": ("Czech koruna", "Tschechische Krone", "Czechia", "Tschechien", "live", "", ""),
    "DKK": ("Danish krone", "Dänische Krone", "Denmark", "Dänemark", "live",
            "pegged to the euro (ERM II)", "an den Euro gebunden (WKM II)"),
    "HKD": ("Hong Kong dollar", "Hongkong-Dollar", "Hong Kong", "Hongkong", "live", "", ""),
    "HUF": ("Hungarian forint", "Ungarischer Forint", "Hungary", "Ungarn", "live", "", ""),
    "IDR": ("Indonesian rupiah", "Indonesische Rupiah", "Indonesia", "Indonesien", "live", "", ""),
    "ILS": ("Israeli shekel", "Israelischer Schekel", "Israel", "Israel", "live", "", ""),
    "INR": ("Indian rupee", "Indische Rupie", "India", "Indien", "live", "", ""),
    "ISK": ("Icelandic krona", "Isländische Krone", "Iceland", "Island", "live",
            "no ECB rate Dec 2008 – Feb 2018 (banking crisis)", "kein EZB-Kurs Dez. 2008 – Feb. 2018 (Bankenkrise)"),
    "KRW": ("South Korean won", "Südkoreanischer Won", "South Korea", "Südkorea", "live", "", ""),
    "MXN": ("Mexican peso", "Mexikanischer Peso", "Mexico", "Mexiko", "live", "", ""),
    "MYR": ("Malaysian ringgit", "Malaysischer Ringgit", "Malaysia", "Malaysia", "live", "", ""),
    "NOK": ("Norwegian krone", "Norwegische Krone", "Norway", "Norwegen", "live", "", ""),
    "NZD": ("New Zealand dollar", "Neuseeland-Dollar", "New Zealand", "Neuseeland", "live", "", ""),
    "PHP": ("Philippine peso", "Philippinischer Peso", "Philippines", "Philippinen", "live", "", ""),
    "PLN": ("Polish zloty", "Polnischer Zloty", "Poland", "Polen", "live", "", ""),
    "RON": ("Romanian leu", "Rumänischer Leu", "Romania", "Rumänien", "live", "", ""),
    "SEK": ("Swedish krona", "Schwedische Krone", "Sweden", "Schweden", "live", "", ""),
    "SGD": ("Singapore dollar", "Singapur-Dollar", "Singapore", "Singapur", "live", "", ""),
    "THB": ("Thai baht", "Thailändischer Baht", "Thailand", "Thailand", "live", "", ""),
    "TRY": ("Turkish lira", "Türkische Lira", "Türkiye", "Türkei", "live",
            "shown in today's (new) lira throughout", "durchgehend in heutiger (neuer) Lira"),
    "ZAR": ("South African rand", "Südafrikanischer Rand", "South Africa", "Südafrika", "live", "", ""),
    "RUB": ("Russian rouble", "Russischer Rubel", "Russia", "Russland", "ended",
            "ECB suspended the rate in March 2022", "EZB setzt den Kurs seit März 2022 aus"),
    "ARS": ("Argentine peso", "Argentinischer Peso", "Argentina", "Argentinien", "ended",
            "indicative rate, series ended", "Indikativkurs, Reihe eingestellt"),
    "DZD": ("Algerian dinar", "Algerischer Dinar", "Algeria", "Algerien", "ended",
            "indicative rate, series ended", "Indikativkurs, Reihe eingestellt"),
    "MAD": ("Moroccan dirham", "Marokkanischer Dirham", "Morocco", "Marokko", "ended",
            "indicative rate, series ended", "Indikativkurs, Reihe eingestellt"),
    "TWD": ("New Taiwan dollar", "Neuer Taiwan-Dollar", "Taiwan", "Taiwan", "ended",
            "indicative rate, series ended", "Indikativkurs, Reihe eingestellt"),
    "GRD": ("Greek drachma", "Griechische Drachme", "Greece", "Griechenland", "euro", "euro since 2001", "Euro seit 2001"),
    "SIT": ("Slovenian tolar", "Slowenischer Tolar", "Slovenia", "Slowenien", "euro", "euro since 2007", "Euro seit 2007"),
    "CYP": ("Cyprus pound", "Zypern-Pfund", "Cyprus", "Zypern", "euro", "euro since 2008", "Euro seit 2008"),
    "MTL": ("Maltese lira", "Maltesische Lira", "Malta", "Malta", "euro", "euro since 2008", "Euro seit 2008"),
    "SKK": ("Slovak koruna", "Slowakische Krone", "Slovakia", "Slowakei", "euro", "euro since 2009", "Euro seit 2009"),
    "EEK": ("Estonian kroon", "Estnische Krone", "Estonia", "Estland", "euro", "euro since 2011", "Euro seit 2011"),
    "LVL": ("Latvian lats", "Lettischer Lats", "Latvia", "Lettland", "euro", "euro since 2014", "Euro seit 2014"),
    "LTL": ("Lithuanian litas", "Litauischer Litas", "Lithuania", "Litauen", "euro", "euro since 2015", "Euro seit 2015"),
    "HRK": ("Croatian kuna", "Kroatische Kuna", "Croatia", "Kroatien", "euro", "euro since 2023", "Euro seit 2023"),
    "BGN": ("Bulgarian lev", "Bulgarischer Lew", "Bulgaria", "Bulgarien", "euro", "euro since 2026", "Euro seit 2026"),
}
DEFAULT = ["USD", "GBP", "CHF", "CNY"]


def _get(freq, q):
    url = API.format(freq=freq, q=q)
    req = urllib.request.Request(url, headers={"User-Agent": "quarto-ecb-exr/1.0", "Accept": "text/csv"})
    for i in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))
        except Exception as e:  # noqa: BLE001 — Netz: zweimal nachfassen
            if i == 3:
                raise
            print(f"[ezb-fx] retry {i+1}: {e}")
            time.sleep(15 * (i + 1))


def _sig(v):
    """Auf 6 signifikante Stellen runden (Monatsdurchschnitte kommen mit 13 Nachkommastellen)."""
    if v == 0:
        return 0
    return round(v, max(0, 5 - int(math.floor(math.log10(abs(v))))))


def fetch():
    """Monatsreihen ab 1999 + letzter Tageskurs aller EXR-Waehrungen von der EZB holen."""
    rows = _get("M", f"startPeriod={START}")
    daily = _get("D", "lastNObservations=1")
    months = sorted({r["TIME_PERIOD"] for r in rows})
    ser = {}
    for r in rows:
        if r["OBS_VALUE"] not in ("", "NaN"):
            ser.setdefault(r["CURRENCY"], {})[r["TIME_PERIOD"]] = float(r["OBS_VALUE"])
    last = {r["CURRENCY"]: [r["TIME_PERIOD"], float(r["OBS_VALUE"])]
            for r in daily if r["OBS_VALUE"] not in ("", "NaN")}
    unknown = sorted(set(ser) - set(CUR))
    if unknown:
        print(f"[ezb-fx] WARN neue Waehrung(en) ohne Metadaten, ausgelassen: {', '.join(unknown)} "
              f"-> in CUR ergaenzen")
    return {"fetched": datetime.date.today().isoformat(), "months": months,
            "series": {c: {m: _sig(v) for m, v in sorted(d.items())} for c, d in ser.items()},
            "last": {c: [d, _sig(v)] for c, (d, v) in last.items()}}


def _compact(data):
    """Je Waehrung Startindex s (in months) + lueckenhafte Werteliste v (None = kein Kurs)."""
    months = data["months"]
    mi = {m: i for i, m in enumerate(months)}
    out = {}
    for c, s in data["series"].items():
        if not s:
            continue
        ks = sorted(s)
        a, b = mi[ks[0]], mi[ks[-1]]
        out[c] = {"s": a, "v": [s.get(months[i]) for i in range(a, b + 1)]}
    return out


def emit_json(path):
    data = fetch()
    live = {"fetched": data["fetched"], "months": data["months"], "cur": _compact(data),
            "last": data["last"]}
    Path(path).write_text(json.dumps(live, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[ezb-fx] Live-JSON -> {path}: {len(live['cur'])} Waehrungen, {data['months'][-1]}, "
          f"Tageskurs {max(d for d, _ in data['last'].values())}")


def update():
    out = fetch()
    months, ser, last = out["months"], out["series"], out["last"]
    CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"[ezb-fx] updated -> {CACHE.name}: {len(ser)} Waehrungen, {months[0]}…{months[-1]}, "
          f"Tageskurs {max(d for d, _ in last.values())}")
    return out


def _unit(vals):
    """Preisnotierung: Stueckelung 1/100/1000/10000 Fremdwaehrung, sodass der Median-Kurs >= 0,1 EUR."""
    med = sorted(vals)[len(vals) // 2]
    u = 1
    while (1 / med) * u < 0.1:
        u *= 10
    return u


UI = {
    "en": dict(
        title="The euro against the world's currencies",
        sub="ECB euro reference rates, monthly averages since January 1999 (the start of the euro). "
            "Pick the currencies, the period and the quotation.",
        qLab="Quotation", qInd="Indirect quotation (Mengennotierung)", qDir="Direct quotation (Preisnotierung)",
        qIndEx="€1 = … foreign currency", qDirEx="1 foreign unit = … €",
        pLab="Period", from_="from", to="to", max="since 1999",
        vLab="Show", vRate="Exchange rate", vIdx="Index (start of period = 100)",
        cLab="Currencies", cHint="Tick a currency in the table to add it to the chart (up to 8).",
        gLive="ECB reference rates", gEnded="Series ended", gEuro="Replaced by the euro",
        thCur="Currency", thToday="Latest daily rate", thStart="Start of period", thEnd="End of period",
        thChg="Change of the quoted rate", thEuro="The euro …",
        up="appreciated", down="depreciated", flat="unchanged",
        noData="no data in this period", tooMany="At most 8 currencies at a time — untick one first.",
        idxNote="Index: each line = 100 in the first month of the period with data.",
        search="Filter …",
        mon=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        loc="en-GB",
        did=[
            "<strong>Two ways to write the same rate.</strong> <em>Indirect quotation</em> (Mengennotierung) "
            "gives the <strong>quantity</strong> of foreign currency you get for €1 (e.g. €1 = 1.25 US$). "
            "<em>Direct quotation</em> (Preisnotierung) gives the <strong>euro price</strong> of one foreign unit "
            "(1 US$ = 0.80 €). Both say the same thing — one is the reciprocal of the other. The ECB quotes the "
            "euro indirectly. For currencies with very small unit values, the direct quotation is given for 100, "
            "1,000 or 10,000 units (as banks do).",
            "<strong>Careful when reading the line.</strong> In indirect quotation a <strong>rising</strong> line "
            "means the euro <strong>appreciates</strong> (€1 buys more). In direct quotation the same event makes "
            "the line <strong>fall</strong> (the foreign currency gets cheaper). Switch the quotation and watch the "
            "chart flip.",
            "<strong>The percentages differ.</strong> If €1 goes from 1.00 US$ to 1.25 US$ (+25 %), the dollar's "
            "price falls from 1.00 € to 0.80 € (−20 %). The column <em>The euro …</em> always tells you the "
            "euro's own move.",
            "<strong>Flat lines.</strong> Some currencies are <strong>pegged</strong> to the euro — the Danish krone, "
            "and the Bulgarian lev until Bulgaria adopted the euro. Compare them with a freely floating currency "
            "such as the US dollar.",
        ],
        foot="Source: European Central Bank (ECB), euro foreign exchange reference rates, dataset EXR — monthly "
             "averages (series EXR.M.&lt;currency&gt;.EUR.SP00.A) and the latest daily reference rate "
             "(EXR.D.…). Retrieved {fetched}: <a href=\"{portal}\">{portal}</a>. The ECB publishes these rates for "
             "information only; banks buy and sell at their own bid and ask rates. Real figures belong to the "
             "HTML layer of this course — the printed worksheets stay timeless.",
    ),
    "de": dict(
        title="Der Euro gegenüber den Währungen der Welt",
        sub="Euro-Referenzkurse der EZB, Monatsdurchschnitte seit Januar 1999 (Start des Euro). "
            "Wählen Sie Währungen, Zeitraum und Notierung.",
        qLab="Notierung", qInd="Mengennotierung", qDir="Preisnotierung",
        qIndEx="1 € = … Fremdwährung", qDirEx="1 Fremdwährungseinheit = … €",
        pLab="Zeitraum", from_="von", to="bis", max="seit 1999",
        vLab="Anzeige", vRate="Wechselkurs", vIdx="Index (Periodenbeginn = 100)",
        cLab="Währungen", cHint="Haken Sie eine Währung in der Tabelle an, um sie ins Diagramm zu holen (bis zu 8).",
        gLive="EZB-Referenzkurse", gEnded="Reihe eingestellt", gEuro="Durch den Euro ersetzt",
        thCur="Währung", thToday="Letzter Tageskurs", thStart="Periodenbeginn", thEnd="Periodenende",
        thChg="Änderung des notierten Kurses", thEuro="Der Euro …",
        up="hat aufgewertet", down="hat abgewertet", flat="unverändert",
        noData="keine Daten im Zeitraum", tooMany="Höchstens 8 Währungen gleichzeitig — bitte erst eine abwählen.",
        idxNote="Index: jede Linie = 100 im ersten Monat des Zeitraums mit Daten.",
        search="Filtern …",
        mon=["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"],
        loc="de-DE",
        did=[
            "<strong>Zwei Schreibweisen für denselben Kurs.</strong> Die <em>Mengennotierung</em> nennt die "
            "<strong>Menge</strong> an Fremdwährung, die man für 1 € erhält (z. B. 1 € = 1,25 US$). Die "
            "<em>Preisnotierung</em> nennt den <strong>Euro-Preis</strong> einer Fremdwährungseinheit "
            "(1 US$ = 0,80 €). Beide sagen dasselbe — die eine ist der Kehrwert der anderen. Die EZB notiert den "
            "Euro in Mengennotierung. Bei Währungen mit sehr kleinem Stückwert gilt die Preisnotierung für 100, "
            "1 000 oder 10 000 Einheiten (wie bei Banken üblich).",
            "<strong>Vorsicht beim Lesen der Linie.</strong> In der Mengennotierung heißt eine "
            "<strong>steigende</strong> Linie: Der Euro <strong>wertet auf</strong> (1 € bringt mehr). In der "
            "Preisnotierung lässt dasselbe Ereignis die Linie <strong>fallen</strong> (die Fremdwährung wird "
            "billiger). Schalten Sie die Notierung um und beobachten Sie, wie das Diagramm kippt.",
            "<strong>Die Prozentwerte unterscheiden sich.</strong> Steigt 1 € von 1,00 US$ auf 1,25 US$ (+25 %), "
            "fällt der Preis des Dollars von 1,00 € auf 0,80 € (−20 %). Die Spalte <em>Der Euro …</em> nennt immer "
            "die Bewegung des Euro selbst.",
            "<strong>Flache Linien.</strong> Manche Währungen sind an den Euro <strong>gebunden</strong> — die "
            "Dänische Krone und bis zur Euro-Einführung der Bulgarische Lew. Vergleichen Sie mit einer frei "
            "schwankenden Währung wie dem US-Dollar.",
        ],
        foot="Quelle: Europäische Zentralbank (EZB), Euro-Referenzkurse, Datensatz EXR — Monatsdurchschnitte "
             "(Reihen EXR.M.&lt;Währung&gt;.EUR.SP00.A) und letzter Tages-Referenzkurs (EXR.D.…). Abgerufen am "
             "{fetched}: <a href=\"{portal}\">{portal}</a>. Die EZB veröffentlicht die Kurse nur zur Information; "
             "Banken kaufen und verkaufen zu eigenen Geld- und Briefkursen. Reale Zahlen gehören in die "
             "HTML-Schicht — die gedruckten Arbeitsblätter bleiben zeitlos.",
    ),
}


def bake(data, lang):
    ui = dict(UI[lang])
    li = 0 if lang == "en" else 1
    comp = _compact(data)
    cur = {}
    for c, meta in CUR.items():
        if c not in comp:
            continue
        cur[c] = dict(comp[c], n=meta[li], r=meta[2 + li], g=meta[4], note=meta[5 + li],
                      u=_unit(list(data["series"][c].values())), last=data["last"].get(c))
    ui["foot"] = ui["foot"].format(fetched="__FETCHED__", portal=PORTAL)   # Datum setzt das JS (auch live)
    live = (f"https://raw.githubusercontent.com/{GITHUB_STATS_REPO}/main/{LIVE_FILE}"
            if GITHUB_STATS_REPO else "")
    payload = {"fetched": data["fetched"], "months": data["months"], "cur": cur, "def": DEFAULT,
               "ui": ui, "live": live}
    tpl = TEMPLATE.read_text(encoding="utf-8")
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return tpl.replace("/*__DATA__*/", js)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("bpe", nargs="?", help="BPE-Ordner (Ziel fuer _ezb-wechselkurs-widget.qmd)")
    ap.add_argument("--emit-json", metavar="DATEI", help="nur die Live-JSON schreiben (GitHub-Action)")
    ap.add_argument("--lang", choices=["en", "de"], default="de")
    ap.add_argument("--offline", action="store_true", help="nur aus dem Cache backen, nichts abrufen")
    a = ap.parse_args()
    if a.emit_json:
        emit_json(a.emit_json)
        return
    if not a.bpe:
        ap.error("BPE-Ordner fehlt (oder --emit-json <datei>)")
    if a.offline:
        if not CACHE.exists():
            sys.exit(f"[ezb-fx] kein Cache {CACHE} — ohne --offline laufen lassen")
        data = json.loads(CACHE.read_text(encoding="utf-8"))
    else:
        data = update()
    target = Path(a.bpe) / "_ezb-wechselkurs-widget.qmd"
    target.write_text(bake(data, a.lang), encoding="utf-8", newline="\n")
    kb = target.stat().st_size // 1024
    sample = ", ".join(f"{c} {data['last'][c][1]}" for c in DEFAULT if c in data["last"])
    print(f"[ezb-fx] gebacken -> {target} ({kb} KB, {a.lang}); 1 EUR = {sample} "
          f"(Tageskurs {data['last'].get('USD', ['?'])[0]}) | "
          f"Live-Repo: {GITHUB_STATS_REPO or '(nur gebacken)'}")


if __name__ == "__main__":
    main()
