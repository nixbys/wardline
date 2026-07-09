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

from cranus.common.errors import AccessDeniedError, KillSwitchEngagedError
from cranus.governance import abac, kill_switch
from cranus.storage.models.governance import User


def enforce_authenticated(user: User) -> None:
    if user.revoked:
        raise AccessDeniedError("this user's access has been revoked")


def enforce_kill_switch(db: Session) -> None:
    if kill_switch.is_enabled(db):
        raise KillSwitchEngagedError("the admin kill switch is engaged; all query paths are frozen")


def filter_sources_by_license(user: User, sources: list[dict]) -> list[dict]:
    return [s for s in sources if abac.check_access(user, s.get("license"))]
