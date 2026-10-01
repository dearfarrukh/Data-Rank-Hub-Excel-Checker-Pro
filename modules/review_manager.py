from __future__ import annotations

import hashlib
from typing import Iterable

import pandas as pd

SEVERITY_ORDER = {"MUST FIX": 0, "MUST CHECK": 1, "REVIEW": 2, "INFO": 3}


def issue_id(row: pd.Series | dict) -> str:
    get = row.get if hasattr(row, "get") else lambda k, d="": d
    raw = "|".join(
        str(get(key, ""))
        for key in ["Severity", "Entity", "Period", "Problem", "Source"]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def prepare_action_table(action_table: pd.DataFrame) -> pd.DataFrame:
    if action_table is None or action_table.empty:
        cols = [
            "Issue ID", "Severity", "Entity", "Period", "Problem", "Current Value",
            "Previous Value", "Previous Rank", "Next Value", "Next Rank", "Top-N Cutoff",
            "Why Flagged", "What To Do", "Source",
        ]
        return pd.DataFrame(columns=cols)
    out = action_table.copy()
    out["Issue ID"] = out.apply(issue_id, axis=1)
    out["__sev"] = out["Severity"].map(SEVERITY_ORDER).fillna(99)
    out = out.sort_values(["__sev", "Entity", "Period"], kind="stable").drop(columns="__sev")
    return out.reset_index(drop=True)


def apply_resolutions(action_table: pd.DataFrame, resolutions: dict[str, dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    prepared = prepare_action_table(action_table)
    if prepared.empty:
        return prepared, prepared.copy()
    resolved_ids = set(resolutions or {})
    resolved = prepared[prepared["Issue ID"].isin(resolved_ids)].copy()
    unresolved = prepared[~prepared["Issue ID"].isin(resolved_ids)].copy()
    if not resolved.empty:
        resolved["Resolution"] = resolved["Issue ID"].map(lambda x: resolutions.get(x, {}).get("action", "Resolved"))
        resolved["Resolution Reason"] = resolved["Issue ID"].map(lambda x: resolutions.get(x, {}).get("reason", ""))
    return unresolved.reset_index(drop=True), resolved.reset_index(drop=True)


def filter_issues(df: pd.DataFrame, menu: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df.copy() if df is not None else pd.DataFrame()
    if menu == "Must Fix":
        return df[df["Severity"] == "MUST FIX"].copy()
    if menu == "Must Check":
        return df[df["Severity"] == "MUST CHECK"].copy()
    if menu == "Review":
        return df[(df["Severity"] == "REVIEW") & (df["Source"] != "Coverage start/end")].copy()
    if menu == "Top-N Risk":
        return df[df["Source"] == "Top-N risk"].copy()
    if menu == "Start / End Years":
        return df[df["Source"] == "Coverage start/end"].copy()
    return df.copy()


def entity_counts(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Entity", "Count", "Must Fix", "Must Check", "Review"])
    base = df.copy()
    base["Entity"] = base["Entity"].replace("", "Dataset / Structure").fillna("Dataset / Structure")
    rows = []
    for entity, group in base.groupby("Entity", sort=True):
        rows.append({
            "Entity": entity,
            "Count": int(len(group)),
            "Must Fix": int((group["Severity"] == "MUST FIX").sum()),
            "Must Check": int((group["Severity"] == "MUST CHECK").sum()),
            "Review": int((group["Severity"] == "REVIEW").sum()),
        })
    return pd.DataFrame(rows)


def clean_display_value(value) -> str:
    if value is None:
        return "Not available"
    try:
        if pd.isna(value):
            return "Not available"
    except Exception:
        pass
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.4g}"
    return str(value)


def add_ranking_context(action_table: pd.DataFrame, working_df: pd.DataFrame, ranking) -> pd.DataFrame:
    if action_table is None or action_table.empty or ranking is None:
        return action_table.copy() if action_table is not None else pd.DataFrame()
    out = action_table.copy()

    # Streamlit Cloud / recent pandas may preserve text columns as Arrow-backed
    # string arrays. These review fields intentionally mix numbers and blanks.
    context_columns = [
        "Current Rank", "Previous Value", "Previous Rank", "Next Value", "Next Rank", "Top-N Cutoff",
    ]
    for col in context_columns:
        if col not in out.columns:
            out[col] = pd.Series([None] * len(out), index=out.index, dtype="object")
        else:
            out[col] = out[col].astype("object")

    period_columns = [str(c) for c in ranking.ranks.columns]

    def _gap_bounds(label: str):
        label = str(label or "").strip()
        if label in period_columns:
            i = period_columns.index(label)
            return i, i
        if "→" in label:
            left, right = [x.strip() for x in label.split("→", 1)]
            if left in period_columns and right in period_columns:
                return period_columns.index(left), period_columns.index(right)
        return None, None

    for i, row in out.iterrows():
        entity = str(row.get("Entity", "")).strip()
        period = str(row.get("Period", "")).strip()
        if not entity:
            continue
        matches = working_df.index[working_df["Entity"].astype(str).str.strip().eq(entity)]
        if len(matches) != 1:
            continue
        idx = matches[0]
        start_i, end_i = _gap_bounds(period)
        if start_i is None:
            continue

        # Exact/current rank and cutoff use the first affected period.
        current_period = period_columns[start_i]
        raw_rank = ranking.ranks.at[idx, current_period]
        if not pd.isna(raw_rank):
            out.at[i, "Current Rank"] = int(raw_rank)
        if row.get("Top-N Cutoff", "") in ("", None) or pd.isna(row.get("Top-N Cutoff", None)):
            cutoff = ranking.cutoffs.get(current_period)
            if cutoff is not None:
                out.at[i, "Top-N Cutoff"] = cutoff

        # For gap cards, show the nearest numeric anchors outside the gap.
        if str(row.get("Problem", "")) == "Internal Gap":
            left_i = start_i - 1
            while left_i >= 0:
                v = pd.to_numeric(pd.Series([working_df.at[idx, period_columns[left_i]]]), errors="coerce").iloc[0]
                if not pd.isna(v):
                    out.at[i, "Previous Value"] = float(v)
                    rr = ranking.ranks.at[idx, period_columns[left_i]]
                    if not pd.isna(rr):
                        out.at[i, "Previous Rank"] = int(rr)
                    break
                left_i -= 1

            right_i = end_i + 1
            while right_i < len(period_columns):
                v = pd.to_numeric(pd.Series([working_df.at[idx, period_columns[right_i]]]), errors="coerce").iloc[0]
                if not pd.isna(v):
                    out.at[i, "Next Value"] = float(v)
                    rr = ranking.ranks.at[idx, period_columns[right_i]]
                    if not pd.isna(rr):
                        out.at[i, "Next Rank"] = int(rr)
                    break
                right_i += 1

    return out

