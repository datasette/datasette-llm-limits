"""SQLite storage for reservation/settlement transactions."""

from __future__ import annotations

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS llm_limits_tx (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    settled_at TEXT,
    actor_id TEXT,
    purpose TEXT,
    model_id TEXT,
    reserved_nanocents INTEGER NOT NULL,
    settled_nanocents INTEGER,
    matched_limits TEXT NOT NULL
)
""".strip()

CREATE_INDEX_ACTOR_CREATED = (
    "CREATE INDEX IF NOT EXISTS llm_limits_tx_actor_created "
    "ON llm_limits_tx(actor_id, created_at)"
)

CREATE_INDEX_SETTLED_AT = (
    "CREATE INDEX IF NOT EXISTS llm_limits_tx_settled_at "
    "ON llm_limits_tx(settled_at)"
)


async def ensure_schema(internal_db) -> None:
    def _create(conn):
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_INDEX_ACTOR_CREATED)
        conn.execute(CREATE_INDEX_SETTLED_AT)

    await internal_db.execute_write_fn(_create)
