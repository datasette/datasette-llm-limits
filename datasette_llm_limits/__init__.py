from datasette import hookimpl
from datasette.permissions import Action

from .accountant import LimitsAccountant
from .config import parse_limits
from .storage import ensure_schema
from .views import llm_limits_view


def _config_limits(datasette):
    raw = (datasette.plugin_config("datasette-llm-limits") or {}).get("limits") or {}
    return parse_limits(raw)


@hookimpl
def startup(datasette):
    async def inner():
        # Validate config eagerly so misconfigurations fail fast.
        _config_limits(datasette)
        await ensure_schema(datasette.get_internal_database())

    return inner


@hookimpl
def register_llm_accountants(datasette):
    return LimitsAccountant(datasette)


@hookimpl
def register_actions():
    return [
        Action(
            name="datasette-llm-limits-view",
            abbr="dlv",
            description="View the LLM limits inspection page",
        ),
    ]


@hookimpl
def register_routes():
    return [(r"^/-/llm-limits$", llm_limits_view)]
