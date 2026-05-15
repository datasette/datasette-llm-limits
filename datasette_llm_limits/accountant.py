"""LimitsAccountant: enforces windowed spending caps via the internal DB."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from datasette_llm_accountant import (
    Accountant,
    InsufficientBalanceError,
    Nanocents,
    Tx,
)
from ulid import ULID

from .config import Limit, parse_limits
from .windows import window_reset, window_start


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _format_usd(nanocents: int) -> str:
    return f"${Nanocents(nanocents).to_usd():.2f}"


class LimitsAccountant(Accountant):
    def __init__(self, datasette):
        self.datasette = datasette

    # -- internal helpers --

    def _limits(self) -> list[Limit]:
        raw = (self.datasette.plugin_config("datasette-llm-limits") or {}).get(
            "limits"
        ) or {}
        return parse_limits(raw)

    def _matching_limits(self, *, model_id, purpose, actor_id) -> list[Limit]:
        return [
            limit
            for limit in self._limits()
            if limit.matches(model_id=model_id, purpose=purpose, actor_id=actor_id)
        ]

    def _running_total(self, conn, limit: Limit, *, model_id, purpose, actor_id, now):
        """Compute the running total in nanocents within a limit's window."""
        sql = """
            SELECT COALESCE(SUM(
                CASE WHEN settled_at IS NULL
                     THEN reserved_nanocents
                     ELSE settled_nanocents
                END
            ), 0) AS total
            FROM llm_limits_tx
            WHERE created_at >= :window_start
              AND (:scope_actor IS NULL OR actor_id = :scope_actor)
              AND (:limit_purpose IS NULL OR purpose = :limit_purpose)
              AND (:limit_model_id IS NULL OR model_id = :limit_model_id)
        """
        params = {
            "window_start": _iso(window_start(limit.window, now)),
            "scope_actor": actor_id if limit.scope == "actor" else None,
            "limit_purpose": limit.purpose,
            "limit_model_id": limit.model_id,
        }
        cur = conn.execute(sql, params)
        return cur.fetchone()[0] or 0

    # -- public API --

    async def reserve(
        self,
        nanocents: Nanocents,
        model_id: Optional[str] = None,
        purpose: Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> Tx:
        matching = self._matching_limits(
            model_id=model_id, purpose=purpose, actor_id=actor_id
        )
        now = _now()
        new_id = str(ULID())

        def _check_and_insert(conn):
            # IMMEDIATE so the check and insert are atomic vs. other writers.
            conn.execute("BEGIN IMMEDIATE")
            try:
                for limit in matching:
                    used = self._running_total(
                        conn,
                        limit,
                        model_id=model_id,
                        purpose=purpose,
                        actor_id=actor_id,
                        now=now,
                    )
                    if used + int(nanocents) > limit.amount_nanocents:
                        reset = window_reset(limit.window, now)
                        msg = (
                            f'Limit "{limit.name}" exceeded: '
                            f"{_format_usd(used)} used of "
                            f"{_format_usd(limit.amount_nanocents)} "
                            f"in {limit.window}."
                        )
                        if reset is not None:
                            msg += f" Try again after {_iso(reset)}."
                        raise InsufficientBalanceError(msg)
                conn.execute(
                    """
                    INSERT INTO llm_limits_tx
                        (id, created_at, actor_id, purpose, model_id,
                         reserved_nanocents, matched_limits)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        new_id,
                        _iso(now),
                        actor_id,
                        purpose,
                        model_id,
                        int(nanocents),
                        json.dumps([limit.name for limit in matching]),
                    ],
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        await self.datasette.get_internal_database().execute_write_fn(_check_and_insert)
        return Tx(new_id)

    async def settle(
        self,
        tx: Tx,
        nanocents: Nanocents,
        model_id: Optional[str] = None,
        purpose: Optional[str] = None,
        actor_id: Optional[str] = None,
    ):
        settled_at = _iso(_now())

        def _update(conn):
            conn.execute(
                """
                UPDATE llm_limits_tx
                   SET settled_nanocents = ?, settled_at = ?
                 WHERE id = ?
                """,
                [int(nanocents), settled_at, str(tx)],
            )

        await self.datasette.get_internal_database().execute_write_fn(_update)
