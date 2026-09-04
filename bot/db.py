import sqlite3
from pathlib import Path

from bot.config import DB_PATH

# Fresh installs get the final structure directly from this SCHEMA. Existing
# databases (CREATE TABLE IF NOT EXISTS is a no-op on a table that already
# exists) are brought up to date additively by _migrate() below.
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    first_name TEXT,
    username TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- `type` stays 'card' vs 'loyalty' only (Phase 7.5, 14B.1): SQLite can't
-- ALTER a CHECK constraint without rebuilding the table, and 'loyalty'
-- already generically covers "not a payment card" - traditional loyalty
-- programs AND membership/rewards programs (e.g. Shell ClubSmart) alike.
-- `source` distinguishes the admin-curated catalog from a program a user
-- typed in themselves (14B.3); `owner_user_id` is set only for the latter,
-- so it can never be shown to or edited by any other user (14B.10).
-- `usage_context` is the optional "where do you mainly use this" answer
-- from the custom-program flow (14B.2) - free-form is fine, it's a hint,
-- not something matched against structurally.
CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK (type IN ('card', 'loyalty')),
    unit_label TEXT,
    emoji TEXT,
    source TEXT NOT NULL DEFAULT 'catalog' CHECK (source IN ('catalog', 'user')),
    owner_user_id INTEGER REFERENCES users(telegram_id),
    usage_context TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS card_profile (
    user_id INTEGER NOT NULL REFERENCES users(telegram_id),
    program_id INTEGER NOT NULL REFERENCES programs(id),
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, program_id)
);

CREATE TABLE IF NOT EXISTS point_balances (
    user_id INTEGER NOT NULL REFERENCES users(telegram_id),
    program_id INTEGER NOT NULL REFERENCES programs(id),
    balance INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, program_id)
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(telegram_id),
    program_id INTEGER NOT NULL REFERENCES programs(id),
    label TEXT NOT NULL,
    target_amount INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recommendation_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    program_id INTEGER NOT NULL REFERENCES programs(id),
    note TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    subcategory TEXT,
    warning TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    rule_key TEXT
);

-- category/merchant/loyalty_program/confidence are set once at ingestion time
-- (see bot/deals/matcher.py classify_deal) from simple, transparent keyword
-- rules - no LLM. valid_until/multiplier are deliberately NOT modeled as
-- columns: reliably parsing "bis 08.09." or "5x Punkte" out of arbitrary
-- blog prose is not something this project can do accurately, and a wrong
-- guess here would violate the "no invented promises" rule worse than just
-- not having the field - see docs/PHASE7_REPORT.md.
CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    summary TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    category TEXT,
    merchant TEXT,
    loyalty_program TEXT,
    confidence TEXT,
    UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS user_deal_notifications (
    user_id INTEGER NOT NULL REFERENCES users(telegram_id),
    deal_id INTEGER NOT NULL REFERENCES deals(id),
    notified_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, deal_id)
);

-- One row per user (1:1). preferred_airports/preferred_airlines are plain
-- comma-separated text by deliberate choice, not JSON: they're free-form,
-- user-typed lists with no fixed schema, so a relational child table would
-- add a full add/remove UI for little benefit at this stage (see
-- docs/OVERNIGHT_REPORT.md). travel_class/priority/preferred_alliance are
-- plain TEXT holding one of a small fixed set of keys, set only via button
-- pickers - never free text - so they stay simple flat columns too.
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(telegram_id),
    home_airport TEXT,
    preferred_airports TEXT,
    preferred_airlines TEXT,
    preferred_alliance TEXT,
    travel_class TEXT,
    priority TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Access-request system (Phase 7I). ALLOWED_USER_IDS (.env) remains the
-- bootstrap/admin allowlist - never touched by this table. A user not in
-- ALLOWED_USER_IDS is authorized only if their row here has status='approved'.
-- Only an ALLOWED_USER_IDS admin can move a row to approved/rejected (checked
-- server-side in bot/handlers/access.py, never trusted from callback data).
CREATE TABLE IF NOT EXISTS access_requests (
    telegram_id INTEGER PRIMARY KEY,
    first_name TEXT,
    username TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_at TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at TEXT,
    decided_by INTEGER
);

