"""The policy enforcement point (report 4.6): a single chokepoint every
authenticated request passes through, so access rules can't be bypassed by
a clever query. `api/deps.get_current_user` calls `enforce_authenticated` on
every request; `api/deps.get_current_user_active` additionally calls
`enforce_kill_switch`, and is used only on the query/agent surface — not on
admin routes. Gating admin routes on the kill switch too would make it a
one-way ratchet: once engaged, no admin could ever reach the endpoint that
disables it again. The query pipeline calls `filter_sources_by_license`
right before context assembly, so ABAC is enforced on the actual evidence
handed to the LLM, not just at the door.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from wardline.common.errors import AccessDeniedError, KillSwitchEngagedError
from wardline.governance import abac, engagements, kill_switch
from wardline.storage.models.governance import User


def enforce_authenticated(user: User) -> None:
    if user.revoked:
        raise AccessDeniedError("this user's access has been revoked")


def enforce_kill_switch(db: Session) -> None:
    if kill_switch.is_enabled(db):
        raise KillSwitchEngagedError("the admin kill switch is engaged; all query paths are frozen")


def enforce_engagement_scope(db: Session, engagement_id: str | None, target: str) -> None:
    """Required before running any connector with `requires_engagement = True`
    (see connectors/base.py) — dual-use, target-lookup tools (Shodan/Censys-
    style exposure lookups, breach-check APIs, SpiderFoot-style aggregators)
    must not be runnable against an arbitrary target just because the caller
    holds an admin/analyst role; a role only says who you are, not what
    you've been authorized to look at.
    """
    if not engagement_id:
        raise AccessDeniedError(
            "this connector requires an engagement_id scoping the authorized target"
        )
    engagement = engagements.get_engagement(db, engagement_id)
    if engagement is None:
        raise AccessDeniedError(f"no such engagement: {engagement_id!r}")
    if not engagements.is_active(engagement):
        raise AccessDeniedError(f"engagement {engagement_id!r} is revoked or outside its validity window")
    if not engagements.target_in_scope(engagement.target, target):
        raise AccessDeniedError(
            f"target {target!r} is outside engagement {engagement_id!r}'s authorized scope "
            f"({engagement.target!r})"
        )


def filter_sources_by_license(user: User, sources: list[dict]) -> list[dict]:
    return [s for s in sources if abac.check_access(user, s.get("license"))]
