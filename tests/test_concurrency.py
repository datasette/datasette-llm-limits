"""Concurrent reservations must not collectively exceed any cap."""

import asyncio

import pytest
from datasette_llm_accountant import InsufficientBalanceError

from conftest import usd


@pytest.mark.asyncio
async def test_parallel_reservations_respect_cap(make_datasette):
    """N parallel reservations of $0.10 each against a $0.50 cap → 5 succeed, rest fail."""
    _, accountant = await make_datasette(
        limits={"cap": {"scope": "actor", "window": "rolling-24h", "amount_usd": 0.50}}
    )

    N = 8

    async def one():
        try:
            await accountant.reserve(usd(0.10), actor_id="alice")
            return "ok"
        except InsufficientBalanceError:
            return "fail"

    results = await asyncio.gather(*[one() for _ in range(N)])
    successes = results.count("ok")
    failures = results.count("fail")
    # Cap allows exactly 5 reservations of $0.10.
    assert successes == 5
    assert failures == N - 5


@pytest.mark.asyncio
async def test_parallel_reservations_at_exact_cap_only_one_fails(make_datasette):
    """6 parallel reservations of $0.10 against $0.50 cap → exactly 5 succeed."""
    _, accountant = await make_datasette(
        limits={"cap": {"scope": "actor", "window": "rolling-24h", "amount_usd": 0.50}}
    )

    async def one():
        try:
            await accountant.reserve(usd(0.10), actor_id="alice")
            return True
        except InsufficientBalanceError:
            return False

    outcomes = await asyncio.gather(*[one() for _ in range(6)])
    assert sum(outcomes) == 5
