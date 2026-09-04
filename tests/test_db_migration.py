"""Verifies the current schema (after all additive migrations) has every
expected table/column and that the DB-level integrity constraints introduced
along the way are actually enforced. For the fuller "upgrade a real
pre-Phase-2B database without losing data" scenario, see the manual checks
logged in docs/OVERNIGHT_REPORT.md - re-deriving that full historic schema
here would mostly duplicate bot/db.py's own SCHEMA constant.

Run with:
    python tests/test_db_migration.py
"""

import os
import sqlite3
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

TEST_DB = "/tmp/th_migration_check.sqlite3"
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

os.environ["BOT_TOKEN"] = "dummy:token"
os.environ["ALLOWED_USER_IDS"] = "1"
os.environ["DB_PATH"] = TEST_DB

from bot.db import get_connection, init_db  # noqa: E402

passed = 0


def check(label, condition):
    global passed
    assert condition, f"FAILED: {label}"
    passed += 1
    print(f"OK {label}")


init_db()
init_db()  # idempotency

conn = get_connection()

EXPECTED_COLUMNS = {
    "programs": {"id", "name", "type", "unit_label", "emoji", "source", "owner_user_id", "usage_context", "is_active"},
    "goals": {"id", "user_id", "program_id", "label", "target_amount", "is_active", "created_at"},
    "recommendation_rules": {
        "id", "category", "program_id", "note", "priority", "subcategory", "warning", "is_active", "rule_key"
    },
    "deals": {
        "id", "source", "external_id", "title", "url", "summary", "published_at", "fetched_at",
        "category", "merchant", "loyalty_program", "confidence",
    },
    "user_deal_notifications": {"user_id", "deal_id", "notified_at"},
    "user_preferences": {
        "user_id", "home_airport", "preferred_airports", "preferred_airlines",
        "preferred_alliance", "travel_class", "priority", "updated_at",
    },
    "access_requests": {"telegram_id", "first_name", "username", "status", "requested_at", "decided_at", "decided_by"},
    "shopping_partners": {
        "id", "loyalty_program_id", "merchant", "merchant_slug", "category", "reward_type",
        "reward_rate", "reward_unit", "is_promotion", "promotion_text", "source", "source_url",
        "landing_url", "valid_from", "valid_until", "last_verified_at", "active",
    },
    "program_transfers": {
        "id", "source_program_id", "target_program_id", "transfer_ratio", "is_promotion",
        "source_url", "last_verified_at", "valid_from", "valid_until", "active",
    },
}
for table, expected_cols in EXPECTED_COLUMNS.items():
    actual = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    check(f"table `{table}` has all expected columns", expected_cols <= actual)

check("12 default programs seeded (incl. Shell ClubSmart, Phase 7.5)", conn.execute("SELECT COUNT(*) c FROM programs").fetchone()["c"] == 12)
check(
    "recommendation_rules seeded (Trade Republic deliberately excluded)",
    conn.execute("SELECT COUNT(*) c FROM recommendation_rules").fetchone()["c"] == 25,
)

# Constraint: at most one active goal per user
conn.execute("INSERT INTO users (telegram_id, first_name) VALUES (1, 'T')")
payback_id = conn.execute("SELECT id FROM programs WHERE name='Payback'").fetchone()["id"]
conn.execute(
    "INSERT INTO goals (user_id, program_id, label, target_amount, is_active) VALUES (1, ?, 'A', 100, 1)",
    (payback_id,),
)
conn.commit()
try:
    conn.execute(
        "INSERT INTO goals (user_id, program_id, label, target_amount, is_active) VALUES (1, ?, 'B', 200, 1)",
        (payback_id,),
    )
    conn.commit()
    raised = False
except sqlite3.IntegrityError:
    conn.rollback()
    raised = True
check("DB-Constraint verhindert zwei aktive Ziele für denselben User", raised)

# Constraint: deals dedup via UNIQUE(source, external_id)
conn.execute(
    "INSERT INTO deals (source, external_id, title, url) VALUES ('src', 'ext1', 'T', 'https://x')"
)
conn.commit()
try:
    conn.execute(
        "INSERT INTO deals (source, external_id, title, url) VALUES ('src', 'ext1', 'T2', 'https://y')"
    )
    conn.commit()
    dup_raised = False
except sqlite3.IntegrityError:
    conn.rollback()
    dup_raised = True
check("DB-Constraint verhindert doppelte Deals (source, external_id)", dup_raised)

# Constraint: shopping_partners dedup via UNIQUE(source, merchant_slug)
conn.execute(
    "INSERT INTO shopping_partners (merchant, merchant_slug, source, source_url) VALUES ('T', 'testshop', 'src', 'https://x')"
)
conn.commit()
try:
    conn.execute(
        "INSERT INTO shopping_partners (merchant, merchant_slug, source, source_url) VALUES ('T2', 'testshop', 'src', 'https://y')"
    )
    conn.commit()
    shop_dup_raised = False
except sqlite3.IntegrityError:
    conn.rollback()
    shop_dup_raised = True
check("DB-Constraint verhindert doppelte shopping_partners (source, merchant_slug)", shop_dup_raised)

conn.close()
os.remove(TEST_DB)

print(f"\nALL {passed} DB MIGRATION/SCHEMA CHECKS PASSED")
