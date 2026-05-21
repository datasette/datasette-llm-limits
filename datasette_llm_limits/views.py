"""Operator inspection view at /-/llm-limits."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from datasette.utils.asgi import Forbidden, Response
from datasette_llm_accountant import Nanocents

from .config import Limit, parse_limits
from .windows import window_reset, window_start

_RECENT_LIMIT = 50


def _wants_json(request) -> bool:
    if request.args.get("_format") == "json":
        return True
    accept = request.headers.get("accept") or ""
    return "application/json" in accept and "text/html" not in accept


async def _running_total_for_limit(internal_db, limit: Limit, now: datetime) -> int:
    sql = """
        SELECT COALESCE(SUM(
            CASE WHEN settled_at IS NULL
                 THEN reserved_nanocents
                 ELSE settled_nanocents
            END
        ), 0) AS total
        FROM llm_limits_tx
        WHERE created_at >= :window_start
          AND (:limit_purpose IS NULL OR purpose = :limit_purpose)
          AND (:limit_model_id IS NULL OR model_id = :limit_model_id)
    """
    params = {
        "window_start": window_start(limit.window, now)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "limit_purpose": limit.purpose,
        "limit_model_id": limit.model_id,
    }
    rows = list(await internal_db.execute(sql, params))
    return rows[0]["total"] or 0


async def _actor_usage_for_limit(
    internal_db, limit: Limit, now: datetime
) -> list[dict]:
    sql = """
        SELECT actor_id, COALESCE(SUM(
            CASE WHEN settled_at IS NULL
                 THEN reserved_nanocents
                 ELSE settled_nanocents
            END
        ), 0) AS total
        FROM llm_limits_tx
        WHERE created_at >= :window_start
          AND actor_id IS NOT NULL
          AND (:limit_purpose IS NULL OR purpose = :limit_purpose)
          AND (:limit_model_id IS NULL OR model_id = :limit_model_id)
        GROUP BY actor_id
        ORDER BY total DESC, actor_id
    """
    params = {
        "window_start": window_start(limit.window, now)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "limit_purpose": limit.purpose,
        "limit_model_id": limit.model_id,
    }
    return [
        {
            "actor_id": row["actor_id"],
            "used_nanocents": row["total"] or 0,
        }
        for row in await internal_db.execute(sql, params)
    ]


async def _build_payload(datasette, limits: list[Limit]) -> dict:
    now = datetime.now(timezone.utc)
    internal = datasette.get_internal_database()

    limit_rows = []
    actor_usage_rows = []
    for limit in limits:
        if limit.scope == "instance":
            used = await _running_total_for_limit(internal, limit, now)
            remaining = max(limit.amount_nanocents - used, 0)
            used_usd = Nanocents(used).to_usd()
            remaining_usd = Nanocents(remaining).to_usd()
        else:
            used_usd = None
            remaining_usd = None
        reset = window_reset(limit.window, now)
        limit_rows.append(
            {
                "name": limit.name,
                "scope": limit.scope,
                "window": limit.window,
                "purpose": limit.purpose,
                "model_id": limit.model_id,
                "amount_usd": Nanocents(limit.amount_nanocents).to_usd(),
                "used_usd": used_usd,
                "remaining_usd": remaining_usd,
                "resets_at": reset.isoformat() if reset else None,
            }
        )
        if limit.scope == "actor":
            for usage in await _actor_usage_for_limit(internal, limit, now):
                used = usage["used_nanocents"]
                remaining = max(limit.amount_nanocents - used, 0)
                actor_usage_rows.append(
                    {
                        "name": limit.name,
                        "actor_id": usage["actor_id"],
                        "window": limit.window,
                        "purpose": limit.purpose,
                        "model_id": limit.model_id,
                        "amount_usd": Nanocents(limit.amount_nanocents).to_usd(),
                        "used_usd": Nanocents(used).to_usd(),
                        "remaining_usd": Nanocents(remaining).to_usd(),
                        "resets_at": reset.isoformat() if reset else None,
                    }
                )

    tx_rows = []
    for row in await internal.execute(
        """
        SELECT id, created_at, settled_at, actor_id, purpose, model_id,
               reserved_nanocents, settled_nanocents, matched_limits
          FROM llm_limits_tx
         ORDER BY created_at DESC, id DESC
         LIMIT ?
        """,
        [_RECENT_LIMIT],
    ):
        settled_nc = row["settled_nanocents"]
        tx_rows.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "settled_at": row["settled_at"],
                "actor_id": row["actor_id"],
                "purpose": row["purpose"],
                "model_id": row["model_id"],
                "reserved_usd": Nanocents(row["reserved_nanocents"]).to_usd(),
                "settled_usd": (
                    Nanocents(settled_nc).to_usd() if settled_nc is not None else None
                ),
                "matched_limits": json.loads(row["matched_limits"]),
            }
        )

    return {
        "limits": limit_rows,
        "actor_usage": actor_usage_rows,
        "recent_transactions": tx_rows,
    }


async def llm_limits_view(request, datasette):
    actor = request.actor
    if not await datasette.allowed(action="datasette-llm-limits-view", actor=actor):
        raise Forbidden("datasette-llm-limits-view")

    raw = (datasette.plugin_config("datasette-llm-limits") or {}).get("limits") or {}
    limits = parse_limits(raw)
    payload = await _build_payload(datasette, limits)

    if _wants_json(request):
        return Response.json(payload)
    return Response.html(
        await datasette.render_template(
            "llm_limits.html",
            payload,
            request=request,
            view_name="llm_limits",
        )
    )
