from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def make_audit_entry(
    action: str,
    entity: str = "",
    period: str = "",
    original: Any = "",
    new_value: Any = "",
    reason: str = "",
    method: str = "",
) -> dict:
    return {
        "Timestamp UTC": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "Action": action,
        "Entity": entity,
        "Period": period,
        "Original": original,
        "New Value": new_value,
        "Reason": reason,
        "Method": method,
    }
