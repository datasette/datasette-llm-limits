"""Operator inspection view at /-/llm-limits."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from datasette.utils.asgi import Forbidden, Response
from datasette_llm_accountant import Nanocents

from .accountant import LimitsAccountant
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
        "window_start": window_start(limit.window, now).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "limit_purpose": limit.purpose,
        "limit_model_id": limit.model_id,
    }
    rows = list(await internal_db.execute(sql, params))
    return rows[0]["total"] or 0


async def _build_payload(datasette, limits: list[Limit]) -> dict:
    now = datetime.now(timezone.utc)
    internal = datasette.get_internal_database()

    limit_rows = []
    for limit in limits:
        used = await _running_total_for_limit(internal, limit, now)
        remaining = max(limit.amount_nanocents - used, 0)
        reset = window_reset(limit.window, now)
        limit_rows.append(
            {
                "name": limit.name,
                "scope": limit.scope,
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

    return {"limits": limit_rows, "recent_transactions": tx_rows}


def _render_html(payload: dict) -> str:
    def esc(value):
        return html.escape("" if value is None else str(value))

    limit_rows = "".join(
        "<tr>"
        f"<td>{esc(l['name'])}</td>"
        f"<td>{esc(l['scope'])}</td>"
        f"<td>{esc(l['window'])}</td>"
        f"<td>{esc(l['purpose'])}</td>"
        f"<td>{esc(l['model_id'])}</td>"
        f"<td>${l['amount_usd']:.4f}</td>"
        f"<td>${l['used_usd']:.4f}</td>"
        f"<td>${l['remaining_usd']:.4f}</td>"
        f"<td>{esc(l['resets_at'])}</td>"
        "</tr>"
        for l in payload["limits"]
    )

    def _settled_cell(value):
        if value is None:
            return ""
        return f"${value:.4f}"

    tx_rows = "".join(
        "<tr>"
        f"<td>{esc(t['id'])}</td>"
        f"<td>{esc(t['created_at'])}</td>"
        f"<td>{esc(t['actor_id'])}</td>"
        f"<td>{esc(t['purpose'])}</td>"
        f"<td>{esc(t['model_id'])}</td>"
        f"<td>${t['reserved_usd']:.4f}</td>"
        f"<td>{_settled_cell(t['settled_usd'])}</td>"
        f"<td>{esc(', '.join(t['matched_limits']))}</td>"
        "</tr>"
        for t in payload["recent_transactions"]
    )

    return f"""<!doctype html>
<html><head><title>LLM Limits</title>
<style>
body {{ font-family: sans-serif; margin: 2em; }}
table {{ border-collapse: collapse; margin-bottom: 2em; }}
th, td {{ border: 1px solid #ccc; padding: 4px 8px; text-align: left; }}
</style>
</head><body>
<h1>LLM Limits</h1>
<h2>Configured limits</h2>
<table><thead><tr>
<th>Name</th><th>Scope</th><th>Window</th><th>Purpose</th><th>Model</th>
<th>Cap</th><th>Used</th><th>Remaining</th><th>Resets at</th>
</tr></thead><tbody>{limit_rows or '<tr><td colspan="9"><em>No limits configured</em></td></tr>'}</tbody></table>
<h2>Recent transactions</h2>
<table><thead><tr>
<th>ID</th><th>Created</th><th>Actor</th><th>Purpose</th><th>Model</th>
<th>Reserved</th><th>Settled</th><th>Matched limits</th>
</tr></thead><tbody>{tx_rows or '<tr><td colspan="8"><em>No transactions yet</em></td></tr>'}</tbody></table>
</body></html>
"""


async def llm_limits_view(request, datasette):
    actor = request.actor
    if not await datasette.allowed(
        action="datasette-llm-limits-view", actor=actor
    ):
        raise Forbidden("datasette-llm-limits-view")

    raw = (datasette.plugin_config("datasette-llm-limits") or {}).get("limits") or {}
    limits = parse_limits(raw)
    payload = await _build_payload(datasette, limits)

    if _wants_json(request):
        return Response.json(payload)
    return Response.html(_render_html(payload))
