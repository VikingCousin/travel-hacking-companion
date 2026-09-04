# Shopping Optimizer (`/shopping`, 🔎 Einkauf optimieren)

## Zweck

Unterschied zu `/deals`: `/deals` ist ein proaktiver News-/Aktionsfeed. `/shopping` beantwortet eine konkrete Kaufabsicht: "Ich will X kaufen – wo starte ich, um möglichst viele Punkte/Meilen mitzunehmen?" Freitext-Kategorie-Eingabe (z. B. "Schuhe"), optional ein ungefährer Kaufbetrag, dann eine Liste verifizierter Shopping-Partner, gruppiert nach den Loyalty-Programmen im eigenen Profil.

## Unterstützte Programme

Jedes `type='loyalty'`-Programm im Profil des Nutzers kann grundsätzlich Shopping-Partner haben – aktuell mit echten Daten hinterlegt: **Payback**. Architektur ist bewusst nicht Payback-spezifisch (siehe `bot/shopping/service.py`), ein weiteres Programm braucht nur eine weitere Quelle in `bot/shopping/sources.py` plus einen Parser.

## Unterstützte Quellen (vor dem Bauen recherchiert)

| Quelle | Status | Begründung |
|---|---|---|
| `payback.de/online-shopping` | ✅ aktiv genutzt | Serverseitig gerendertes HTML (Next.js/MUI), `robots.txt` erlaubt den Pfad, Struktur wurde live inspiziert (nicht geraten) und ist klein genug für einen robusten, defensiven Regex-Parser (`bot/shopping/fetcher.py`). Zeigt eine kuratierte "Featured Partners"-Liste, **nicht** den vollständigen Payback-Katalog (der erfordert die interaktive Shop-Suche, die hier nicht automatisiert wird). |
| `miles-and-more.com` (Shopping-Portal) | ❌ nicht genutzt | Jeder getestete Pfad (inkl. der bloßen Domain) liefert HTTP 403 durch Bot-Schutz. Nicht umgangen – das wäre "Umgehung technischer Schutzmaßnahmen" und ausdrücklich verboten. Dokumentiert statt erzwungen. |
| PAYBACK-Login / persönliche Coupons | ❌ nie | Kein Login, kein Scraping des persönlichen Kontos – siehe unten. |

## Wie aktuell sind die Reward-Raten?

Jede Zeile in `shopping_partners` hat ein `last_verified_at` (Zeitpunkt des letzten erfolgreichen Refreshs) und `source_url` (die tatsächlich abgefragte Seite). Automatischer Refresh alle 24 Stunden per JobQueue, zusätzlich `/deals`-artiges manuelles `[🔄 Aktualisieren]` ist für `/shopping` (noch) nicht vorgesehen – Suchen lesen primär aus der DB (Caching-Pflicht aus der Spezifikation), kein Live-Fetch pro Suche.

**Wichtig:** Nur Raten in der klaren Form "N °P pro M €" werden als numerische `reward_rate` gespeichert. Alles andere ("Bis zu X °P", "X °P pro Buchung/Abo") bleibt als reiner Text (`promotion_text`) erhalten – nie als erfundene Zahl interpretiert. Für Nutzer ohne verifizierte Rate zeigt der Bot: "Aktuelle Reward-Rate konnte nicht zuverlässig bestimmt werden."

## Ranking

1. Aktive, verifizierte Promotion (aktuell nie gesetzt – die Payback-Landingpage unterscheidet nicht zuverlässig zwischen Dauer-Rate und Zeit-Aktion, also wird `is_promotion` nie ohne echten Beleg auf `true` gesetzt)
2. Innerhalb desselben Programms: höhere verifizierte Rate zuerst
3. Programme werden **niemals** anhand ihrer rohen Zahl gegeneinander sortiert (Payback-Punkte ≠ Miles-&-More-Meilen) – die Cross-Programm-Reihenfolge nutzt nur ein einheitenunabhängiges Signal (aktive Promotion vorhanden ja/nein)
4. Ergebnis wird pro Programm gruppiert angezeigt ("beste PAYBACK-Option", "höchste Miles-&-More-Rate"), nie als ein einziges gemischtes Ranking mit impliziter Punkt=Meile-Gleichsetzung

## PAYBACK-Grenze

Keine Anmeldung, kein Scraping des persönlichen Kontos, keine automatisierte Extraktion persönlicher Coupons. Alles, was der Bot zeigt, stammt von der öffentlichen Landingpage – entsprechend heißt es immer "öffentliche Aktion", nie "dein Coupon" oder "deine Aktion". Persönliche Payback-Coupons sind komplett außerhalb dieses Systems.

## Keine garantierte Stackability

Portal-Reward (z. B. Payback-Punkte beim Einkauf über den Shopping-Link) und die Kartenempfehlung aus `/zahlen` werden nie automatisch addiert. Der `[💳 Passende Karte]`-Button öffnet den bestehenden Phase-3-Recommender separat, mit dem Hinweis, vor dem Kauf selbst zu prüfen, ob beides kombinierbar ist.

## Custom/Rewards-Programme (14B)

Katalog (`programs.source='catalog'`) und nutzereigene Programme (`source='user'`, `owner_user_id` gesetzt) sind strikt getrennt: ein nutzereigenes Programm ist ausschließlich für diesen Nutzer sichtbar, nie für andere, und wird nie automatisch in den globalen Katalog übernommen. Ein bekannter Alias (z. B. "Shell Club Smart" → "Shell ClubSmart") wird deterministisch erkannt – kein Fuzzy-Matching, kein LLM. Ein unbekanntes Programm bedeutet ausschließlich "der Nutzer besitzt es" – niemals werden daraus Benefits, Punkteraten oder Transferverhältnisse erfunden. `program_transfers` existiert als Architektur für später verifizierte Transferbeziehungen, ist aber aktuell leer.

## Bekannte Einschränkungen

- Nur Payback hat echte Shopping-Partner-Daten; andere Programme zeigen ehrlich "keine passende Option gefunden", bis eine verifizierte Quelle existiert.
- Die Payback-Landingpage zeigt nur eine kleine, kuratierte Auswahl – kein vollständiger Kategorie-Katalog.
- Kein Ablaufdatum (`valid_until`) wird geparst – die Quelle stellt das nicht zuverlässig maschinenlesbar bereit.
- Digest-/Refresh-Frequenz ist global, nicht pro Nutzer konfigurierbar (wie bei `/deals`, siehe `docs/PHASE7_REPORT.md`).
