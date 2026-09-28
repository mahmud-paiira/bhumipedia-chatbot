"""Load iLKMS tables from a live PostgreSQL database.

Produces the exact same {table: {cols, rows}} structure that
build_db.load_tables_from_sql() produces from the pg_dump file, so the whole
Q&A pipeline (build_db.extract_db) works unchanged against a live source.

The dump export scope is "approved content"; this loader applies the same
filters (approved=true for acts and blogs) so results match the curated
.sql snapshot while reflecting live updates.
"""
import datetime
import os

import dotenv
import psycopg2
import psycopg2.extras

dotenv.load_dotenv()

TABLES = [
    "acts_acts",
    "acts_sections",
    "acts_subsections",
    "acts_schedules",
    "acts_subschedules",
    "blogs_blog",
    # public_api.build_full_forums reads these two; without them the live
    # PostgreSQL path serves an empty /api/forums/full/ even though the SQL
    # snapshot (same schema) has them. build_full_forums applies its own
    # "approved + open" filter, so they are exported unfiltered like the child
    # act tables.
    "forum_group",
    "forum_topic",
]

# Mirror the pg_dump export scope ("approved-content export"): acts with
# approved=true (including soft-deleted/draft rows, which extract_db filters
# itself via is_soft_deleted/is_draft/live), their child rows, and approved
# blogs. This keeps the live path byte-identical to the .sql build.
APPROVED_ACTS_WHERE = "WHERE approved = TRUE"


def _dbname(dsn):
    return dsn or os.environ.get("DATABASE_URL") or "postgresql://localhost/iLKMS"


def _cell(v):
    """Convert a real-DB value to the text form pg_dump COPY uses."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "t" if v else "f"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return str(v)


class _Conn:
    def __init__(self, dsn=None):
        self.dsn = dsn
        self.conn = None

    def connect(self):
        try:
            self.conn = psycopg2.connect(_dbname(self.dsn))
            self.conn.set_session(readonly=True)
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[db_source] connect failed: {exc}")
            return False

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
            self.conn = None

    def health(self):
        if self.conn is None:
            return False
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone()[0] == 1
        except Exception:  # noqa: BLE001
            return False

    def load(self, schema="public"):
        """Return the tables dict identical in shape to build_db's parser."""
        tables = {}
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for name in TABLES:
                cols = []
                if name == "acts_acts":
                    q = f"SELECT * FROM {schema}.acts_acts {APPROVED_ACTS_WHERE} ORDER BY id"
                elif name == "blogs_blog":
                    q = ("SELECT * FROM {0}.blogs_blog WHERE approved = TRUE "
                         "ORDER BY id").format(schema)
                else:
                    # Child tables are exported unfiltered (the dump contains
                    # sections/subschedules for unapproved acts too); extract_db
                    # resolves parent acts itself via act_by_id.
                    q = f"SELECT * FROM {schema}.{name} ORDER BY id"
                cur.execute(q)
                rows = cur.fetchall()
                cur.execute(q + " LIMIT 0")
                cols = [d.name for d in cur.description]
                tables[f"{schema}.{name}"] = {
                    "cols": cols,
                    "rows": [[_cell(r.get(c)) for c in cols] for r in rows],
                }
        return tables


def load_tables_from_db(dsn=None, schema="public"):
    """Convenience: connect, load, close. Returns tables dict or None."""
    c = _Conn(dsn)
    if not c.connect():
        return None
    try:
        return c.load(schema)
    finally:
        c.close()


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    tb = load_tables_from_db()
    if tb is None:
        sys.exit("Could not connect. Set DATABASE_URL in .env")
    for k, v in tb.items():
        print(f"{k}: {len(v['rows'])} rows, {len(v['cols'])} cols")