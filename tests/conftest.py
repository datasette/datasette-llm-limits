import pytest_asyncio
from datasette.app import Datasette
from datasette_llm_accountant import Nanocents

from datasette_llm_limits.accountant import LimitsAccountant


@pytest_asyncio.fixture
async def make_datasette():
    """Factory: build (datasette, accountant) with given plugin config."""

    instances = []

    async def _build(limits=None, permissions=None):
        plugin_cfg = {}
        if limits is not None:
            plugin_cfg["limits"] = limits
        cfg = {"plugins": {"datasette-llm-limits": plugin_cfg}}
        if permissions is not None:
            cfg["permissions"] = permissions
        datasette = Datasette(memory=True, config=cfg)
        await datasette.invoke_startup()
        instances.append(datasette)
        return datasette, LimitsAccountant(datasette)

    yield _build


def usd(amount):
    """Convenience for tests: dollars to Nanocents."""
    return Nanocents.from_usd(amount)
