from datasette import hookimpl

from .config import parse_limits
from .storage import ensure_schema


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
