import json

import pytest
from datasette_llm_accountant import InsufficientBalanceError, Tx

from conftest import usd


@pytest.mark.asyncio
async def test_reserve_returns_tx_and_inserts_row(make_datasette):
    datasette, accountant = await make_datasette(
        limits={
            "daily": {"scope": "actor", "window": "rolling-24h", "amount_usd": 1.00}
        }
    )

    tx = await accountant.reserve(usd(0.10), actor_id="alice", model_id="gpt-4o")
    assert isinstance(tx, Tx)

    internal = datasette.get_internal_database()
    rows = list(await internal.execute("select * from llm_limits_tx where id = ?", [tx]))
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_id"] == "alice"
    assert row["model_id"] == "gpt-4o"
    assert row["reserved_nanocents"] == int(usd(0.10))
    assert row["settled_at"] is None
    assert row["settled_nanocents"] is None
    assert json.loads(row["matched_limits"]) == ["daily"]


@pytest.mark.asyncio
async def test_reserve_over_cap_raises_insufficient_balance(make_datasette):
    _, accountant = await make_datasette(
        limits={"tight": {"scope": "actor", "window": "rolling-24h", "amount_usd": 0.50}}
    )
    await accountant.reserve(usd(0.40), actor_id="alice")
    with pytest.raises(InsufficientBalanceError) as exc_info:
        await accountant.reserve(usd(0.20), actor_id="alice")
    msg = str(exc_info.value)
    assert "tight" in msg
    # Window appears in the message
    assert "rolling-24h" in msg
    # Used and cap amounts appear, formatted in USD
    assert "0.40" in msg
    assert "0.50" in msg


@pytest.mark.asyncio
async def test_reserve_under_cap_succeeds_repeatedly(make_datasette):
    _, accountant = await make_datasette(
        limits={"daily": {"scope": "actor", "window": "rolling-24h", "amount_usd": 1.00}}
    )
    for _ in range(5):
        await accountant.reserve(usd(0.10), actor_id="alice")


@pytest.mark.asyncio
async def test_settle_updates_settled_columns(make_datasette):
    datasette, accountant = await make_datasette(
        limits={"daily": {"scope": "actor", "window": "rolling-24h", "amount_usd": 1.00}}
    )
    tx = await accountant.reserve(usd(0.50), actor_id="alice")
    await accountant.settle(tx, usd(0.30), actor_id="alice")

    internal = datasette.get_internal_database()
    row = list(
        await internal.execute("select * from llm_limits_tx where id = ?", [tx])
    )[0]
    assert row["settled_nanocents"] == int(usd(0.30))
    assert row["settled_at"] is not None


@pytest.mark.asyncio
async def test_settling_under_reservation_frees_headroom(make_datasette):
    """Reserve $0.80 of $1 cap; settle for $0.10 → another $0.80 fits."""
    _, accountant = await make_datasette(
        limits={"daily": {"scope": "actor", "window": "rolling-24h", "amount_usd": 1.00}}
    )
    tx = await accountant.reserve(usd(0.80), actor_id="alice")
    await accountant.settle(tx, usd(0.10), actor_id="alice")
    # Now used = $0.10, headroom = $0.90
    await accountant.reserve(usd(0.80), actor_id="alice")


@pytest.mark.asyncio
async def test_rollback_zeros_out_the_reservation(make_datasette):
    _, accountant = await make_datasette(
        limits={"daily": {"scope": "actor", "window": "rolling-24h", "amount_usd": 1.00}}
    )
    tx = await accountant.reserve(usd(0.90), actor_id="alice")
    await accountant.rollback(tx)
    # Fully rolled back: full $1 should now be available
    await accountant.reserve(usd(1.00), actor_id="alice")


@pytest.mark.asyncio
async def test_per_actor_isolation(make_datasette):
    _, accountant = await make_datasette(
        limits={"daily": {"scope": "actor", "window": "rolling-24h", "amount_usd": 1.00}}
    )
    await accountant.reserve(usd(0.90), actor_id="alice")
    # Bob's quota is independent
    await accountant.reserve(usd(0.90), actor_id="bob")
    # But Alice is near her cap
    with pytest.raises(InsufficientBalanceError):
        await accountant.reserve(usd(0.20), actor_id="alice")


