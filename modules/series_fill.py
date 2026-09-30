from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from modules.audit_log import make_audit_entry
from modules.correction_manager import forced_expected
from modules.lifecycle import classify_lifecycle, load_lifecycle_rules, rule_lookup
from modules.orientation import parse_period


@dataclass
class FillCandidate:
    entity: str
    period: str
    row_index: int
    column: str
    original: object
    new_value: float
    previous_period: str
    previous_value: float
    next_period: str
    next_value: float
    method: str = "Linear interpolation"


def detect_decimals(df: pd.DataFrame, period_columns: list[str]) -> int:
    values: list[float] = []
    for col in period_columns:
        numeric = pd.to_numeric(df[col], errors="coerce").dropna()
        if not numeric.empty:
            values.extend(numeric.astype(float).tolist())
        if len(values) >= 5000:
            break
    if not values:
        return 2
    sample = values[:5000]
    for decimals in range(0, 7):
        matches = sum(abs(v - round(v, decimals)) < 10 ** (-(decimals + 4)) for v in sample)
        if matches / len(sample) >= 0.95:
            return decimals
    return 6


def _linear(prev: float, nxt: float, i0: int, i1: int, i: int, decimals: int) -> float:
    if i1 == i0:
        return round(float(prev), decimals)
    value = float(prev) + (float(nxt) - float(prev)) * ((i - i0) / (i1 - i0))
    return round(value, decimals)


def find_safe_fill_candidates(
    df: pd.DataFrame,
    period_columns: list[str],
    lifecycle_rules=None,
    user_overrides: list[dict] | None = None,
) -> pd.DataFrame:
    rules = lifecycle_rules if lifecycle_rules is not None else load_lifecycle_rules()
    lookup = rule_lookup(rules)
    rows: list[dict] = []
    decimals = detect_decimals(df, period_columns)

    for row_index in df.index:
        entity = str(df.at[row_index, "Entity"]).strip()
        numeric = pd.to_numeric(df.loc[row_index, period_columns], errors="coerce")
        values = numeric.tolist()
        valid = [i for i, v in enumerate(values) if not pd.isna(v)]
        if len(valid) < 2:
            continue
        first, last = valid[0], valid[-1]
        for i in range(first + 1, last):
            if not pd.isna(values[i]):
                continue
            period = str(period_columns[i])
            forced, _ = forced_expected(entity, period, user_overrides)
            if forced:
                continue
            lifecycle_status, _ = classify_lifecycle(entity, period, lookup)
            if lifecycle_status in {"EXPECTED_BEFORE_START", "EXPECTED_AFTER_END", "PROTECTED_TRANSITION"}:
                continue
            left = next((j for j in range(i - 1, -1, -1) if not pd.isna(values[j])), None)
            right = next((j for j in range(i + 1, len(values)) if not pd.isna(values[j])), None)
            if left is None or right is None:
                continue
            # Do not interpolate across a protected lifecycle transition year.
            blocked = False
            for j in range(left + 1, right):
                status, _ = classify_lifecycle(entity, period_columns[j], lookup)
                if status == "PROTECTED_TRANSITION":
                    blocked = True
                    break
                forced_gap, _ = forced_expected(entity, period_columns[j], user_overrides)
                if forced_gap:
                    blocked = True
                    break
            if blocked:
                continue
            new_value = _linear(values[left], values[right], left, right, i, decimals)
            rows.append({
                "Entity": entity,
                "Period": period,
                "Row Index": int(row_index),
                "Column": str(period_columns[i]),
                "Original": df.at[row_index, period_columns[i]],
                "New Value": new_value,
                "Method": "Linear interpolation",
                "Previous Anchor": str(period_columns[left]),
                "Previous Value": float(values[left]),
                "Next Anchor": str(period_columns[right]),
                "Next Value": float(values[right]),
            })
    return pd.DataFrame(rows)


def apply_fill_candidates(df: pd.DataFrame, candidates: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    out = df.copy()
    logs: list[dict] = []
    if candidates is None or candidates.empty:
        return out, logs
    for _, row in candidates.iterrows():
        idx = int(row["Row Index"])
        col = str(row["Column"])
        original = out.at[idx, col]
        value = float(row["New Value"])
        out.at[idx, col] = value
        logs.append(make_audit_entry(
            "Series Fill",
            entity=str(row["Entity"]),
            period=str(row["Period"]),
            original=original,
            new_value=value,
            reason=f"Internal gap between {row['Previous Anchor']} and {row['Next Anchor']}",
            method="Linear interpolation",
        ))
    return out, logs
