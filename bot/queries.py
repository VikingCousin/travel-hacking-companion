"""Shared read/write helpers used by /punkte, /ziele and /status so the three
handlers don't each duplicate the same SQL."""

import sqlite3


def loyalty_programs_for_user(conn: sqlite3.Connection, user_id: int):
    """Loyalty programs from the user's own /profil selection, with their
    current balance (NULL if none has been entered yet)."""
    return conn.execute(
        """
        SELECT p.id, p.name, p.unit_label, p.emoji, pb.balance, pb.updated_at
        FROM card_profile cp
        JOIN programs p ON p.id = cp.program_id
        LEFT JOIN point_balances pb ON pb.program_id = p.id AND pb.user_id = cp.user_id
        WHERE cp.user_id = ? AND p.type = 'loyalty'
        ORDER BY p.name
        """,
        (user_id,),
    ).fetchall()


def upsert_point_balance(conn: sqlite3.Connection, user_id: int, program_id: int, balance: int) -> None:
    conn.execute(
        """
        INSERT INTO point_balances (user_id, program_id, balance, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT (user_id, program_id) DO UPDATE SET
            balance = excluded.balance,
            updated_at = excluded.updated_at
        """,
        (user_id, program_id, balance),
    )


def all_goals(conn: sqlite3.Connection, user_id: int):
    return conn.execute(
        """
        SELECT g.id, g.label, g.target_amount, g.is_active, g.program_id,
               p.name AS program_name, p.unit_label, p.emoji
        FROM goals g
        JOIN programs p ON p.id = g.program_id
        WHERE g.user_id = ?
        ORDER BY g.is_active DESC, g.created_at DESC
        """,
        (user_id,),
    ).fetchall()


def active_goal_with_progress(conn: sqlite3.Connection, user_id: int):
    """The user's active goal joined with their current balance for that
    program, or None if no goal is active."""
    return conn.execute(
        """
        SELECT g.id, g.label, g.target_amount, g.program_id,
               p.name AS program_name, p.unit_label, p.emoji, pb.balance
        FROM goals g
        JOIN programs p ON p.id = g.program_id
        LEFT JOIN point_balances pb ON pb.program_id = g.program_id AND pb.user_id = g.user_id
        WHERE g.user_id = ? AND g.is_active = 1
        """,
        (user_id,),
    ).fetchone()


def create_goal(conn: sqlite3.Connection, user_id: int, program_id: int, label: str, target_amount: int) -> tuple[int, bool]:
    """Creates a goal (inactive by default) and auto-activates it only if the
    user has no other active goal yet. Returns (goal_id, was_auto_activated)."""
    cur = conn.execute(
        "INSERT INTO goals (user_id, program_id, label, target_amount, is_active) VALUES (?, ?, ?, ?, 0)",
        (user_id, program_id, label, target_amount),
    )
    goal_id = cur.lastrowid

    has_active = conn.execute(
        "SELECT 1 FROM goals WHERE user_id = ? AND is_active = 1", (user_id,)
    ).fetchone()
    auto_activated = has_active is None
    if auto_activated:
        set_active_goal(conn, user_id, goal_id)

    conn.commit()
    return goal_id, auto_activated


def set_active_goal(conn: sqlite3.Connection, user_id: int, goal_id: int) -> None:
    conn.execute("UPDATE goals SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE goals SET is_active = 1 WHERE id = ? AND user_id = ?", (goal_id, user_id))


def delete_goal(conn: sqlite3.Connection, user_id: int, goal_id: int) -> None:
    conn.execute("DELETE FROM goals WHERE id = ? AND user_id = ?", (goal_id, user_id))


def user_cards(conn: sqlite3.Connection, user_id: int):
    """type='card' programs (payment cards, never loyalty programs) from the
    user's own /profil selection - used by the /zahlen recommender."""
    return conn.execute(
        """
        SELECT p.id, p.name, p.emoji
        FROM card_profile cp
        JOIN programs p ON p.id = cp.program_id
        WHERE cp.user_id = ? AND p.type = 'card'
        ORDER BY p.name
        """,
        (user_id,),
    ).fetchall()


def recommendation_rules_for(conn: sqlite3.Connection, category: str, subcategory: str | None = None):
    """Active recommendation_rules for a category, preferring subcategory-exact
    rows and falling back to category-wide rows (subcategory IS NULL) when no
    subcategory is given. Ordered by priority (highest first); the caller
    (recommendation_engine.recommend) restricts this further to the specific
    user's own active cards."""
    if subcategory:
        where_subcat = "(r.subcategory = ? OR r.subcategory IS NULL)"
        params = (category, subcategory)
    else:
        where_subcat = "r.subcategory IS NULL"
        params = (category,)

    query = f"""
        SELECT r.program_id, r.note, r.warning, r.priority
        FROM recommendation_rules r
        JOIN programs p ON p.id = r.program_id
        WHERE r.is_active = 1 AND r.category = ? AND {where_subcat} AND p.type = 'card'
        ORDER BY r.priority DESC
    """
    return conn.execute(query, params).fetchall()


