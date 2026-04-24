"""
Migrate all data from SQLite (whatsapp.db) to PostgreSQL.
Run on the server: python3 scripts/migrate_to_postgres.py
"""
import sqlite3
import psycopg2
import json
import sys
import os

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "whatsapp.db")
PG_DSN = os.environ.get(
    "PG_DSN",
    "host=localhost dbname=vivizwb_db user=vivizwb password=vivizwb_secure_2026"
)

TABLES = [
    "admins",
    "contacts",
    "conversations",
    "messages",
    "message_templates",
    "broadcasts",
    "broadcast_recipients",
    "webhook_logs",
    "quick_replies",
]


BOOL_COLUMNS = {
    "admins": {"is_active", "must_change_password"},
    "contacts": {"is_opted_in", "is_blocked"},
    "messages": {"is_ai_reply"},
    "message_templates": {"is_active"},
}


def adapt_value(v, col_name=None, table=None):
    """Convert Python types to PG-compatible values."""
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    # Cast SQLite integer booleans to Python bool for PG boolean columns
    if isinstance(v, int) and table and col_name:
        if col_name in BOOL_COLUMNS.get(table, set()):
            return bool(v)
    return v


def migrate_table(sq_cur, pg_cur, table):
    sq_cur.execute(f"SELECT * FROM {table}")
    rows = sq_cur.fetchall()
    if not rows:
        print(f"  {table}: empty, skipping")
        return

    cols = [d[0] for d in sq_cur.description]
    placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join(cols)
    sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    adapted = [tuple(adapt_value(v, cols[i], table) for i, v in enumerate(row)) for row in rows]
    pg_cur.executemany(sql, adapted)
    print(f"  {table}: {len(rows)} rows migrated")


def main():
    print("Connecting to SQLite...")
    sq = sqlite3.connect(SQLITE_PATH)
    sq.row_factory = sqlite3.Row
    sq_cur = sq.cursor()

    print("Connecting to PostgreSQL...")
    pg = psycopg2.connect(PG_DSN)
    pg.autocommit = False
    pg_cur = pg.cursor()

    try:
        for table in TABLES:
            # Check table exists in SQLite
            sq_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not sq_cur.fetchone():
                print(f"  {table}: not in SQLite, skipping")
                continue
            migrate_table(sq_cur, pg_cur, table)

        # Reset all sequences so new inserts don't collide
        for table in TABLES:
            pg_cur.execute(f"""
                SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {table}), 0) + 1,
                    false
                )
            """)

        pg.commit()
        print("\nMigration complete.")
    except Exception as e:
        pg.rollback()
        print(f"\nERROR: {e}")
        sys.exit(1)
    finally:
        sq.close()
        pg.close()


if __name__ == "__main__":
    main()
