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
    out = (
        findings_df.groupby(["Severity", "Category"], dropna=False)
        .size()
        .reset_index(name="Count")
    )
    out["__order"] = out["Severity"].map(severity_rank).fillna(99)
    return (
        out.sort_values(["__order", "Count", "Category"], ascending=[True, False, True])
        .drop(columns="__order")
        .reset_index(drop=True)
    )
