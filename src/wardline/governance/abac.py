"""Attribute-based access control (report 4.6): fine-grained rules on top of
RBAC, keyed on document attributes rather than just the caller's role —
here, license. `viewer`s can't see documents licensed for internal use only;
`analyst`/`admin` can see everything a `viewer` can plus internal material.
"""

from __future__ import annotations

from wardline.storage.models.governance import ROLE_ADMIN, ROLE_ANALYST, User

_INTERNAL_ONLY_LICENSES = {"internal-only"}


def check_access(user: User, license: str | None) -> bool:
    if license not in _INTERNAL_ONLY_LICENSES:
        return True
    return user.role in (ROLE_ADMIN, ROLE_ANALYST)
