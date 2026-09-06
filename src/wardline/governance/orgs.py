"""Org/workspace lifecycle (commercialization roadmap Pillar 1). Thin
governance layer over storage/models/orgs.py, matching this codebase's
existing router/business-logic split -- `api/routers/orgs.py` is a thin
wrapper around this module the same way `api/routers/auth.py` wraps
`governance/accounts.py`.

Deliberately narrow, matching the model's own docstring: this is the
grouping entity invites need, not a seat-billing system. One owner per
org (whoever created it), members otherwise unprivileged relative to
their existing global `role` (admin/analyst/viewer) -- there's no
separate "role within this org" concept yet.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from wardline.common.errors import AccessDeniedError
from wardline.governance import accounts
from wardline.storage.models.governance import User
from wardline.storage.models.orgs import Organization


def create_organization(db: Session, *, owner: User, name: str) -> Organization:
    if owner.org_id is not None:
        raise AccessDeniedError("you already belong to an organization")
    org = Organization(name=name, owner_user_id=owner.id)
    db.add(org)
    db.flush()
    owner.org_id = org.id
    db.flush()
    return org


def get_organization(db: Session, org_id: str) -> Organization | None:
    return db.get(Organization, org_id)


def list_org_members(db: Session, org: Organization) -> list[User]:
    return list(db.query(User).filter(User.org_id == org.id))


def invite_to_org(db: Session, *, org: Organization, inviter: User, email: str, role: str) -> str:
    if inviter.id != org.owner_user_id:
        raise AccessDeniedError("only the organization's owner can invite members")
    return accounts.create_invite(db, email=email, role=role, org_id=org.id)
