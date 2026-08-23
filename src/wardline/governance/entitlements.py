"""Plan-based feature gating (commercialization roadmap Pillar 5): whether
a query mode is allowed, and how far `max_sources` can be pushed, for the
caller's current plan. `api/routers/query.py` is the only caller — kept as
pure functions taking a plan id (not a `User`/db session) so this is
trivially unit-testable without touching `governance/billing.py`'s
Stripe-adjacent code.
"""

from __future__ import annotations

from wardline.common.errors import AccessDeniedError
from wardline.common.plans import get_plan


def enforce_mode_allowed(plan_id: str, mode: str) -> None:
    plan = get_plan(plan_id)
    if mode not in plan.modes:
        raise AccessDeniedError(
            f"the {plan.label} plan doesn't include {mode!r} mode — "
            f"available modes: {', '.join(sorted(plan.modes))}"
        )


def capped_max_sources(plan_id: str, requested: int) -> int:
    return min(requested, get_plan(plan_id).max_sources_cap)
