"""Connector plugin registry — the mechanism behind "add a source later
without touching core code" (report 4.1 + the plan's runtime "add a source"
story).

Built-in connectors register via `@register_connector(...)` at import time.
Third-party connectors register the same way from an installed package that
declares a `wardline.connectors` entry point — no special-casing between the
two, and no core-repo change needed to add one.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from wardline.common.logging import get_logger
from wardline.connectors.base import Connector

logger = get_logger(__name__)

_REGISTRY: dict[str, type[Connector]] = {}
_ENTRY_POINTS_LOADED = False


def register_connector(name: str):
    def decorator(cls: type[Connector]):
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return decorator


def _load_builtin_connectors() -> None:
    # Import side effects register each module's @register_connector class.
    from wardline.connectors import (  # noqa: F401
        archive_org,
        nmap_scan,
        opencorporates,
        sec_edgar,
        threat_intel,
        upload,
        web_crawler,
        wikidata,
        wikipedia,
    )


def _load_entry_point_connectors() -> None:
    global _ENTRY_POINTS_LOADED
    if _ENTRY_POINTS_LOADED:
        return
    for ep in entry_points(group="wardline.connectors"):
        try:
            cls = ep.load()
            _REGISTRY[ep.name] = cls
            cls.name = ep.name
            logger.info("connector.registered_external", name=ep.name)
        except Exception as exc:
            logger.error("connector.load_failed", name=ep.name, error=str(exc))
    _ENTRY_POINTS_LOADED = True


def _ensure_loaded() -> None:
    if not _REGISTRY:
        _load_builtin_connectors()
    _load_entry_point_connectors()


def list_connectors() -> dict[str, type[Connector]]:
    _ensure_loaded()
    return dict(_REGISTRY)


def get_connector(name: str, config: dict | None = None) -> Connector:
    _ensure_loaded()
    if name not in _REGISTRY:
        raise KeyError(f"No connector registered under name={name!r}")
    return _REGISTRY[name](config=config or {})
