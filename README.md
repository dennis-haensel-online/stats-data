# Statistik-Widget — jährliche Auto-Aktualisierung über GitHub (optional)

Das WB-Statistik-Widget (`stats-widget.py` → `_stats-widget.qmd`) funktioniert **sofort ohne alles**:
die Daten sind in die Seite **gebacken** (Fallback, alle Länder, Stand des letzten Backens). Dieser
Ordner richtet — analog zum Newsticker (`_assets/newsticker-github/`) — einen **Live-Layer** ein, der
die Zahlen **jährlich von selbst aktualisiert**, ohne die Seite neu zu rendern.

## Wie es funktioniert (Antwort auf „macht das die Ladezeit groß?")

- Die Seite rendert **sofort** aus den gebackenen Fallback-Daten.
- Zusätzlich holt das Widget **asynchron** (nach dem Rendern, unter dem Fold) eine `wb-stats.json` von
  GitHub (`fetch(..., {cache:"no-store"})`). Klappt der Abruf, ersetzt er die gebackenen Daten; klappt
  er nicht (offline, Moodle-CSP, Repo fehlt), bleibt der Fallback stehen — **fail-safe**.
- Die JSON ist ~180 KB, gzip ~40 KB, und der Fetch blockiert das Rendern nicht → **kein spürbarer
  Ladezeit-Effekt**. Exakt dasselbe Muster wie der Newsticker.

## Einrichtung (einmalig)

1. **Öffentliches Repo anlegen**, z. B. `dein-github-name/stats-data` (analog `newsticker-data`).
2. Aus diesem Ordner **kopieren** in das neue Repo (beide Widgets teilen sich ein Repo):
   - `_assets/stats-widget.py` → dort als `stats-widget.py` (Weltbank, jährlich).
   - `_assets/eurostat-widget.py` → dort als `eurostat-widget.py` (Eurostat).
   - `refresh-stats.yml` **und** `refresh-eurostat.yml` → dort nach `.github/workflows/`.
3. Im Repo **Actions aktivieren** und beide einmal manuell starten (`Run workflow`) → sie legen
   `wb-stats.json` und `eurostat-stats.json` an. Danach laufen **beide täglich**
   und committen jeweils **nur bei echter Änderung** (Weltbank-Werte ändern sich real meist einmal im
   Jahr bzw. bei Revisionen, Eurostat monatlich).
4. In **beiden** Skripten (`_assets/stats-widget.py` **und** `_assets/eurostat-widget.py`, Hauptrepo)
   `GITHUB_STATS_REPO = "dein-github-name/stats-data"` setzen und die BPE-Seite **einmal neu backen**
   (`python _assets/stats-widget.py <bpe-ordner>` **und** `python _assets/eurostat-widget.py <bpe-ordner>`).
   Ab jetzt holen die Widgets die Live-JSON; der gebackene Stand bleibt Fallback.

> **Bequemer Weg für Schritt 2 (und alle späteren Updates):**
> `python _assets/push-data-repos.py --repo stats` klont `stats-data`, kopiert die vier Dateien
> (beide Skripte + beide Workflows nach `.github/workflows/`) LF-normalisiert hinein und pusht —
> committet **nur bei echter Änderung**. Existiert `stats-data` noch nicht, nennt das Skript die
> Anlege-Schritte (Repo selbst anlegen kann es nicht). Die Punkte 1, 3 und 4 oben bleiben manuell.

## Rollout auf BPE 19/20 + 22

Dieselbe `wb-stats.json` deckt alle BPEs ab (alle Länder, alle Kennzahlen). Für weitere BPE-Seiten
einfach dort ebenfalls `python _assets/stats-widget.py <bpe-ordner>` ausführen und `{{< include
_stats-widget.qmd >}}` unter den Newsticker setzen — kein zweites Daten-Repo nötig.

## Eurostat-Widget (monatlich, europäisch)

Das separate Eurostat-Widget (`eurostat-widget.py` → `_eurostat-widget.qmd`) folgt exakt demselben
Muster (gebacken + optionaler Live-Fetch von `eurostat-stats.json`). Die zugehörige Action
`refresh-eurostat.yml` läuft **täglich** (Eurostat liefert Monatswerte, wird aber täglich abgefragt). Beide Actions prüfen also
**täglich** und liegen im selben `stats-data`-Repo; committet wird nur bei echter Änderung — beim
Eurostat-Widget real jeden Monat, beim Weltbank-Widget effektiv, sobald die WB neue Jahres- oder
revidierte Werte veröffentlicht.
