from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from modules.correction_manager import forced_expected
from modules.lifecycle import load_lifecycle_rules, rule_lookup, classify_lifecycle


@dataclass(frozen=True)
class CoverageCandidate:
    entity: str
    candidate_type: str
    blank_from: str
    blank_to: str
    first_or_last_period: str
    first_or_last_value: float | None
    blank_count: int
    continuation_count: int
    suggested_action: str


def _is_number(value) -> bool:
    try:
        return not pd.isna(value)
    except Exception:
        return False


def _range_label(periods: list[str]) -> str:
    if not periods:
        return ""
    return periods[0] if len(periods) == 1 else f"{periods[0]}–{periods[-1]}"


def _all_expected_by_rules(entity: str, periods: list[str], rules, user_overrides) -> bool:
    if not periods:
        return False
    lookup = rule_lookup(rules)
    for period in periods:
        forced, _ = forced_expected(entity, period, user_overrides)
        if forced:
            continue
        status, _ = classify_lifecycle(entity, period, lookup)
        if status in {"EXPECTED_BEFORE_START", "EXPECTED_AFTER_END", "PROTECTED_TRANSITION"}:
            continue
        return False
    return True


def detect_start_end_candidates(
    df: pd.DataFrame,
    period_columns: list,
    numeric_matrix: pd.DataFrame,
    lifecycle_rules=None,
    user_overrides: list[dict] | None = None,
    min_following_values: int = 2,
) -> pd.DataFrame:
    """Find unclassified leading/trailing blank ranges.

    These are not declared errors automatically. They are review candidates so the
    user can confirm a real series start/end, mark missing data, or apply a historical
    predecessor/successor rule. Known lifecycle/Force Correct ranges are excluded.
    """
    rules = lifecycle_rules if lifecycle_rules is not None else load_lifecycle_rules()
    rows: list[dict] = []

    for idx in df.index:
        entity = str(df.at[idx, "Entity"]).strip()
        vals = [numeric_matrix.at[idx, p] for p in period_columns]
        known = [i for i, v in enumerate(vals) if _is_number(v)]
        if not known:
            continue

        first_i, last_i = known[0], known[-1]

        if first_i > 0:
            blank_periods = [str(p) for p in period_columns[:first_i]]
            if not _all_expected_by_rules(entity, blank_periods, rules, user_overrides):
                continuation = sum(_is_number(v) for v in vals[first_i:])
                if continuation >= min_following_values:
                    first_period = str(period_columns[first_i])
                    first_value = float(vals[first_i])
                    rows.append({
                        "Severity": "REVIEW",
                        "Entity": entity,
                        "Period": _range_label(blank_periods),
                        "Problem": "Start Year Candidate",
                        "Current Value": "",
                        "Previous Value": "",
                        "Previous Rank": "",
                        "Next Value": first_value,
                        "Next Rank": "",
                        "Top-N Cutoff": "",
                        "Why Flagged": (
                            f"{len(blank_periods)} leading period(s) are blank. First available data is "
                            f"{first_period} = {first_value:g}, followed by {continuation - 1} later populated period(s)."
                        ),
                        "What To Do": (
                            f"Confirm {first_period} as the true start year if correct, or mark the earlier range as missing data."
                        ),
                        "Source": "Coverage start/end",
                        "Candidate Type": "START",
                        "Candidate Period": first_period,
                        "Boundary Period": str(period_columns[first_i - 1]),
                        "Blank From": blank_periods[0],
                        "Blank To": blank_periods[-1],
                        "Blank Count": len(blank_periods),
                    })

        if last_i < len(period_columns) - 1:
            blank_periods = [str(p) for p in period_columns[last_i + 1:]]
            if not _all_expected_by_rules(entity, blank_periods, rules, user_overrides):
                preceding = sum(_is_number(v) for v in vals[: last_i + 1])
                if preceding >= min_following_values:
                    last_period = str(period_columns[last_i])
                    last_value = float(vals[last_i])
                    rows.append({
                        "Severity": "REVIEW",
                        "Entity": entity,
                        "Period": _range_label(blank_periods),
                        "Problem": "End Year Candidate",
                        "Current Value": "",
                        "Previous Value": last_value,
                        "Previous Rank": "",
                        "Next Value": "",
                        "Next Rank": "",
                        "Top-N Cutoff": "",
                        "Why Flagged": (
                            f"{len(blank_periods)} trailing period(s) are blank. Last available data is "
                            f"{last_period} = {last_value:g}."
                        ),
                        "What To Do": (
                            f"Confirm {last_period} as the true end year if correct, or mark the later range as missing data."
                        ),
                        "Source": "Coverage start/end",
                        "Candidate Type": "END",
                        "Candidate Period": last_period,
                        "Boundary Period": str(period_columns[last_i + 1]),
                        "Blank From": blank_periods[0],
                        "Blank To": blank_periods[-1],
                        "Blank Count": len(blank_periods),
                    })

    columns = [
        "Severity", "Entity", "Period", "Problem", "Current Value", "Previous Value", "Previous Rank",
        "Next Value", "Next Rank", "Top-N Cutoff", "Why Flagged", "What To Do", "Source",
        "Candidate Type", "Candidate Period", "Boundary Period", "Blank From", "Blank To", "Blank Count",
    ]
    return pd.DataFrame(rows, columns=columns)
