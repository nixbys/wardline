"""The admin kill switch (report 4.6): an administrator can revoke access and
freeze the system instantly. Backed by a single row in `system_settings` so
it takes effect immediately for every in-flight process, no restart needed.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from wardline.common.config import get_settings
from wardline.storage.models.base import utcnow
from wardline.storage.models.governance import KILL_SWITCH_KEY, SystemSetting


def is_enabled(db: Session) -> bool:
    row = db.get(SystemSetting, KILL_SWITCH_KEY)
    if row is None:
        return get_settings().kill_switch_enabled_default
    return bool(row.value.get("enabled", False))


def set_enabled(db: Session, enabled: bool) -> None:
    row = db.get(SystemSetting, KILL_SWITCH_KEY)
    if row is None:
        row = SystemSetting(key=KILL_SWITCH_KEY, value={}, updated_at=utcnow())
        db.add(row)
    row.value = {"enabled": enabled}
    row.updated_at = utcnow()
    db.flush()