PREFERENCE_FIELDS = {
    "home_airport",
    "preferred_airports",
    "preferred_airlines",
    "preferred_alliance",
    "travel_class",
    "priority",
}


def get_user_preferences(conn: sqlite3.Connection, user_id: int):
    """The user's row in user_preferences, or None if they've never set
    anything yet - callers should treat every field as optional/missing."""
    return conn.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)).fetchone()


def upsert_user_preference(conn: sqlite3.Connection, user_id: int, field: str, value: str) -> None:
    """Sets a single preference field. `field` is checked against a fixed
    whitelist before being interpolated into the column name, so this is safe
    despite the dynamic SQL - it can never be arbitrary user input."""
    if field not in PREFERENCE_FIELDS:
        raise ValueError(f"unknown preference field: {field}")
    conn.execute(
        f"""
        INSERT INTO user_preferences (user_id, {field}, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT (user_id) DO UPDATE SET
            {field} = excluded.{field},
            updated_at = excluded.updated_at
        """,
        (user_id, value),
    )


def profile_counts(conn: sqlite3.Connection, user_id: int) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT p.type, COUNT(*) AS n
        FROM card_profile cp
        JOIN programs p ON p.id = cp.program_id
        WHERE cp.user_id = ?
        GROUP BY p.type
        """,
        (user_id,),
    ).fetchall()
    counts = {"card": 0, "loyalty": 0}
    for row in rows:
        counts[row["type"]] = row["n"]
    return counts


# --- Custom / catalog programs (Phase 7.5, 14B) ---------------------------


def visible_programs(conn: sqlite3.Connection, user_id: int, type_filter: str | None = None):
    """Every program a user should be able to pick from: the shared catalog
    (source='catalog') plus this user's OWN custom programs - never another
    user's custom programs (14B.10). This is the one place that needs to
    know about program visibility; queries scoped through card_profile
    already only ever see what that user actually added, regardless of who
    owns the underlying programs row."""
    query = "SELECT id, name, type, emoji, source, usage_context FROM programs WHERE is_active = 1 AND (source = 'catalog' OR owner_user_id = ?)"
    params: list = [user_id]
    if type_filter:
        query += " AND type = ?"
        params.append(type_filter)
    query += " ORDER BY source, name"
    return conn.execute(query, params).fetchall()


def resolve_program_alias(name: str) -> str | None:
    """Deterministic alias -> canonical catalog program name (14B.4). No
    fuzzy matching - an unrecognized spelling is left alone rather than
    guessed."""
    from bot.db import KNOWN_PROGRAM_ALIASES

    key = name.strip().lower()
    if key in KNOWN_PROGRAM_ALIASES:
        return KNOWN_PROGRAM_ALIASES[key]
    return None


def find_catalog_program_by_name(conn: sqlite3.Connection, name: str):
    """Case-insensitive exact match against the shared catalog only (never a
    user's private custom program - a name collision with someone else's
    private entry must not silently attach the searching user to it)."""
    return conn.execute(
        "SELECT id, name, type FROM programs WHERE source = 'catalog' AND lower(name) = lower(?)",
        (name,),
    ).fetchone()


def create_custom_program(
    conn: sqlite3.Connection, owner_user_id: int, name: str, program_type: str, usage_context: str | None = None
) -> int:
    """Creates a new program row owned exclusively by this user (14B.3).
    Never touches or creates a shared catalog entry - see 14B.10."""
    cur = conn.execute(
        """
        INSERT INTO programs (name, type, source, owner_user_id, usage_context, is_active)
        VALUES (?, ?, 'user', ?, ?, 1)
        """,
        (name, program_type, owner_user_id, usage_context),
    )
    return cur.lastrowid


def user_custom_programs(conn: sqlite3.Connection, user_id: int):
    """This user's own custom programs only (14B.9 management view)."""
    return conn.execute(
        "SELECT id, name, type, usage_context, is_active FROM programs WHERE source = 'user' AND owner_user_id = ? ORDER BY name",
        (user_id,),
    ).fetchall()


def deactivate_custom_program(conn: sqlite3.Connection, user_id: int, program_id: int) -> bool:
    """Soft-deletes a custom program (14B.9) - ownership is re-checked here
    server-side so a user can never deactivate anyone else's program, no
    matter what program_id a crafted callback might contain. Also removes it
    from card_profile so it stops showing up as "active" anywhere. Returns
    False (no-op) if the program doesn't exist or isn't owned by this user."""
    owned = conn.execute(
        "SELECT 1 FROM programs WHERE id = ? AND source = 'user' AND owner_user_id = ?", (program_id, user_id)
    ).fetchone()
    if not owned:
        return False
    conn.execute("UPDATE programs SET is_active = 0 WHERE id = ?", (program_id,))
    conn.execute("DELETE FROM card_profile WHERE user_id = ? AND program_id = ?", (user_id, program_id))
    return True
