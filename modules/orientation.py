from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd


MONTH_NAMES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

ENTITY_CANDIDATES = ["country", "state", "entity", "city", "company", "name", "region"]
PERIOD_CANDIDATES = ["year", "date", "period", "time", "month", "quarter"]


@dataclass(frozen=True)
class PeriodToken:
    key: tuple[int, int, int]
    label: str
    frequency: str


@dataclass
class OrientationResult:
    orientation: str
    confidence: float
    reason: str
    entity_column: str | None
    period_column: str | None
    frequency: str | None
    period_count: int
    entity_count: int


def _clean_text(value: Any) -> str:
    return str(value).strip()


def parse_period(value: Any) -> PeriodToken | None:
    """Parse annual, monthly, and quarterly period labels used by Data Rank Hub."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    # Excel often exposes year headers as numeric values such as 1950 or 1950.0.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value).is_integer():
            year = int(value)
            if 1000 <= year <= 3000:
                return PeriodToken((year, 0, 0), str(year), "Annual")

    text = _clean_text(value)
    if not text:
        return None

    # Annual
    if re.fullmatch(r"(?:18|19|20|21)\d{2}", text):
        year = int(text)
        return PeriodToken((year, 0, 0), text, "Annual")

    # YYYY-MM / YYYY/MM
    m = re.fullmatch(r"((?:18|19|20|21)\d{2})[-/](0?[1-9]|1[0-2])", text)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        return PeriodToken((year, month, 0), f"{year:04d}-{month:02d}", "Monthly")

    # MM-YYYY / MM/YYYY
    m = re.fullmatch(r"(0?[1-9]|1[0-2])[-/]((?:18|19|20|21)\d{2})", text)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        return PeriodToken((year, month, 0), f"{year:04d}-{month:02d}", "Monthly")

    # Month name + year or year + month name
    m = re.fullmatch(r"([A-Za-z]+)[\s_-]+((?:18|19|20|21)\d{2})", text)
    if m and m.group(1).lower() in MONTH_NAMES:
        month, year = MONTH_NAMES[m.group(1).lower()], int(m.group(2))
        return PeriodToken((year, month, 0), f"{year:04d}-{month:02d}", "Monthly")

    m = re.fullmatch(r"((?:18|19|20|21)\d{2})[\s_-]+([A-Za-z]+)", text)
    if m and m.group(2).lower() in MONTH_NAMES:
        year, month = int(m.group(1)), MONTH_NAMES[m.group(2).lower()]
        return PeriodToken((year, month, 0), f"{year:04d}-{month:02d}", "Monthly")

    # 2024 Q1 / Q1 2024 / 2024-Q1
    m = re.fullmatch(r"((?:18|19|20|21)\d{2})[\s_-]*Q([1-4])", text, flags=re.I)
    if m:
        year, quarter = int(m.group(1)), int(m.group(2))
        return PeriodToken((year, 0, quarter), f"{year:04d} Q{quarter}", "Quarterly")

    m = re.fullmatch(r"Q([1-4])[\s_-]*((?:18|19|20|21)\d{2})", text, flags=re.I)
    if m:
        quarter, year = int(m.group(1)), int(m.group(2))
        return PeriodToken((year, 0, quarter), f"{year:04d} Q{quarter}", "Quarterly")

    return None


def _most_common_frequency(tokens: Iterable[PeriodToken]) -> str | None:
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token.frequency] = counts.get(token.frequency, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda x: x[1])[0]


def detect_entity_column(df: pd.DataFrame) -> str | None:
    lowered = {str(col).strip().lower(): col for col in df.columns}
    for candidate in ENTITY_CANDIDATES:
        if candidate in lowered:
            return str(lowered[candidate])

    # Fallback: first mostly-text column that is not itself a period label.
    for col in df.columns:
        series = df[col].dropna()
        if series.empty:
            continue
        parsed_share = series.map(lambda x: parse_period(x) is not None).mean()
        text_share = series.map(lambda x: isinstance(x, str) and bool(x.strip())).mean()
        if parsed_share < 0.25 and text_share >= 0.60:
            return str(col)
    return str(df.columns[0]) if len(df.columns) else None


def _period_column_score(series: pd.Series) -> float:
    nonblank = series.dropna()
    if nonblank.empty:
        return 0.0
    parsed = nonblank.map(lambda x: parse_period(x) is not None)
    return float(parsed.mean())


def detect_period_column(df: pd.DataFrame) -> tuple[str | None, float]:
    lowered = {str(col).strip().lower(): str(col) for col in df.columns}

    # Prefer a semantically named column if it contains period values.
    for candidate in PERIOD_CANDIDATES:
        if candidate in lowered:
            col = lowered[candidate]
            score = _period_column_score(df[col])
            if score >= 0.60:
                return col, score

    best_col, best_score = None, 0.0
    for col in df.columns:
        score = _period_column_score(df[col])
        if score > best_score:
            best_col, best_score = str(col), score
    return best_col, best_score


def detect_orientation(df: pd.DataFrame) -> OrientationResult:
    if df is None or df.empty or len(df.columns) < 2:
        return OrientationResult(
            orientation="unknown", confidence=0.0,
            reason="Not enough rows/columns to detect a ranking-table orientation.",
            entity_column=None, period_column=None, frequency=None,
            period_count=0, entity_count=max(0, len(df) if df is not None else 0),
        )

    header_tokens = [(str(col), parse_period(col)) for col in df.columns]
    parsed_headers = [(col, token) for col, token in header_tokens if token is not None]
    header_period_ratio = len(parsed_headers) / max(1, len(df.columns) - 1)

    period_col, period_value_score = detect_period_column(df)

    # Checker format: entity rows, period columns.
    # Require at least two period headers to avoid mistaking a normal table for a time matrix.
    if len(parsed_headers) >= 2 and header_period_ratio >= 0.50:
        entity_col = detect_entity_column(df)
        tokens = [token for _, token in parsed_headers if token is not None]
        return OrientationResult(
            orientation="checker",
            confidence=min(0.99, 0.70 + 0.29 * header_period_ratio),
            reason=f"Detected {len(parsed_headers)} period columns across the table header.",
            entity_column=entity_col,
            period_column=None,
            frequency=_most_common_frequency(tokens),
            period_count=len(parsed_headers),
            entity_count=len(df),
        )

    # AlienArt format: period rows, entity columns.
    if period_col is not None and period_value_score >= 0.60:
        tokens = [parse_period(v) for v in df[period_col].dropna()]
        tokens = [t for t in tokens if t is not None]
        entity_count = max(0, len(df.columns) - 1)
        return OrientationResult(
            orientation="alienart",
            confidence=min(0.99, 0.70 + 0.29 * period_value_score),
            reason=f"Column '{period_col}' contains period values in {period_value_score:.0%} of nonblank rows.",
            entity_column=None,
            period_column=period_col,
            frequency=_most_common_frequency(tokens),
            period_count=len(tokens),
            entity_count=entity_count,
        )

    return OrientationResult(
        orientation="unknown", confidence=max(header_period_ratio, period_value_score),
        reason="The table does not strongly match either supported ranking orientation.",
        entity_column=detect_entity_column(df), period_column=period_col,
        frequency=None, period_count=0, entity_count=0,
    )


def normalize_to_checker(df: pd.DataFrame, result: OrientationResult) -> pd.DataFrame:
    """Return internal format: Entity | Period 1 | Period 2 | ..."""
    if result.orientation == "checker":
        out = df.copy()
        entity_col = result.entity_column or str(out.columns[0])
        if entity_col != "Entity":
            out = out.rename(columns={entity_col: "Entity"})
        return out

    if result.orientation == "alienart":
        period_col = result.period_column
        if not period_col or period_col not in df.columns:
            raise ValueError("AlienArt orientation detected without a valid period column.")

        working = df.copy()
        period_labels = []
        for value in working[period_col].tolist():
            token = parse_period(value)
            period_labels.append(token.label if token else _clean_text(value))

        entity_cols = [col for col in working.columns if str(col) != str(period_col)]
        records = []
        for entity_col in entity_cols:
            row = {"Entity": str(entity_col).strip()}
            for idx, period_label in enumerate(period_labels):
                row[period_label] = working.iloc[idx][entity_col]
            records.append(row)
        return pd.DataFrame(records)

    raise ValueError("Unable to normalize: orientation is unknown.")


def restore_original_orientation(
    normalized_df: pd.DataFrame,
    result: OrientationResult,
    original_df: pd.DataFrame,
) -> pd.DataFrame:
    """Stage-1 round-trip helper used later by corrected export."""
    if result.orientation == "checker":
        out = normalized_df.copy()
        original_entity_col = result.entity_column or str(original_df.columns[0])
        if original_entity_col != "Entity":
            out = out.rename(columns={"Entity": original_entity_col})
        ordered = [c for c in original_df.columns if c in out.columns]
        extras = [c for c in out.columns if c not in ordered]
        return out[ordered + extras]

    if result.orientation == "alienart":
        period_col = result.period_column or "Year"
        period_cols = [c for c in normalized_df.columns if c != "Entity"]
        rows = []
        for period in period_cols:
            row = {period_col: period}
            for _, entity_row in normalized_df.iterrows():
                row[str(entity_row["Entity"])] = entity_row[period]
            rows.append(row)
        out = pd.DataFrame(rows)
        original_order = [str(c) for c in original_df.columns]
        ordered = [c for c in original_order if c in out.columns]
        extras = [c for c in out.columns if c not in ordered]
        return out[ordered + extras]

    raise ValueError("Unable to restore: orientation is unknown.")
