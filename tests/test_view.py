"""Tests for the /-/llm-limits inspection view and its permission."""

import pytest
from datasette.app import Datasette

from datasette_llm_limits.accountant import LimitsAccountant
from conftest import usd


def _config(limits=None, allow_view_to=None):
    cfg = {"plugins": {"datasette-llm-limits": {"limits": limits or {}}}}
    if allow_view_to is not None:
        cfg["permissions"] = {"datasette-llm-limits-view": {"id": allow_view_to}}
    return cfg


@pytest.mark.asyncio
async def test_anonymous_user_denied():
    datasette = Datasette(memory=True, config=_config(allow_view_to="*"))
    await datasette.invoke_startup()
    resp = await datasette.client.get("/-/llm-limits")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_user_without_permission_denied():
    datasette = Datasette(memory=True, config=_config(allow_view_to="admin"))
    await datasette.invoke_startup()
    cookies = {"ds_actor": datasette.client.actor_cookie({"id": "alice"})}
    resp = await datasette.client.get("/-/llm-limits", cookies=cookies)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_authorized_user_gets_html():
    datasette = Datasette(memory=True, config=_config(allow_view_to="*"))
    await datasette.invoke_startup()
    cookies = {"ds_actor": datasette.client.actor_cookie({"id": "alice"})}
    resp = await datasette.client.get("/-/llm-limits", cookies=cookies)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_authorized_user_gets_json():
    limits = {
        "daily": {"scope": "actor", "window": "rolling-24h", "amount_usd": 1.00},
        "monthly": {
            "scope": "instance",
            "window": "calendar-month",
            "amount_usd": 50.0,
        },
    }
    datasette = Datasette(memory=True, config=_config(limits=limits, allow_view_to="*"))
    await datasette.invoke_startup()

    # Record one reservation so the running totals are not all zero.
    accountant = LimitsAccountant(datasette)
    await accountant.reserve(usd(0.20), actor_id="alice", model_id="gpt-4o")

    cookies = {"ds_actor": datasette.client.actor_cookie({"id": "alice"})}
    resp = await datasette.client.get("/-/llm-limits?_format=json", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "limits" in body
    assert "recent_transactions" in body

    names = {row["name"] for row in body["limits"]}
    assert names == {"daily", "monthly"}

    # The instance limit aggregates the $0.20 reservation
    monthly = next(row for row in body["limits"] if row["name"] == "monthly")
    assert monthly["used_usd"] == pytest.approx(0.20)
    assert monthly["amount_usd"] == pytest.approx(50.0)
    assert monthly["remaining_usd"] == pytest.approx(49.80)

    # Recent transactions list includes the reservation
    assert len(body["recent_transactions"]) == 1
    tx = body["recent_transactions"][0]
    assert tx["actor_id"] == "alice"
    assert tx["model_id"] == "gpt-4o"
    assert tx["reserved_usd"] == pytest.approx(0.20)


@pytest.mark.asyncio
async def test_html_view_lists_configured_limits():
    limits = {
        "monthly": {
            "scope": "instance",
            "window": "calendar-month",
            "amount_usd": 50.0,
        },
    }
    datasette = Datasette(memory=True, config=_config(limits=limits, allow_view_to="*"))
    await datasette.invoke_startup()
    cookies = {"ds_actor": datasette.client.actor_cookie({"id": "alice"})}
    resp = await datasette.client.get("/-/llm-limits", cookies=cookies)
    assert resp.status_code == 200
    assert "monthly" in resp.text
    assert "calendar-month" in resp.text