-- Shopping Optimizer (Phase 7.5). Deliberately separate from `deals`: a
-- deal is a news article ("this happened"), a shopping_partners row is a
-- standing (or currently promoted) reward rate at a specific merchant
-- ("this is available if you shop here"). `reward_rate`/`reward_unit` are
-- only ever set when a source's rate text parses unambiguously as a plain
-- per-euro ratio (e.g. "1 °P pro 2 €") - conditional/flat offers (e.g.
-- "bis zu 7.600 °P", "500 °P pro Abo") keep reward_rate NULL and store the
-- raw text in promotion_text instead, so the UI never invents a per-euro
-- number that wasn't actually stated. UNIQUE(source, merchant_slug) makes
-- refreshing an upsert (rate can change over time) rather than an insert -
-- last_verified_at tracks when a row was last confirmed against the source.
CREATE TABLE IF NOT EXISTS shopping_partners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loyalty_program_id INTEGER REFERENCES programs(id),
    merchant TEXT NOT NULL,
    merchant_slug TEXT NOT NULL,
    category TEXT,
    reward_type TEXT,
    reward_rate REAL,
    reward_unit TEXT,
    is_promotion INTEGER NOT NULL DEFAULT 0,
    promotion_text TEXT,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    landing_url TEXT,
    valid_from TEXT,
    valid_until TEXT,
    last_verified_at TEXT NOT NULL DEFAULT (datetime('now')),
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (source, merchant_slug)
);

