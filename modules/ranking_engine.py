from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass
class RankingResult:
    ranks: pd.DataFrame
    cutoffs: dict[str, float | None]
    top_n: int


def build_ranking_matrix(numeric_matrix: pd.DataFrame, top_n: int) -> RankingResult:
    """Rank every period independently. Highest value receives rank 1."""
    ranks = numeric_matrix.rank(axis=0, method="min", ascending=False, na_option="keep")
    cutoffs: dict[str, float | None] = {}
    for column in numeric_matrix.columns:
        values = pd.to_numeric(numeric_matrix[column], errors="coerce").dropna().sort_values(ascending=False)
        if len(values) >= top_n:
            cutoffs[str(column)] = float(values.iloc[top_n - 1])
        elif len(values):
            cutoffs[str(column)] = float(values.iloc[-1])
        else:
            cutoffs[str(column)] = None
    return RankingResult(ranks=ranks, cutoffs=cutoffs, top_n=int(top_n))


def _nearest_numeric_position(values: list[float | None], start: int, step: int) -> int | None:
    i = start + step
    while 0 <= i < len(values):
        value = values[i]
        if value is not None and not pd.isna(value):
            return i
        i += step
    return None


def _linear_estimate(left_value: float, right_value: float, left_index: int, right_index: int, target_index: int) -> float:
    if right_index == left_index:
        return float(left_value)
    fraction = (target_index - left_index) / (right_index - left_index)
    return float(left_value + (right_value - left_value) * fraction)


def evaluate_missing_cell_risk(
    row_index,
    period_index: int,
    period_columns: list,
    numeric_matrix: pd.DataFrame,
    ranking: RankingResult,
    rank_margin: int = 2,
) -> dict:
    """
    Evaluate whether one missing cell could realistically affect selected Top-N.

    No value is written into the dataset. Interpolation is used only as a risk signal
    when both surrounding anchors exist.
    """
    row = numeric_matrix.loc[row_index]
    values = [None if pd.isna(v) else float(v) for v in row.tolist()]
    left_i = _nearest_numeric_position(values, period_index, -1)
    right_i = _nearest_numeric_position(values, period_index, 1)

    period = str(period_columns[period_index])
    cutoff = ranking.cutoffs.get(period)

    prev_value = values[left_i] if left_i is not None else None
    next_value = values[right_i] if right_i is not None else None
    prev_rank = None
    next_rank = None
    if left_i is not None:
        raw = ranking.ranks.loc[row_index, period_columns[left_i]]
        prev_rank = None if pd.isna(raw) else int(raw)
    if right_i is not None:
        raw = ranking.ranks.loc[row_index, period_columns[right_i]]
        next_rank = None if pd.isna(raw) else int(raw)

    reasons: list[str] = []
    estimated_value = None
    estimated_rank_risk = False

    # Local rank evidence only — never "ever Top-N in history".
    if prev_rank is not None and prev_rank <= ranking.top_n + rank_margin:
        reasons.append(f"previous available rank was {prev_rank}")
    if next_rank is not None and next_rank <= ranking.top_n + rank_margin:
        reasons.append(f"next available rank was {next_rank}")

    # For internal gaps, a straight-line value is a risk estimate only.
    if left_i is not None and right_i is not None and cutoff is not None:
        estimated_value = _linear_estimate(prev_value, next_value, left_i, right_i, period_index)
        if estimated_value >= cutoff:
            estimated_rank_risk = True
            reasons.append("between-anchor estimate reaches the selected Top-N cutoff")

    risk = bool(reasons)
    return {
        "period": period,
        "cutoff": cutoff,
        "previous_period": str(period_columns[left_i]) if left_i is not None else "",
        "previous_value": prev_value,
        "previous_rank": prev_rank,
        "next_period": str(period_columns[right_i]) if right_i is not None else "",
        "next_value": next_value,
        "next_rank": next_rank,
        "estimated_value": estimated_value,
        "risk": risk,
        "reason": "; ".join(reasons),
        "estimated_rank_risk": estimated_rank_risk,
    }


def build_top_n_risk_table(
    df: pd.DataFrame,
    period_columns: list,
    numeric_matrix: pd.DataFrame,
    top_n: int,
    rank_margin: int = 2,
) -> tuple[pd.DataFrame, RankingResult]:
    ranking = build_ranking_matrix(numeric_matrix, top_n)
    rows: list[dict] = []

    for row_index in df.index:
        entity = str(df.loc[row_index, "Entity"]).strip()
        for i, period in enumerate(period_columns):
            raw_numeric = numeric_matrix.loc[row_index, period]
            if not pd.isna(raw_numeric):
                continue
            risk = evaluate_missing_cell_risk(
                row_index=row_index,
                period_index=i,
                period_columns=period_columns,
                numeric_matrix=numeric_matrix,
                ranking=ranking,
                rank_margin=rank_margin,
            )
            if not risk["risk"]:
                continue
            rows.append({
                "Entity": entity,
                "Error Period": str(period),
                "Problem Type": "Missing value may affect Top-N",
                "Previous Period": risk["previous_period"],
                "Previous Value": risk["previous_value"],
                "Previous Rank": risk["previous_rank"],
                "Current Value": None,
                "Current Rank": None,
                "Next Period": risk["next_period"],
                "Next Value": risk["next_value"],
                "Next Rank": risk["next_rank"],
                "Top-N Cutoff": risk["cutoff"],
                "Risk Estimate": risk["estimated_value"],
                "Why Flagged": risk["reason"],
            })

    columns = [
        "Entity", "Error Period", "Problem Type", "Previous Period", "Previous Value",
        "Previous Rank", "Current Value", "Current Rank", "Next Period", "Next Value",
        "Next Rank", "Top-N Cutoff", "Risk Estimate", "Why Flagged",
    ]
    return pd.DataFrame(rows, columns=columns), ranking


def classify_top_n_safety(core_findings: pd.DataFrame, risk_table: pd.DataFrame) -> str:
    """YES=no known ranking blockers, NO=definite structural blocker, UNRESOLVED=risk needs review."""
    if not core_findings.empty:
        structural_blockers = {
            "Missing Entity Column", "Blank Entity Name", "Duplicate Entity", "Duplicate Row",
            "Duplicate Period", "Periods Out of Order", "No Period Columns", "Non-Numeric Value",
        }
        blocker_mask = (
            core_findings["Severity"].eq("MUST FIX")
            & core_findings["Category"].isin(structural_blockers)
        )
        if blocker_mask.any():
            return "NO"
        if (core_findings["Category"] == "Missing Period").any():
            return "UNRESOLVED"
    if not risk_table.empty:
        return "UNRESOLVED"
    return "YES"
