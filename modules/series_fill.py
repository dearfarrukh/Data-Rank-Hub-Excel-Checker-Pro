from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from modules.audit_log import make_audit_entry
from modules.correction_manager import forced_expected
from modules.data_cleaner import classify_cell
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
    excluded_cells: set[tuple[str, str]] | None = None,
) -> pd.DataFrame:
    rules = lifecycle_rules if lifecycle_rules is not None else load_lifecycle_rules()
    lookup = rule_lookup(rules)
    rows: list[dict] = []
    decimals = detect_decimals(df, period_columns)
    excluded_cells = excluded_cells or set()

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
            # Only true blanks are eligible. Invalid text such as BAD_TEXT must
            # remain a data error and must never be silently interpolated.
            raw_kind, _ = classify_cell(df.at[row_index, period_columns[i]])
            if raw_kind != "blank":
                continue
            if (entity, period) in excluded_cells:
                continue
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


def find_repeated_fill_candidates(
    df: pd.DataFrame,
    period_columns: list[str],
    eligible_entities: set[str] | None = None,
    repeated_threshold: int = 2,
) -> pd.DataFrame:
    """Build interpolation candidates for repeated-value runs.

    Safety rules:
    - Regular repeated non-zero runs only.
    - The first value in the repeated run is preserved as the left anchor.
    - Only later duplicate cells in that run are changed.
    - The period immediately after the run must contain a valid numeric value.
    - If ``eligible_entities`` is supplied, only those entities are considered.

    Example: 100, 100, 110 -> 100, 105, 110.
    """
    from modules.jump_checker import repeated_runs

    rows: list[dict] = []
    decimals = detect_decimals(df, period_columns)
    eligible = {str(x).strip() for x in eligible_entities} if eligible_entities is not None else None

    for row_index in df.index:
        entity = str(df.at[row_index, "Entity"]).strip()
        if not entity or (eligible is not None and entity not in eligible):
            continue

        numeric = pd.to_numeric(df.loc[row_index, period_columns], errors="coerce")
        values = numeric.tolist()
        for run in repeated_runs(values, int(repeated_threshold)):
            value = run["value"]
            if float(value) == 0:
                continue

            start = int(run["start_index"])
            end = int(run["end_index"])
            right = end + 1

            # Repeated-value interpolation needs a real next-period anchor.
            # We deliberately do not jump across blanks or invalid cells.
            if right >= len(values) or pd.isna(values[right]):
                continue

            left_value = float(values[start])
            right_value = float(values[right])
            if left_value == right_value:
                continue

            run_start = str(period_columns[start])
            run_end = str(period_columns[end])
            run_label = run_start if run_start == run_end else f"{run_start} → {run_end}"

            # Preserve the first occurrence and interpolate only duplicate cells.
            for i in range(start + 1, end + 1):
                new_value = _linear(left_value, right_value, start, right, i, decimals)
                original = df.at[row_index, period_columns[i]]
                # Skip no-op changes after rounding.
                try:
                    if float(original) == float(new_value):
                        continue
                except Exception:
                    pass
                rows.append({
                    "Entity": entity,
                    "Run Period": run_label,
                    "Period": str(period_columns[i]),
                    "Row Index": int(row_index),
                    "Column": str(period_columns[i]),
                    "Original": original,
                    "New Value": new_value,
                    "Method": "Repeated-value linear interpolation",
                    "Previous Anchor": str(period_columns[start]),
                    "Previous Value": left_value,
                    "Next Anchor": str(period_columns[right]),
                    "Next Value": right_value,
                })

    return pd.DataFrame(rows)


def apply_repeated_fill_candidates(df: pd.DataFrame, candidates: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Apply previewed repeated-value interpolation candidates."""
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
            "Repeated Series Fill",
            entity=str(row["Entity"]),
            period=str(row["Period"]),
            original=original,
            new_value=value,
            reason=(
                f"Repeated-value run {row['Run Period']} interpolated between "
                f"{row['Previous Anchor']} and {row['Next Anchor']}"
            ),
            method="Repeated-value linear interpolation",
        ))
    return out, logs
