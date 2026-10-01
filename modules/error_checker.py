from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from modules.data_cleaner import classify_cell, get_period_columns, numeric_period_matrix
from modules.gap_checker import compress_missing_ranges, expected_periods
from modules.jump_checker import repeated_runs
from modules.orientation import parse_period


@dataclass
class CheckerConfig:
    data_mode: str = "Regular Data"
    repeated_threshold: int = 2
    suspicious_jump_threshold: float = 500.0
    check_negative_values: bool = True


@dataclass
class Finding:
    category: str
    severity: str
    entity: str = ""
    period: str = ""
    value: object = ""
    details: str = ""
    suggestion: str = ""
    fixable: bool = False

    def to_dict(self) -> dict:
        return {
            "Category": self.category,
            "Severity": self.severity,
            "Entity": self.entity,
            "Period": self.period,
            "Value": self.value,
            "Details": self.details,
            "Suggestion": self.suggestion,
            "Fixable": self.fixable,
        }


@dataclass
class CheckResult:
    findings: list[Finding]
    period_columns: list
    numeric_matrix: pd.DataFrame
    completeness: pd.DataFrame

    def findings_frame(self) -> pd.DataFrame:
        columns = ["Category", "Severity", "Entity", "Period", "Value", "Details", "Suggestion", "Fixable"]
        if not self.findings:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame([finding.to_dict() for finding in self.findings], columns=columns)


def _add(findings: list[Finding], *args, **kwargs) -> None:
    findings.append(Finding(*args, **kwargs))


def _structure_checks(df: pd.DataFrame, findings: list[Finding]) -> None:
    if "Entity" not in df.columns:
        _add(findings, "Missing Entity Column", "MUST FIX", details="Internal checker view has no Entity column.")
        return

    blank_mask = df["Entity"].isna() | df["Entity"].astype(str).str.strip().eq("")
    for index in df.index[blank_mask]:
        _add(
            findings, "Blank Entity Name", "MUST FIX",
            details=f"Blank entity name on data row {index + 2}.",
            suggestion="Enter the correct entity name or remove the empty row.",
        )

    entity_clean = df["Entity"].fillna("").astype(str).str.strip()
    duplicate_mask = entity_clean.ne("") & entity_clean.duplicated(keep=False)
    if duplicate_mask.any():
        duplicate_df = df.loc[duplicate_mask].copy()
        duplicate_df["__entity_clean__"] = entity_clean[duplicate_mask]
        for entity_name, group in duplicate_df.groupby("__entity_clean__", sort=False):
            rows = [int(index) + 2 for index in group.index]
            _add(
                findings, "Duplicate Entity", "MUST FIX", entity=entity_name,
                details=f"Entity appears more than once on data rows {rows}.",
                suggestion="Review whether these rows should be merged, renamed, or removed.",
            )

    full_duplicate_mask = df.duplicated(keep=False)
    for index in df.index[full_duplicate_mask]:
        _add(
            findings, "Duplicate Row", "MUST FIX",
            entity=str(df.loc[index, "Entity"]) if "Entity" in df.columns else "",
            details=f"Entire row is duplicated on data row {index + 2}.",
            suggestion="Remove the duplicate row after confirming which copy to keep.",
        )


def _period_checks(period_columns: list, findings: list[Finding]) -> None:
    parsed = [(col, parse_period(col)) for col in period_columns]
    parsed = [(col, token) for col, token in parsed if token is not None]

    key_map: dict[tuple[int, int, int], list[str]] = {}
    for col, token in parsed:
        key_map.setdefault(token.key, []).append(str(col))

    for labels in key_map.values():
        if len(labels) > 1:
            _add(
                findings, "Duplicate Period", "MUST FIX", period=" / ".join(labels),
                details="The same time period appears more than once.",
                suggestion="Keep one period column and reconcile any conflicting values.",
            )

    keys = [token.key for _, token in parsed]
    if keys and keys != sorted(keys):
        _add(
            findings, "Periods Out of Order", "MUST FIX",
            details="Time columns are not arranged chronologically.",
            suggestion="Reorder period columns before final export.",
        )

    existing_keys = set(keys)
    for key, label in expected_periods(period_columns):
        if key not in existing_keys:
            _add(
                findings, "Missing Period", "MUST CHECK", period=label,
                details=f"{label} is missing from the time-series columns.",
                suggestion="Confirm whether this period should exist in the dataset.",
            )


def _cell_and_gap_checks(df: pd.DataFrame, period_columns: list, findings: list[Finding]) -> None:
    for row_index, row in df.iterrows():
        entity = str(row.get("Entity", "")).strip()
        converted: list[tuple[str, float | None, object]] = []

        for column in period_columns:
            raw = row[column]
            kind, numeric = classify_cell(raw)
            converted.append((kind, numeric, raw))

        valid_positions = [i for i, item in enumerate(converted) if item[0] == "number"]

        for i, (kind, _, raw) in enumerate(converted):
            if kind == "invalid":
                _add(
                    findings, "Non-Numeric Value", "MUST FIX",
                    entity=entity, period=str(period_columns[i]), value=str(raw),
                    details=f"Expected a numeric value on data row {row_index + 2}.",
                    suggestion="Replace it with the correct number or clear the cell if truly missing.",
                )

        if not valid_positions:
            continue

        first_valid, last_valid = valid_positions[0], valid_positions[-1]
        missing_inside = [
            i for i in range(first_valid + 1, last_valid)
            if converted[i][0] == "blank"
        ]
        for gap in compress_missing_ranges(missing_inside, period_columns):
            _add(
                findings, "Internal Gap", "REVIEW",
                entity=entity, period=gap.label,
                details=f"{gap.length} missing period(s) inside the series on data row {row_index + 2}.",
                suggestion="Review the gap. If both anchors are valid and no Top-N risk is detected, Safe Series Fill may be used.",
                fixable=True,
            )


