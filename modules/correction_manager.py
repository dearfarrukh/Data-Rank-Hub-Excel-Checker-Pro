from __future__ import annotations

from typing import Any

import pandas as pd

from modules.audit_log import make_audit_entry
from modules.orientation import parse_period

FORCE_REASONS = [
    "Production not started yet",
    "Entity did not exist yet",
    "Covered by predecessor country",
    "Series intentionally starts here",
    "Series intentionally ends here",
    "Blank is correct",
    "Keep original as correct",
    "Custom reason",
]


def _period_key(period: object) -> tuple[int, int, int] | None:
    token = parse_period(period)
    return token.key if token else None


def apply_manual_value(working_df: pd.DataFrame, entity: str, period: str, value: float) -> tuple[pd.DataFrame, dict]:
    out = working_df.copy()
    mask = out["Entity"].astype(str).str.strip().eq(str(entity).strip())
    if not mask.any():
        raise ValueError(f"Entity '{entity}' was not found.")
    if period not in out.columns:
        raise ValueError(f"Period '{period}' was not found.")
    idx = out.index[mask][0]
    original = out.at[idx, period]
    out.at[idx, period] = value
    log = make_audit_entry(
        "Manual correction", entity, period, original, value,
        reason="User entered a corrected value", method="Manual",
    )
    return out, log


def add_resolution(resolutions: dict, issue_id: str, action: str, reason: str = "") -> dict:
    out = dict(resolutions or {})
    out[issue_id] = {"action": action, "reason": reason}
    return out


def remove_resolution(resolutions: dict, issue_id: str) -> dict:
    out = dict(resolutions or {})
    out.pop(issue_id, None)
    return out


def build_force_override(entity: str, period: str, reason: str, scope: str, custom_reason: str = "") -> dict:
    actual_reason = custom_reason.strip() if reason == "Custom reason" and custom_reason.strip() else reason
    return {
        "entity": str(entity).strip(),
        "boundary_period": str(period),
        "reason": actual_reason,
        "scope": scope,
    }


def forced_expected(entity: str, period: str, overrides: list[dict] | None) -> tuple[bool, str]:
    entity_norm = str(entity).strip().lower()
    target_key = _period_key(period)
    if target_key is None:
        return False, ""
    for rule in overrides or []:
        if str(rule.get("entity", "")).strip().lower() != entity_norm:
            continue
        boundary_key = _period_key(rule.get("boundary_period"))
        if boundary_key is None:
            continue
        scope = rule.get("scope", "This period only")
        match = False
        if scope == "This period only":
            match = target_key == boundary_key
        elif scope == "This and all earlier periods":
            match = target_key <= boundary_key
        elif scope == "This and all later periods":
            match = target_key >= boundary_key
        if match:
            return True, str(rule.get("reason", "User force-correct rule"))
    return False, ""
