"""Verify the plugin is registered as an Accountant via the hook."""

import pytest
from datasette.app import Datasette
from datasette.plugins import pm
from datasette_llm_accountant import Accountant

from datasette_llm_limits.accountant import LimitsAccountant


@pytest.mark.asyncio
async def test_plugin_registers_a_limits_accountant():
    datasette = Datasette(memory=True)
    await datasette.invoke_startup()

    accountants = []
    for result in pm.hook.register_llm_accountants(datasette=datasette):
        if not result:
            continue
        if isinstance(result, list):
            accountants.extend(result)
        else:
            accountants.append(result)

    assert any(isinstance(a, LimitsAccountant) for a in accountants), (
        f"Expected a LimitsAccountant among {accountants!r}"
    )
    # All registered accountants must subclass Accountant
    for a in accountants:
        assert isinstance(a, Accountant)
