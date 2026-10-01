from __future__ import annotations

import hashlib

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
    if menu in {"Start / End Years", "Start / End Review"}:
        return df[df["Source"] == "Coverage start/end"].copy()
    if menu == "All Errors":
        # Start/end coverage candidates are classification/review items, not errors.
        return df[df["Source"] != "Coverage start/end"].copy()
    return df.copy()



def ever_top_n_entities(working_df: pd.DataFrame, ranking, top_n: int) -> set[str]:
    """Return entities that achieved rank <= Top-N in at least one observed period.

    This is intentionally an entity-level membership rule: once an entity has entered
    the selected Top-N at any point in the dataset, all of that entity's review issues
    belong in the main Top-N workspace (including start/end coverage reviews).
    """
    if working_df is None or working_df.empty or ranking is None:
        return set()

    out: set[str] = set()
    for idx in working_df.index:
        entity = str(working_df.at[idx, "Entity"]).strip() if "Entity" in working_df.columns else ""
        if not entity:
            continue
        try:
            row_ranks = pd.to_numeric(ranking.ranks.loc[idx], errors="coerce")
        except Exception:
            continue
        if (row_ranks <= int(top_n)).fillna(False).any():
            out.add(entity)
    return out


def filter_top_n_relevant_issues(
    df: pd.DataFrame,
    working_df: pd.DataFrame,
    ranking,
    top_n: int,
) -> pd.DataFrame:
    """Return ALL issues for entities that ever entered the selected Top-N.

    User-facing rule:
    - If an entity ranked inside the selected Top-N in any observed period, none of
      that entity's issues are pushed to Advanced.
    - This includes start/end coverage reviews, jumps, repeats, zero runs, missing
      values, invalid values, and Top-N risk rows.
    - Dataset-wide structural issues stay visible because they can invalidate the
      selected ranking regardless of entity membership.
    - Issues belonging only to entities that never entered the selected Top-N are
      left for the Advanced / other-countries view.
    """
    if df is None or df.empty:
        return df.copy() if df is not None else pd.DataFrame()

    eligible = ever_top_n_entities(working_df, ranking, top_n)
    global_problems = {
        "Missing Entity Column", "Blank Entity Name", "Duplicate Period",
        "Periods Out of Order", "No Period Columns", "Missing Period",
    }

    keep: list[bool] = []
    for _, row in df.iterrows():
        entity = str(row.get("Entity", "")).strip()
        problem = str(row.get("Problem", ""))
        if not entity or entity == "Dataset / Structure" or problem in global_problems:
            keep.append(True)
        else:
            keep.append(entity in eligible)

    return df.loc[keep].reset_index(drop=True)


def filter_other_country_issues(
    df: pd.DataFrame,
    working_df: pd.DataFrame,
    ranking,
    top_n: int,
) -> pd.DataFrame:
    """Return unresolved issues for entities that never entered selected Top-N."""
    if df is None or df.empty:
        return df.copy() if df is not None else pd.DataFrame()
    eligible = ever_top_n_entities(working_df, ranking, top_n)
    keep: list[bool] = []
    for _, row in df.iterrows():
        entity = str(row.get("Entity", "")).strip()
        # Dataset/structural issues belong to the main workspace, never Advanced.
        keep.append(bool(entity and entity != "Dataset / Structure" and entity not in eligible))
    return df.loc[keep].reset_index(drop=True)


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


def _period_span(label: str, period_columns: list[str]) -> tuple[int | None, int | None]:
    label = str(label or "").strip()
    if label in period_columns:
        i = period_columns.index(label)
        return i, i
    if "→" in label:
        left, right = [x.strip() for x in label.split("→", 1)]
        if left in period_columns and right in period_columns:
            return period_columns.index(left), period_columns.index(right)
    return None, None


