# Future Monetization (nicht implementiert)

Keine Payments, kein Stripe, keine Telegram Payments, keine Abos in diesem Projekt. Dieses Dokument hält nur fest, wie das bestehende Access-Modell (Phase 7I) eine spätere Monetarisierung nicht verbaut.

## Saubere Trennung, die bereits besteht

- **Authorization** (`bot/whitelist.py`, `access_requests`-Tabelle): entscheidet nur, ob jemand den Bot überhaupt nutzen darf. Kennt nichts von Bezahlung.
- **User Profile** (`users`, `card_profile`, `user_preferences`, …): die eigentlichen Nutzerdaten, unabhängig vom Zugriffsstatus.
- **Zukünftiger Subscription State**: existiert noch nicht. Ließe sich additiv als eigene Tabelle (z. B. `subscriptions(user_id, tier, valid_until)`) ergänzen, ohne `access_requests` oder `users` anzufassen.

## Mögliche spätere Stufen (nur Skizze, keine Umsetzung)

1. **Beta/Manual Access** (aktueller Stand): Zugriff nur nach manueller Freigabe durch einen Admin.
2. **Free**: jeder freigegebene Nutzer, wie heute – Kernfunktionen kostenlos.
3. **Premium**: zusätzliche Funktionen (z. B. Sofort-Alerts statt nur Daily Digest, mehr Deal-Quellen) hinter einem `subscriptions`-Flag.
4. **Subscription**: Abrechnung über Telegram Payments oder Stripe – separates Thema, das eigene Sicherheits- und Compliance-Anforderungen hätte und hier bewusst nicht angerührt wurde.

Keine dieser Stufen ist heute technisch vorbereitet über das Nötigste hinaus – nur die Trennung der Datenmodelle stellt sicher, dass eine spätere Ergänzung additiv bleibt.