-- Prepared architecture for verified transfer relationships between two
-- programs (14B.7) - e.g. "Membership Rewards -> Miles & More". Empty by
-- design in Phase 7.5: no transfer ratio is seeded here because none has
-- been verified against a current source (see docs/SHOPPING_OPTIMIZER.md).
-- No optimizer logic reads this table yet - it only exists so a future,
-- verified entry doesn't need a schema change to be added.
CREATE TABLE IF NOT EXISTS program_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_program_id INTEGER NOT NULL REFERENCES programs(id),
    target_program_id INTEGER NOT NULL REFERENCES programs(id),
    transfer_ratio TEXT,
    is_promotion INTEGER NOT NULL DEFAULT 0,
    source_url TEXT,
    last_verified_at TEXT,
    valid_from TEXT,
    valid_until TEXT,
    active INTEGER NOT NULL DEFAULT 1
);
"""

# name, type, unit_label, emoji — cards have no unit_label/emoji since balances
# and goals only ever apply to type='loyalty' programs.
DEFAULT_PROGRAMS = [
    ("Trade Republic", "card", None, None),
    ("Payback American Express", "card", None, None),
    ("Wise", "card", None, None),
    ("Revolut", "card", None, None),
    ("Payback", "loyalty", "Punkte", "🟡"),
    ("Miles & More", "loyalty", "Meilen", "🔵"),
    ("Membership Rewards", "loyalty", "Punkte", "🟢"),
    ("Flying Blue", "loyalty", "Meilen", "🔷"),
    ("Avios", "loyalty", "Avios", "🟣"),
    ("Marriott Bonvoy", "loyalty", "Punkte", "🏨"),
    ("Hilton Honors", "loyalty", "Punkte", "⭐"),
    ("Shell ClubSmart", "loyalty", "Punkte", "⛽"),
]

# Deterministic alias -> canonical catalog program name (14B.4). Lowercased,
# trimmed comparison - no fuzzy matching, so a near-miss is deliberately
# stored as the user's own program rather than silently merged into the
# wrong catalog entry. Extend this whenever a real recognizable spelling
# variant comes up; every program not listed here still works, it just
# always becomes a user-owned entry on first mention.
KNOWN_PROGRAM_ALIASES = {
    "shell clubsmart": "Shell ClubSmart",
    "shell club smart": "Shell ClubSmart",
    "clubsmart": "Shell ClubSmart",
    "club smart": "Shell ClubSmart",
    "payback": "Payback",
    "miles and more": "Miles & More",
    "miles & more": "Miles & More",
    "milesandmore": "Miles & More",
    "m&m": "Miles & More",
    "amex membership rewards": "Membership Rewards",
    "membership rewards": "Membership Rewards",
    "flying blue": "Flying Blue",
    "avios": "Avios",
    "marriott bonvoy": "Marriott Bonvoy",
    "bonvoy": "Marriott Bonvoy",
    "hilton honors": "Hilton Honors",
    "hilton": "Hilton Honors",
}

# Conservative Phase-3 starter rules for /zahlen. Only well-established, generic
# facts (e.g. "Payback Amex earns Payback points") - no invented cashback
# percentages, FX rates, or promotions. Trade Republic intentionally has no
# rules yet: its actual saveback/cashback conditions aren't verified here, and
# per the "no invented benefits" requirement the neutral choice is to not
# recommend it until real conditions are maintained in this table.
# rule_key, program_name, category, subcategory, note (Begründung), warning, priority
RECOMMENDATION_RULE_SEEDS = [
    ("pbamex_restaurant", "Payback American Express", "restaurant", None,
     "Alltägliche EUR-Ausgabe – du sammelst PAYBACK-Punkte.", None, 10),
    ("pbamex_supermarkt", "Payback American Express", "supermarkt", None,
     "Alltägliche EUR-Ausgabe – du sammelst PAYBACK-Punkte.", None, 10),
    ("pbamex_shopping_stationaer", "Payback American Express", "shopping", "stationaer",
     "Kartenzahlung im Geschäft – du sammelst PAYBACK-Punkte.", None, 10),
    ("pbamex_shopping_online", "Payback American Express", "shopping", "online",
     "Du sammelst PAYBACK-Punkte.",
     "American Express wird nicht von jedem Online-Shop akzeptiert – prüfe vorab, ob eine Alternative nötig ist.", 7),
    ("pbamex_online", "Payback American Express", "online", None,
     "Du sammelst PAYBACK-Punkte.",
     "American Express wird nicht von jedem Anbieter akzeptiert – prüfe vorab, ob eine Alternative nötig ist.", 7),
    ("pbamex_tanken", "Payback American Express", "tanken", None,
     "Alltägliche EUR-Ausgabe – du sammelst PAYBACK-Punkte.",
     "Nicht jede Tankstelle akzeptiert American Express.", 8),
    ("pbamex_bahn", "Payback American Express", "bahn", None,
     "Alltägliche EUR-Ausgabe – du sammelst PAYBACK-Punkte.", None, 8),
    ("pbamex_sonstiges", "Payback American Express", "sonstiges", None,
     "Alltägliche EUR-Ausgabe – du sammelst PAYBACK-Punkte.", None, 5),
    ("pbamex_ausland_karte", "Payback American Express", "ausland", "karte",
     "Du sammelst weiterhin PAYBACK-Punkte.",
     "Bei Zahlungen in Fremdwährung können Gebühren anfallen – prüfe die aktuellen Konditionen.", 3),
    ("pbamex_hotel", "Payback American Express", "hotel", None,
     "Du sammelst PAYBACK-Punkte.", None, 5),
    ("pbamex_flug", "Payback American Express", "flug", None,
     "Du sammelst PAYBACK-Punkte.", None, 3),
    ("wise_ausland_karte", "Wise", "ausland", "karte",
     "Für Zahlungen in Fremdwährung im Ausland konzipiert.",
     "Wechselkurse, Gebühren und Limits können sich ändern – prüfe die aktuellen Konditionen in der App.", 10),
    ("wise_ausland_bargeld", "Wise", "ausland", "bargeld",
     "Für Bargeldabhebungen im Ausland geeignet.",
     "Kostenlose Abhebe-Limits und Gebühren können sich ändern – prüfe die aktuellen Konditionen in der App.", 10),
    ("wise_bargeld", "Wise", "bargeld", None,
     "Für Bargeldabhebungen geeignet.",
     "Kostenlose Abhebe-Limits und Gebühren können sich ändern – prüfe die aktuellen Konditionen in der App.", 5),
    ("wise_flug", "Wise", "flug", None,
     "Buchungen in Fremdwährung können hierüber günstiger abgerechnet werden.",
     "Wechselkurse und Gebühren können sich ändern – prüfe die aktuellen Konditionen.", 6),
    ("wise_hotel", "Wise", "hotel", None,
     "Buchungen in Fremdwährung können hierüber günstiger abgerechnet werden.",
     "Wechselkurse und Gebühren können sich ändern – prüfe die aktuellen Konditionen.", 6),
    ("wise_online", "Wise", "online", None,
     "Sinnvoll, falls der Anbieter in Fremdwährung abrechnet.",
     "Wechselkurse und Gebühren können sich ändern – prüfe die aktuellen Konditionen.", 4),
    ("wise_shopping_online", "Wise", "shopping", "online",
     "Sinnvoll, falls der Anbieter in Fremdwährung abrechnet.",
     "Wechselkurse und Gebühren können sich ändern – prüfe die aktuellen Konditionen.", 4),
    ("revolut_ausland_karte", "Revolut", "ausland", "karte",
     "Für Zahlungen in Fremdwährung im Ausland konzipiert.",
     "Wechselkurse, Gebühren und Limits können sich ändern – prüfe die aktuellen Konditionen in der App.", 10),
    ("revolut_ausland_bargeld", "Revolut", "ausland", "bargeld",
     "Für Bargeldabhebungen im Ausland geeignet.",
     "Kostenlose Abhebe-Limits und Gebühren können sich ändern – prüfe die aktuellen Konditionen in der App.", 10),
    ("revolut_bargeld", "Revolut", "bargeld", None,
     "Für Bargeldabhebungen geeignet.",
     "Kostenlose Abhebe-Limits und Gebühren können sich ändern – prüfe die aktuellen Konditionen in der App.", 5),
    ("revolut_flug", "Revolut", "flug", None,
     "Buchungen in Fremdwährung können hierüber günstiger abgerechnet werden.",
     "Wechselkurse und Gebühren können sich ändern – prüfe die aktuellen Konditionen.", 6),
    ("revolut_hotel", "Revolut", "hotel", None,
     "Buchungen in Fremdwährung können hierüber günstiger abgerechnet werden.",
     "Wechselkurse und Gebühren können sich ändern – prüfe die aktuellen Konditionen.", 6),
    ("revolut_online", "Revolut", "online", None,
     "Sinnvoll, falls der Anbieter in Fremdwährung abrechnet.",
     "Wechselkurse und Gebühren können sich ändern – prüfe die aktuellen Konditionen.", 4),
    ("revolut_shopping_online", "Revolut", "shopping", "online",
     "Sinnvoll, falls der Anbieter in Fremdwährung abrechnet.",
     "Wechselkurse und Gebühren können sich ändern – prüfe die aktuellen Konditionen.", 4),
]


def get_connection() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for databases created before Phase 2B. Never drops
    or rewrites existing data."""
    if not _column_exists(conn, "programs", "unit_label"):
        conn.execute("ALTER TABLE programs ADD COLUMN unit_label TEXT")
    if not _column_exists(conn, "programs", "emoji"):
        conn.execute("ALTER TABLE programs ADD COLUMN emoji TEXT")
    if not _column_exists(conn, "goals", "is_active"):
        conn.execute("ALTER TABLE goals ADD COLUMN is_active INTEGER NOT NULL DEFAULT 0")
    if not _column_exists(conn, "recommendation_rules", "subcategory"):
        conn.execute("ALTER TABLE recommendation_rules ADD COLUMN subcategory TEXT")
    if not _column_exists(conn, "recommendation_rules", "warning"):
        conn.execute("ALTER TABLE recommendation_rules ADD COLUMN warning TEXT")
    if not _column_exists(conn, "recommendation_rules", "is_active"):
        conn.execute("ALTER TABLE recommendation_rules ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    if not _column_exists(conn, "recommendation_rules", "rule_key"):
        conn.execute("ALTER TABLE recommendation_rules ADD COLUMN rule_key TEXT")
    if not _column_exists(conn, "deals", "category"):
        conn.execute("ALTER TABLE deals ADD COLUMN category TEXT")
    if not _column_exists(conn, "deals", "merchant"):
        conn.execute("ALTER TABLE deals ADD COLUMN merchant TEXT")
    if not _column_exists(conn, "deals", "loyalty_program"):
        conn.execute("ALTER TABLE deals ADD COLUMN loyalty_program TEXT")
    if not _column_exists(conn, "deals", "confidence"):
        conn.execute("ALTER TABLE deals ADD COLUMN confidence TEXT")
    if not _column_exists(conn, "programs", "source"):
        conn.execute("ALTER TABLE programs ADD COLUMN source TEXT NOT NULL DEFAULT 'catalog'")
    if not _column_exists(conn, "programs", "owner_user_id"):
        conn.execute("ALTER TABLE programs ADD COLUMN owner_user_id INTEGER")
    if not _column_exists(conn, "programs", "usage_context"):
        conn.execute("ALTER TABLE programs ADD COLUMN usage_context TEXT")
    if not _column_exists(conn, "programs", "is_active"):
        conn.execute("ALTER TABLE programs ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

    # Enforces "at most one active goal per user" at the database level.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_goals_one_active_per_user "
        "ON goals(user_id) WHERE is_active = 1"
    )
    # Lets seed rules be upserted by a stable key (see init_db) instead of
    # duplicating on every restart. SQLite UNIQUE indexes already allow
    # multiple NULLs, so hand-written (non-seed) rules without a rule_key
    # are unaffected.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_recommendation_rules_rule_key "
        "ON recommendation_rules(rule_key)"
    )


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        # Upsert by name: fills in unit_label/emoji for programs seeded before
        # Phase 2B and adds the new programs, without touching card_profile /
        # point_balances / goals rows, which reference the stable program id.
        conn.executemany(
            """
            INSERT INTO programs (name, type, unit_label, emoji) VALUES (?, ?, ?, ?)
            ON CONFLICT (name) DO UPDATE SET
                type = excluded.type,
                unit_label = excluded.unit_label,
                emoji = excluded.emoji
            """,
            DEFAULT_PROGRAMS,
        )

        program_ids = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM programs")}
        rule_rows = [
            (rule_key, category, subcategory, program_ids[program_name], note, warning, priority)
            for rule_key, program_name, category, subcategory, note, warning, priority in RECOMMENDATION_RULE_SEEDS
        ]
        conn.executemany(
            """
            INSERT INTO recommendation_rules
                (rule_key, category, subcategory, program_id, note, warning, priority, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT (rule_key) DO UPDATE SET
                category = excluded.category,
                subcategory = excluded.subcategory,
                program_id = excluded.program_id,
                note = excluded.note,
                warning = excluded.warning,
                priority = excluded.priority,
                is_active = 1
            """,
            rule_rows,
        )
        conn.commit()
    finally:
        conn.close()
