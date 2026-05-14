import pytest

from datasette_llm_limits.config import Limit, parse_limits


def test_parse_minimal_actor_limit():
    limits = parse_limits(
        {
            "per-user-daily": {
                "scope": "actor",
                "window": "rolling-24h",
                "amount_usd": 1.00,
            }
        }
    )
    assert len(limits) == 1
    limit = limits[0]
    assert isinstance(limit, Limit)
    assert limit.name == "per-user-daily"
    assert limit.scope == "actor"
    assert limit.window == "rolling-24h"
    # 1.00 USD = 100_000_000_000 nanocents
    assert limit.amount_nanocents == 100_000_000_000
    assert limit.purpose is None
    assert limit.model_id is None


def test_parse_instance_limit_with_purpose_and_model():
    limits = parse_limits(
        {
            "gpt5-pro-cap": {
                "scope": "actor",
                "window": "rolling-7d",
                "amount_usd": 10.00,
                "model_id": "gpt-5-pro",
            },
            "enrichments-cap": {
                "scope": "instance",
                "window": "calendar-month",
                "amount_usd": 250,
                "purpose": "enrichments",
            },
        }
    )
    by_name = {l.name: l for l in limits}
    assert by_name["gpt5-pro-cap"].model_id == "gpt-5-pro"
    assert by_name["enrichments-cap"].scope == "instance"
    assert by_name["enrichments-cap"].purpose == "enrichments"


def test_parse_empty_returns_empty_list():
    assert parse_limits({}) == []
    assert parse_limits(None) == []


@pytest.mark.parametrize(
    "bad_field,value",
    [
        ("scope", "team"),
        ("window", "rolling-1h"),
    ],
)
def test_unknown_scope_or_window_rejected(bad_field, value):
    cfg = {
        "x": {"scope": "actor", "window": "rolling-24h", "amount_usd": 1.0},
    }
    cfg["x"][bad_field] = value
    with pytest.raises(ValueError):
        parse_limits(cfg)


@pytest.mark.parametrize("amount", [0, -1, -0.5])
def test_non_positive_amount_rejected(amount):
    with pytest.raises(ValueError):
        parse_limits(
            {"x": {"scope": "actor", "window": "rolling-24h", "amount_usd": amount}}
        )


def test_unknown_field_rejected():
    with pytest.raises(ValueError):
        parse_limits(
            {
                "x": {
                    "scope": "actor",
                    "window": "rolling-24h",
                    "amount_usd": 1.0,
                    "color": "red",
                }
            }
        )


def test_missing_required_field_rejected():
    with pytest.raises(ValueError):
        parse_limits({"x": {"scope": "actor", "window": "rolling-24h"}})


# --- matching ---

def _limit(**kwargs):
    base = dict(
        name="l",
        scope="actor",
        window="rolling-24h",
        amount_nanocents=100,
        purpose=None,
        model_id=None,
    )
    base.update(kwargs)
    return Limit(**base)


def test_instance_scope_matches_anonymous_caller():
    limit = _limit(scope="instance")
    assert limit.matches(model_id=None, purpose=None, actor_id=None)


def test_actor_scope_skips_when_actor_id_is_none():
    limit = _limit(scope="actor")
    assert not limit.matches(model_id=None, purpose=None, actor_id=None)


def test_actor_scope_matches_when_actor_id_present():
    limit = _limit(scope="actor")
    assert limit.matches(model_id=None, purpose=None, actor_id="user-1")


def test_purpose_filter_only_matches_when_purpose_matches():
    limit = _limit(scope="instance", purpose="enrichments")
    assert limit.matches(model_id=None, purpose="enrichments", actor_id=None)
    assert not limit.matches(model_id=None, purpose="chat", actor_id=None)
    assert not limit.matches(model_id=None, purpose=None, actor_id=None)


def test_model_id_filter_only_matches_when_model_matches():
    limit = _limit(scope="instance", model_id="gpt-5-pro")
    assert limit.matches(model_id="gpt-5-pro", purpose=None, actor_id=None)
    assert not limit.matches(model_id="gpt-4o", purpose=None, actor_id=None)
    assert not limit.matches(model_id=None, purpose=None, actor_id=None)