def remove_safe_fill_reviews(
    action_table: pd.DataFrame,
    safe_fill_candidates: pd.DataFrame,
    period_columns: list,
) -> pd.DataFrame:
    """Remove REVIEW/Internal Gap rows that are fully covered by safe-fill cells.

    Safe-fill candidates are a separate workflow, not an error/review count. A gap
    remains in Review when only part of the gap is safe or no safe candidate exists.
    """
    if action_table is None or action_table.empty or safe_fill_candidates is None or safe_fill_candidates.empty:
        return action_table.copy() if action_table is not None else pd.DataFrame()

    period_labels = [str(c) for c in period_columns]
    safe_cells = {
        (str(r.get("Entity", "")).strip(), str(r.get("Period", "")).strip())
        for _, r in safe_fill_candidates.iterrows()
    }

    keep = []
    for _, row in action_table.iterrows():
        if not (
            str(row.get("Severity", "")) == "REVIEW"
            and str(row.get("Problem", "")) == "Internal Gap"
            and str(row.get("Source", "")) == "Core check"
        ):
            keep.append(True)
            continue

        entity = str(row.get("Entity", "")).strip()
        start_i, end_i = _period_span(str(row.get("Period", "")), period_labels)
        if start_i is None:
            keep.append(True)
            continue
        affected = [(entity, period_labels[i]) for i in range(start_i, end_i + 1)]
        keep.append(not affected or not all(cell in safe_cells for cell in affected))

    return action_table.loc[keep].reset_index(drop=True)


def add_ranking_context(action_table: pd.DataFrame, working_df: pd.DataFrame, ranking) -> pd.DataFrame:
    if action_table is None or action_table.empty or ranking is None:
        return action_table.copy() if action_table is not None else pd.DataFrame()
    out = action_table.copy()

    # Streamlit Cloud / recent pandas may preserve text columns as Arrow-backed
    # string arrays. These fields intentionally mix numbers and blanks.
    context_columns = [
        "Current Rank", "Previous Value", "Previous Rank", "Next Value", "Next Rank", "Top-N Cutoff",
    ]
    for col in context_columns:
        if col not in out.columns:
            out[col] = pd.Series([None] * len(out), index=out.index, dtype="object")
        else:
            out[col] = out[col].astype("object")

    period_columns = [str(c) for c in ranking.ranks.columns]

    def _numeric_at(idx, pidx):
        if pidx is None or pidx < 0 or pidx >= len(period_columns):
            return None
        value = pd.to_numeric(pd.Series([working_df.at[idx, period_columns[pidx]]]), errors="coerce").iloc[0]
        return None if pd.isna(value) else float(value)

    def _rank_at(idx, pidx):
        if pidx is None or pidx < 0 or pidx >= len(period_columns):
            return None
        raw = ranking.ranks.at[idx, period_columns[pidx]]
        return None if pd.isna(raw) else int(raw)

    for i, row in out.iterrows():
        entity = str(row.get("Entity", "")).strip()
        if not entity:
            continue
        matches = working_df.index[working_df["Entity"].astype(str).str.strip().eq(entity)]
        if len(matches) != 1:
            continue
        idx = matches[0]
        start_i, end_i = _period_span(str(row.get("Period", "")), period_columns)
        if start_i is None:
            continue

        problem = str(row.get("Problem", ""))
        source = str(row.get("Source", ""))

        # For transitions like 1974→1975, the finding's current value belongs to
        # the ending period. For ranges/repeated runs it is clearer to anchor the
        # card to the first affected period.
        current_i = end_i if problem in {"Suspicious Jump", "Suspicious Drop", "Cumulative Value Decreased"} else start_i
        current_period = period_columns[current_i]

        raw_rank = _rank_at(idx, current_i)
        if raw_rank is not None:
            out.at[i, "Current Rank"] = raw_rank

        existing_cutoff = row.get("Top-N Cutoff", None)
        empty_cutoff = existing_cutoff in ("", None)
        try:
            empty_cutoff = empty_cutoff or pd.isna(existing_cutoff)
        except Exception:
            pass
        if empty_cutoff:
            cutoff = ranking.cutoffs.get(current_period)
            if cutoff is not None:
                out.at[i, "Top-N Cutoff"] = cutoff

        # Top-N risk rows already carry carefully chosen nearest anchors.
        if source == "Top-N risk":
            continue

        if problem == "Internal Gap":
            left_i = start_i - 1
            while left_i >= 0 and _numeric_at(idx, left_i) is None:
                left_i -= 1
            right_i = end_i + 1
            while right_i < len(period_columns) and _numeric_at(idx, right_i) is None:
                right_i += 1
        else:
            left_i = start_i - 1
            right_i = end_i + 1

        prev_value = _numeric_at(idx, left_i)
        next_value = _numeric_at(idx, right_i)
        prev_rank = _rank_at(idx, left_i)
        next_rank = _rank_at(idx, right_i)

        if prev_value is not None:
            out.at[i, "Previous Value"] = prev_value
        if prev_rank is not None:
            out.at[i, "Previous Rank"] = prev_rank
        if next_value is not None:
            out.at[i, "Next Value"] = next_value
        if next_rank is not None:
            out.at[i, "Next Rank"] = next_rank

    return out
