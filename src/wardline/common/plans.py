"""Plan/entitlement definitions (commercialization roadmap Pillar 5:
Billing & packaging). One place to retune pricing/limits — nothing else
in this codebase hard-codes a dollar amount or a per-plan cap;
`governance/entitlements.py` and `governance/billing.py` both read from
`PLANS` here, and `billing.py` (not this module) is where a plan id maps
to the real Stripe Price id via `Settings` — this module stays free of
env/settings reads so it's a plain, trivially-testable data table.

**Prices below are placeholders**, not a business decision this code can
make on your behalf — change `monthly_price_usd` once real numbers exist;
nothing else needs to change. Wire up the matching Stripe Price object's id
via `STRIPE_PRICE_ID_PRO`/`STRIPE_PRICE_ID_TEAM` in `.env` (see
`governance/billing.py`) once one exists in the Stripe dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass

FREE = "free"
PRO = "pro"
TEAM = "team"
ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class Plan:
    id: str
    label: str
    monthly_price_usd: float | None  # None => "contact sales", not a real checkout price
    per_seat: bool
    modes: frozenset[str]  # query modes this plan may use (see common/schemas.QueryRequest.mode)
    max_sources_cap: int  # hard ceiling on QueryRequest.max_sources, regardless of what's asked
    self_serve_checkout: bool  # False => Enterprise-style "talk to us", no Stripe Checkout button


PLANS: dict[str, Plan] = {
    FREE: Plan(
        id=FREE,
        label="Free",
        monthly_price_usd=0,
        per_seat=False,
        modes=frozenset({"fast", "auto"}),
        max_sources_cap=6,
        self_serve_checkout=False,  # nothing to check out -- it's the unpaid default
    ),
    PRO: Plan(
        id=PRO,
        label="Pro",
        monthly_price_usd=20,
        per_seat=False,
        modes=frozenset({"fast", "auto", "research"}),
        max_sources_cap=12,
        self_serve_checkout=True,
    ),
    TEAM: Plan(
        id=TEAM,
        label="Team",
        monthly_price_usd=15,
        per_seat=True,
        modes=frozenset({"fast", "auto", "research"}),
        max_sources_cap=20,
        self_serve_checkout=True,
    ),
    ENTERPRISE: Plan(
        id=ENTERPRISE,
        label="Enterprise",
        monthly_price_usd=None,
        per_seat=False,
        modes=frozenset({"fast", "auto", "research"}),
        max_sources_cap=50,
        self_serve_checkout=False,  # dedicated instance / contract, not a Stripe Checkout flow
    ),
}

DEFAULT_PLAN = FREE


def get_plan(plan_id: str) -> Plan:
    return PLANS.get(plan_id, PLANS[DEFAULT_PLAN])


def public_plan_list() -> list[dict]:
    """What GET /v1/billing/plans hands the pricing page."""
    return [
        {
            "id": plan.id,
            "label": plan.label,
            "monthly_price_usd": plan.monthly_price_usd,
            "per_seat": plan.per_seat,
            "modes": sorted(plan.modes),
            "max_sources_cap": plan.max_sources_cap,
            "self_serve_checkout": plan.self_serve_checkout,
        }
        for plan in PLANS.values()
    ]
