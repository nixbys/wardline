"""Shared exception types used across planes."""

from __future__ import annotations


class WardlineError(Exception):
    """Base class for all application-raised errors."""


class NotFoundError(WardlineError):
    """A requested resource does not exist."""


class AccessDeniedError(WardlineError):
    """RBAC/ABAC policy denied the action (see governance/pep.py)."""


class KillSwitchEngagedError(WardlineError):
    """The admin kill switch is active; all query paths are frozen."""


class QuarantinedError(WardlineError):
    """A document/chunk failed a quality gate and was quarantined."""


class ConnectorError(WardlineError):
    """A collection-plane connector failed to discover/fetch/parse a source item."""


class InsufficientEvidenceError(WardlineError):
    """The query pipeline could not assemble enough grounded evidence to answer."""
