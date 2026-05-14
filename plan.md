# datasette-llm-limits — specification

A Datasette plugin that enforces **windowed spending limits** on LLM usage
within a single Datasette instance. Plugs into
[`datasette-llm-accountant`](https://github.com/datasette/datasette-llm-accountant)
as an `Accountant` implementation, so it runs transparently for every prompt
made through `datasette-llm`.

`datasette-llm-allowance` is the existing accountant for a *refillable*
balance (top up $X, spend until empty). `datasette-llm-limits` is for the
distinct case of **time-windowed caps that reset automatically** — "no
single user may spend more than $1.00 per day", "the whole instance is
capped at $50 per calendar month", etc.

---

## Goals

1. Define spending caps in `datasette.yaml` as `(scope, window) → amount`
   triples, where scope is the actor / model / purpose / instance and
   window is a rolling or calendar period.
2. Reject the reservation phase of an LLM call when granting it would
   push any matching scope over its cap, returning a clear
   `InsufficientBalanceError` so `datasette-llm` surfaces a sensible error
   to the caller.
3. Record actual settled cost so future reservations within the same
   window see an accurate running total.
4. Expose a read-only `/-/llm-limits` view for operators to inspect
   current usage vs. configured caps.

Out of scope: refillable balances (see `datasette-llm-allowance`),
request-count rate limiting unrelated to spend, currency conversion.

## Dependencies

Declared in `pyproject.toml`:

```toml
[project]
dependencies = [
    "datasette>=1.0a28",
    "datasette-llm-accountant",
]
```

`datasette>=1.0a28` is required for:

- The internal-database API (`datasette.get_internal_database()`),
- The 1.0 `permissions:` block and `allow:` blocks used to gate the
  inspection view,
- The `datasette.allowed(...)` permission-check coroutine.

`datasette-llm-accountant` is required for the `Accountant`, `Tx`,
`Nanocents` and `InsufficientBalanceError` primitives this plugin builds
on.

---

## Configuration

All configuration lives in `datasette.yaml` under
`plugins.datasette-llm-limits.limits`. Each entry is a named limit; the
plugin checks **every matching limit** on every reservation and rejects
the call if any one is over.

```yaml
plugins:
  datasette-llm-limits:
    limits:
      # Per-user, rolling 24h
      per-user-daily:
        scope: actor
        window: rolling-24h
        amount_usd: 1.00

      # Per-user, calendar month (resets at UTC midnight on day 1)
      per-user-monthly:
        scope: actor
        window: calendar-month
        amount_usd: 20.00

      # Per-actor cap that only applies to one purpose
      enrichments-per-user-daily:
        scope: actor
        window: rolling-24h
        amount_usd: 5.00
        purpose: enrichments

      # Instance-wide cap, any actor, any purpose
      instance-monthly:
        scope: instance
        window: calendar-month
        amount_usd: 250.00

      # Per-model cap (e.g. limit expensive models per actor)
      gpt5-pro-per-user-weekly:
        scope: actor
        window: rolling-7d
        amount_usd: 10.00
        model_id: gpt-5-pro
```

### Field reference

| Field        | Type     | Required | Description |
|--------------|----------|----------|-------------|
| `scope`      | string   | yes      | One of `actor`, `instance`. `actor` partitions usage by `actor_id`; `instance` aggregates across all actors. |
| `window`     | string   | yes      | One of `rolling-24h`, `rolling-7d`, `rolling-30d`, `calendar-day`, `calendar-week`, `calendar-month`. Rolling windows look back N seconds from now. Calendar windows reset at UTC midnight on the appropriate boundary. |
| `amount_usd` | number   | yes      | Cap in US dollars. Internally converted to `Nanocents`. Floats are accepted; precision is preserved via `Nanocents.from_usd`. |
| `purpose`    | string   | no       | If set, the limit only applies when the prompt's `purpose` matches. Omitting it means the limit applies regardless of purpose. |
| `model_id`   | string   | no       | If set, the limit only applies when the prompt's `model_id` matches. Omitting it means the limit applies regardless of model. |

A limit "matches" a reservation when:

- `purpose` is unset OR equals the prompt's purpose, AND
- `model_id` is unset OR equals the prompt's model id, AND
- `scope == "instance"` OR (`scope == "actor"` AND the reservation has a
  non-empty `actor_id`).

Reservations made by unauthenticated callers (no `actor_id`) skip all
`scope: actor` limits but still consume any `scope: instance` limit.

### Schema validation

Configuration is validated at startup. Unknown fields, unknown `scope` or
`window` values, or non-positive `amount_usd` raise `ValueError` before
the Datasette app starts.

---

## Accountant behaviour

The plugin registers a single `Accountant` via
`@hookimpl register_llm_accountants`:

```python
class LimitsAccountant(Accountant):
    async def reserve(self, nanocents, model_id=None, purpose=None, actor_id=None) -> Tx: ...
    async def settle(self, tx, nanocents, model_id=None, purpose=None, actor_id=None): ...
    async def rollback(self, tx): ...
```

### `reserve`

1. Compute the set of matching limits (see above).
2. For each, query the internal database for the actor's (or instance's)
   total settled cost within the limit's window plus all **outstanding**
   reservations (settled=NULL) for that scope.
3. If `running_total + nanocents > amount`, raise
   `InsufficientBalanceError` with the limit's name and the headroom
   remaining. The error message must be safe to surface to users (no
   internal IDs).