@pytest.mark.asyncio
async def test_anonymous_caller_bypasses_actor_scope_only(make_datasette):
    _, accountant = await make_datasette(
        limits={
            "actor-daily": {"scope": "actor", "window": "rolling-24h", "amount_usd": 0.50},
            "instance-daily": {
                "scope": "instance",
                "window": "rolling-24h",
                "amount_usd": 0.30,
            },
        }
    )
    # Anonymous doesn't trip the actor-scoped cap, but it DOES trip the instance cap
    await accountant.reserve(usd(0.20), actor_id=None)
    with pytest.raises(InsufficientBalanceError) as exc_info:
        await accountant.reserve(usd(0.20), actor_id=None)
    assert "instance-daily" in str(exc_info.value)


@pytest.mark.asyncio
async def test_instance_limit_aggregates_across_actors(make_datasette):
    _, accountant = await make_datasette(
        limits={
            "instance-daily": {
                "scope": "instance",
                "window": "rolling-24h",
                "amount_usd": 1.00,
            }
        }
    )
    await accountant.reserve(usd(0.60), actor_id="alice")
    with pytest.raises(InsufficientBalanceError):
        await accountant.reserve(usd(0.60), actor_id="bob")


@pytest.mark.asyncio
async def test_purpose_filtered_limit_only_applies_for_that_purpose(make_datasette):
    _, accountant = await make_datasette(
        limits={
            "enrichments-cap": {
                "scope": "actor",
                "window": "rolling-24h",
                "amount_usd": 0.20,
                "purpose": "enrichments",
            }
        }
    )
    # purpose=chat is unaffected by the enrichments cap
    await accountant.reserve(usd(1.00), actor_id="alice", purpose="chat")
    # purpose=enrichments is limited
    await accountant.reserve(usd(0.10), actor_id="alice", purpose="enrichments")
    with pytest.raises(InsufficientBalanceError):
        await accountant.reserve(usd(0.20), actor_id="alice", purpose="enrichments")


@pytest.mark.asyncio
async def test_model_filtered_limit_only_applies_for_that_model(make_datasette):
    _, accountant = await make_datasette(
        limits={
            "gpt5-cap": {
                "scope": "actor",
                "window": "rolling-24h",
                "amount_usd": 0.20,
                "model_id": "gpt-5-pro",
            }
        }
    )
    await accountant.reserve(usd(1.00), actor_id="alice", model_id="gpt-4o")
    await accountant.reserve(usd(0.10), actor_id="alice", model_id="gpt-5-pro")
    with pytest.raises(InsufficientBalanceError):
        await accountant.reserve(usd(0.20), actor_id="alice", model_id="gpt-5-pro")


@pytest.mark.asyncio
async def test_no_matching_limits_inserts_row_but_does_not_reject(make_datasette):
    """An actor with no actor-scoped limit and no instance limit should not be blocked."""
    datasette, accountant = await make_datasette(limits={})
    tx = await accountant.reserve(usd(100.0), actor_id="alice")
    internal = datasette.get_internal_database()
    row = list(
        await internal.execute("select * from llm_limits_tx where id = ?", [tx])
    )[0]
    assert json.loads(row["matched_limits"]) == []


@pytest.mark.asyncio
async def test_calendar_window_error_includes_reset_time(make_datasette):
    _, accountant = await make_datasette(
        limits={
            "month": {"scope": "actor", "window": "calendar-month", "amount_usd": 0.10}
        }
    )
    await accountant.reserve(usd(0.10), actor_id="alice")
    with pytest.raises(InsufficientBalanceError) as exc_info:
        await accountant.reserve(usd(0.01), actor_id="alice")
    assert "Try again after" in str(exc_info.value)


@pytest.mark.asyncio
async def test_rolling_window_error_omits_reset_time(make_datasette):
    _, accountant = await make_datasette(
        limits={"daily": {"scope": "actor", "window": "rolling-24h", "amount_usd": 0.10}}
    )
    await accountant.reserve(usd(0.10), actor_id="alice")
    with pytest.raises(InsufficientBalanceError) as exc_info:
        await accountant.reserve(usd(0.01), actor_id="alice")
    assert "Try again after" not in str(exc_info.value)
