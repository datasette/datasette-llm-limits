"""Storage / schema tests for the internal-database llm_limits_tx table."""

import pytest
from datasette.app import Datasette


@pytest.mark.asyncio
async def test_startup_creates_llm_limits_tx_table():
    datasette = Datasette(memory=True)
    await datasette.invoke_startup()
    internal = datasette.get_internal_database()
    tables = {
        r["name"]
        for r in await internal.execute(
            "select name from sqlite_master where type='table'"
        )
    }
    assert "llm_limits_tx" in tables


@pytest.mark.asyncio
async def test_llm_limits_tx_has_expected_columns():
    datasette = Datasette(memory=True)
    await datasette.invoke_startup()
    internal = datasette.get_internal_database()
    cols = {
        r["name"]: r for r in await internal.execute("pragma table_info(llm_limits_tx)")
    }
    assert set(cols) >= {
        "id",
        "created_at",
        "settled_at",
        "actor_id",
        "purpose",
        "model_id",
        "reserved_nanocents",
        "settled_nanocents",
        "matched_limits",
    }
    # id is the primary key
    assert cols["id"]["pk"] == 1


@pytest.mark.asyncio
async def test_startup_is_idempotent():
    # Running startup twice should not fail.
    datasette = Datasette(memory=True)
    await datasette.invoke_startup()
    await datasette.invoke_startup()


@pytest.mark.asyncio
async def test_invalid_config_fails_at_startup():
    datasette = Datasette(
        memory=True,
        config={
            "plugins": {
                "datasette-llm-limits": {
                    "limits": {
                        "bad": {
                            "scope": "team",  # invalid
                            "window": "rolling-24h",
                            "amount_usd": 1.0,
                        }
                    }
                }
            }
        },
    )
    with pytest.raises(ValueError):
        await datasette.invoke_startup()
