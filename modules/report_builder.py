from __future__ import annotations

import pandas as pd


SEVERITY_ORDER = ["MUST FIX", "MUST CHECK", "REVIEW", "INFO"]


def severity_counts(findings_df: pd.DataFrame) -> dict[str, int]:
    counts = {severity: 0 for severity in SEVERITY_ORDER}
    if findings_df.empty or "Severity" not in findings_df.columns:
        return counts
    actual = findings_df["Severity"].value_counts().to_dict()
    for key, value in actual.items():
        counts[str(key)] = int(value)
    return counts


def final_status(findings_df: pd.DataFrame) -> str:
    counts = severity_counts(findings_df)
    if counts.get("MUST FIX", 0) or counts.get("MUST CHECK", 0):
        return "REVIEW NEEDED"
    return "READY"


def category_summary(findings_df: pd.DataFrame) -> pd.DataFrame:
    if findings_df.empty:
        return pd.DataFrame(columns=["Severity", "Category", "Count"])
    severity_rank = {name: i for i, name in enumerate(SEVERITY_ORDER)}
    out = findings_df.groupby(["Severity", "Category"], dropna=False).size().reset_index(name="Count")
    out["__order"] = out["Severity"].map(severity_rank).fillna(99)
    return out.sort_values(["__order", "Count", "Category"], ascending=[True, False, True]).drop(columns="__order").reset_index(drop=True)


def build_action_table(findings_df: pd.DataFrame, risk_table: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "Severity", "Entity", "Period", "Problem", "Current Value", "Previous Value", "Previous Rank",
        "Next Value", "Next Rank", "Top-N Cutoff", "Why Flagged", "What To Do", "Source",
    ]
    rows: list[dict] = []

    if not findings_df.empty:
        for _, item in findings_df.iterrows():
            rows.append({
                "Severity": item.get("Severity", ""),
                "Entity": item.get("Entity", ""),
                "Period": item.get("Period", ""),
                "Problem": item.get("Category", ""),
                "Current Value": item.get("Value", ""),
                "Previous Value": "",
                "Previous Rank": "",
                "Next Value": "",
                "Next Rank": "",
                "Top-N Cutoff": "",
                "Why Flagged": item.get("Details", ""),
                "What To Do": item.get("Suggestion", ""),
                "Source": "Core check",
            })

    if risk_table is not None and not risk_table.empty:
        for _, item in risk_table.iterrows():
            rows.append({
                "Severity": "MUST CHECK",
                "Entity": item.get("Entity", ""),
                "Period": item.get("Error Period", ""),
                "Problem": item.get("Problem Type", ""),
                "Current Value": item.get("Current Value", ""),
                "Previous Value": item.get("Previous Value", ""),
                "Previous Rank": item.get("Previous Rank", ""),
                "Next Value": item.get("Next Value", ""),
                "Next Rank": item.get("Next Rank", ""),
                "Top-N Cutoff": item.get("Top-N Cutoff", ""),
                "Why Flagged": item.get("Why Flagged", ""),
                "What To Do": item.get("What To Do", ""),
                "Source": "Top-N risk",
            })

    out = pd.DataFrame(rows, columns=columns)
    if out.empty:
        return out
    order = {name: i for i, name in enumerate(SEVERITY_ORDER)}
    out["__order"] = out["Severity"].map(order).fillna(99)
    return out.sort_values(["__order", "Entity", "Period"], kind="stable").drop(columns="__order").reset_index(drop=True)
