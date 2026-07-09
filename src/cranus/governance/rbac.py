"""Role-based access control (report 4.6): coarse per-route gating."""

from __future__ import annotations

from cranus.common.errors import AccessDeniedError
from cranus.storage.models.governance import User


def require_role(user: User, *roles: str) -> None:
    if user.role not in roles:
        raise AccessDeniedError(f"role {user.role!r} is not permitted; requires one of {roles}")
