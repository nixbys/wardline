"""Shared exception types used across planes."""

from __future__ import annotations


class CranusError(Exception):
    """Base class for all application-raised errors."""


class NotFoundError(CranusError):
    """A requested resource does not exist."""


class AccessDeniedError(CranusError):
    """RBAC/ABAC policy denied the action (see governance/pep.py)."""


class KillSwitchEngagedError(CranusError):
    """The admin kill switch is active; all query paths are frozen."""


class QuarantinedError(CranusError):
    """A document/chunk failed a quality gate and was quarantined."""


class ConnectorError(CranusError):
    """A collection-plane connector failed to discover/fetch/parse a source item."""


class InsufficientEvidenceError(CranusError):
    """The query pipeline could not assemble enough grounded evidence to answer."""