4. Otherwise insert a row into `llm_limits_tx` recording the reservation
   amount, scope, window-start timestamp, and the matching limit names.
5. Return a `Tx` whose payload is the inserted row's id.

The check + insert must happen inside an `IMMEDIATE` transaction on the
internal database so two concurrent reservations cannot both pass a cap
that only one of them would individually fit under.

### `settle`

1. Look up the reservation row by `tx.id`.
2. Update its `settled_nanocents` column to the supplied amount (which
   may be less than the reservation, equal to it, or up to the
   `ReservationExceededError` ceiling enforced by
   `datasette-llm-accountant`).
3. Set `settled_at = now()`.

### `rollback`

Equivalent to `settle(tx, Nanocents(0))`. The reservation row remains
visible in the audit trail but no longer counts toward any window's
running total.

---

## Storage

Tables are created in Datasette's internal database (the path passed via
`--internal`). All writes go through `datasette.get_internal_database()`
so they participate in the normal Datasette write queue.

### `llm_limits_tx`

```sql
CREATE TABLE llm_limits_tx (
    id TEXT PRIMARY KEY,                -- ULID for monotonic ordering
    created_at TEXT NOT NULL,           -- ISO-8601 UTC
    settled_at TEXT,                    -- ISO-8601 UTC; NULL while reserved
    actor_id TEXT,                      -- NULL for unauthenticated
    purpose TEXT,                       -- NULL when not provided
    model_id TEXT,                      -- NULL when not provided
    reserved_nanocents INTEGER NOT NULL,
    settled_nanocents INTEGER,          -- NULL while reserved
    matched_limits TEXT NOT NULL        -- JSON array of limit names
);

CREATE INDEX llm_limits_tx_actor_created
    ON llm_limits_tx(actor_id, created_at);
CREATE INDEX llm_limits_tx_settled_at
    ON llm_limits_tx(settled_at);
```

The plugin migrates this table forward via
`datasette.get_internal_database()` on startup and on every new
Datasette release.

### Window queries

A "running total" for a limit is computed as:

```sql
SELECT
    COALESCE(SUM(
        CASE WHEN settled_at IS NULL
             THEN reserved_nanocents
             ELSE settled_nanocents
        END
    ), 0)
FROM llm_limits_tx
WHERE created_at >= :window_start
  AND (:scope_actor IS NULL OR actor_id = :scope_actor)
  AND (:purpose IS NULL OR purpose = :purpose)
  AND (:model_id IS NULL OR model_id = :model_id);
```

`:window_start` is computed from the limit's `window`:

- `rolling-24h` → `now() - 24h`
- `rolling-7d` → `now() - 7d`
- `rolling-30d` → `now() - 30d`
- `calendar-day` → start of current UTC day
- `calendar-week` → most recent Monday UTC at 00:00
- `calendar-month` → first day of current UTC month at 00:00

Calendar boundaries are computed in Python (`datetime` + `timedelta`),
not in SQL, to keep the query portable.

---

## Permissions and web UI

### Permissions

- `datasette-llm-limits-view` — required to access the inspection view.
  Defaults to **deny** (Datasette 1.0 default for plugin-introduced
  permissions).

Operators grant it in `datasette.yaml`:

```yaml
permissions:
  datasette-llm-limits-view:
    id: "*"          # any signed-in user
    # or id: ["github:9599"] for a specific actor
```

### `/-/llm-limits`

Registered via `register_routes`. Returns HTML by default and JSON when
called with `?_format=json` or `Accept: application/json`. Renders:

- A table of configured limits with current running total, remaining
  headroom, and time-until-reset.
- The 50 most recent transactions, with links to query the underlying
  `_internal.llm_limits_tx` table (visible to actors with
  `view-database` on `_internal`).

Returns `403` if the actor doesn't hold `datasette-llm-limits-view`.

---

## Errors surfaced to callers

When `reserve` rejects, the message must follow the format:

```
Limit "<limit-name>" exceeded: <amount-used-usd> used of <cap-usd>
in <window>. Try again after <reset-time-iso>.
```

`reset-time-iso` is omitted for rolling windows (they slide
continuously) and included for calendar windows.

---

## Testing

- Unit tests for the matching algorithm (does a reservation match a
  given limit?).
- Unit tests for window-start computation, including DST-irrelevant UTC
  boundaries.
- Integration tests using `datasette-test` that:
  - Configure a tight limit and assert the second reservation is
    rejected.
  - Configure a per-actor limit and assert two actors are tracked
    independently.
  - Settle a reservation under the reserved amount and assert the
    headroom returns.
  - Roll back a reservation and assert it no longer counts.
- A concurrency test that fires N reservations in parallel against a
  cap that fits N-1 of them; exactly one must fail.

---

## Open questions

- **Soft vs. hard limits**: a future version may add `mode: soft` that
  logs over-limit attempts without rejecting them. Out of scope for v1.
- **Per-team / per-API-key scopes**: currently `actor_id` is the only
  partitioning key. We may want to plumb arbitrary actor properties
  (`actor.team`, `actor.org`) into limit matching later. v1 just keys
  on `actor.id`.
- **Cost prediction**: reservation amounts come from
  `datasette-llm-accountant`'s configured `auto_reservation_usd` /
  purpose reservation. If a prompt is much cheaper than the reservation,
  headroom is over-consumed until settle. Acceptable for v1; could be
  improved with a smarter reservation estimator later.
