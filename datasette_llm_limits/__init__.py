from datasette import hookimpl
from datasette.permissions import Action

from .accountant import LimitsAccountant
from .config import parse_limits
from .storage import ensure_schema
from .views import llm_limits_view

VIEW_PERMISSION = "datasette-llm-limits-view"
VIEW_PATH = "/-/llm-limits"


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
            name=VIEW_PERMISSION,
            abbr="dlv",
            description="View the LLM limits inspection page",
        ),
    ]


@hookimpl
async def menu_links(datasette, actor, request):
    if await datasette.allowed(action=VIEW_PERMISSION, actor=actor):
        return [
            {
                "href": datasette.urls.path(VIEW_PATH),
                "label": "LLM Limits",
            }
        ]
    return []


@hookimpl
def register_routes():
    return [(r"^{}$".format(VIEW_PATH), llm_limits_view)]
