"""Configuration parsing, validation, and limit-matching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from datasette_llm_accountant import Nanocents

from .windows import ALL_WINDOWS

VALID_SCOPES = {"actor", "instance"}
REQUIRED_FIELDS = {"scope", "window", "amount_usd"}
OPTIONAL_FIELDS = {"purpose", "model_id"}
ALL_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS


@dataclass(frozen=True)
class Limit:
    name: str
    scope: str
    window: str
    amount_nanocents: int
    purpose: Optional[str]
    model_id: Optional[str]

    def matches(
        self,
        *,
        model_id: Optional[str],
        purpose: Optional[str],
        actor_id: Optional[str],
    ) -> bool:
        if self.purpose is not None and self.purpose != purpose:
            return False
        if self.model_id is not None and self.model_id != model_id:
            return False
        if self.scope == "actor" and not actor_id:
            return False
        return True


def parse_limits(raw: Optional[dict]) -> list[Limit]:
    if not raw:
        return []
    limits = []
    for name, spec in raw.items():
        limits.append(_parse_one(name, spec))
    return limits


def _parse_one(name: str, spec: dict) -> Limit:
    if not isinstance(spec, dict):
        raise ValueError(
            f"limit {name!r}: expected a mapping, got {type(spec).__name__}"
        )
    keys = set(spec)
    missing = REQUIRED_FIELDS - keys
    if missing:
        raise ValueError(
            f"limit {name!r}: missing required field(s): {sorted(missing)}"
        )
    unknown = keys - ALL_FIELDS
    if unknown:
        raise ValueError(f"limit {name!r}: unknown field(s): {sorted(unknown)}")

    scope = spec["scope"]
    if scope not in VALID_SCOPES:
        raise ValueError(
            f"limit {name!r}: invalid scope {scope!r}, must be one of {sorted(VALID_SCOPES)}"
        )

    window = spec["window"]
    if window not in ALL_WINDOWS:
        raise ValueError(
            f"limit {name!r}: invalid window {window!r}, must be one of {sorted(ALL_WINDOWS)}"
        )

    amount_usd = spec["amount_usd"]
    if not isinstance(amount_usd, (int, float)) or amount_usd <= 0:
        raise ValueError(
            f"limit {name!r}: amount_usd must be a positive number, got {amount_usd!r}"
        )

    return Limit(
        name=name,
        scope=scope,
        window=window,
        amount_nanocents=int(Nanocents.from_usd(float(amount_usd))),
        purpose=spec.get("purpose"),
        model_id=spec.get("model_id"),
    )