def _number_checks(
    df: pd.DataFrame,
    period_columns: list,
    numeric_matrix: pd.DataFrame,
    findings: list[Finding],
    config: CheckerConfig,
) -> None:
    for pos, row_index in enumerate(df.index):
        entity = str(df.loc[row_index, "Entity"]).strip()
        row_values = numeric_matrix.loc[row_index].tolist()

        for run in repeated_runs(row_values, int(config.repeated_threshold)):
            start_col = str(period_columns[run["start_index"]])
            end_col = str(period_columns[run["end_index"]])
            period_label = start_col if start_col == end_col else f"{start_col} → {end_col}"
            value = run["value"]

            if float(value) == 0:
                _add(
                    findings, "Zero Run", "REVIEW",
                    entity=entity, period=period_label, value=value,
                    details=f"Zero appears in {run['length']} consecutive periods.",
                    suggestion="Check whether zeros are real observations or placeholders for missing data.",
                )
            elif config.data_mode == "Regular Data":
                _add(
                    findings, "Repeated Consecutive Value", "REVIEW",
                    entity=entity, period=period_label, value=value,
                    details=f"The same non-zero value appears in {run['length']} consecutive periods.",
                    suggestion="Check whether this is genuine or an accidental forward-fill.",
                )

        previous_numeric = None
        previous_column = None
        for column, raw_numeric in zip(period_columns, row_values):
            if pd.isna(raw_numeric):
                continue

            current_numeric = float(raw_numeric)
            if config.check_negative_values and current_numeric < 0:
                _add(
                    findings, "Negative Value", "REVIEW",
                    entity=entity, period=str(column), value=current_numeric,
                    details=f"Negative numeric value on data row {row_index + 2}.",
                    suggestion="Confirm whether negative values are valid for this dataset.",
                )

            if previous_numeric is not None and previous_numeric != 0:
                change_percent = abs((current_numeric - previous_numeric) / abs(previous_numeric) * 100)
                if change_percent > float(config.suspicious_jump_threshold):
                    _add(
                        findings, "Suspicious Jump", "REVIEW",
                        entity=entity, period=f"{previous_column} → {column}", value=current_numeric,
                        details=(
                            f"Value changed by {change_percent:,.1f}% from "
                            f"{previous_numeric:,.6g} to {current_numeric:,.6g}."
                        ),
                        suggestion="Review this large change against the source or historical context.",
                    )

            if (
                config.data_mode == "Cumulative Totals"
                and previous_numeric is not None
                and current_numeric < previous_numeric
            ):
                _add(
                    findings, "Cumulative Value Decreased", "MUST FIX",
                    entity=entity, period=f"{previous_column} → {column}", value=current_numeric,
                    details=(
                        f"Cumulative value fell from {previous_numeric:,.6g} "
                        f"to {current_numeric:,.6g}."
                    ),
                    suggestion="Verify the source because cumulative totals normally should not decrease.",
                )

            previous_numeric = current_numeric
            previous_column = str(column)


def _build_completeness(df: pd.DataFrame, period_columns: list, numeric_matrix: pd.DataFrame) -> pd.DataFrame:
    rows = []
    total = len(period_columns)
    for row_index in df.index:
        entity = str(df.loc[row_index, "Entity"]).strip()
        numeric_values = numeric_matrix.loc[row_index].tolist()
        valid_positions = [i for i, value in enumerate(numeric_values) if not pd.isna(value)]
        valid_count = len(valid_positions)
        rows.append({
            "Entity": entity,
            "Completeness %": round(valid_count / total * 100, 1) if total else 0.0,
            "Observations": valid_count,
            "Missing": total - valid_count,
            "First Available": str(period_columns[valid_positions[0]]) if valid_positions else "",
            "Last Available": str(period_columns[valid_positions[-1]]) if valid_positions else "",
        })
    return pd.DataFrame(rows)


def run_core_checks(df: pd.DataFrame, config: CheckerConfig | None = None) -> CheckResult:
    config = config or CheckerConfig()
    findings: list[Finding] = []

    _structure_checks(df, findings)
    period_columns = get_period_columns(df)

    if not period_columns:
        _add(
            findings, "No Period Columns", "MUST FIX",
            details="No annual, monthly, or quarterly period columns were recognized.",
            suggestion="Check the orientation or period labels.",
        )
        return CheckResult(findings, [], pd.DataFrame(index=df.index), pd.DataFrame())

    _period_checks(period_columns, findings)
    numeric_matrix = numeric_period_matrix(df, period_columns)
    _cell_and_gap_checks(df, period_columns, findings)
    _number_checks(df, period_columns, numeric_matrix, findings, config)
    completeness = _build_completeness(df, period_columns, numeric_matrix)

    return CheckResult(findings, period_columns, numeric_matrix, completeness)
