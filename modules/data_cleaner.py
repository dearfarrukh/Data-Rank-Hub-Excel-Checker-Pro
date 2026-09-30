from __future__ import annotations

from typing import Any

import pandas as pd

from modules.orientation import parse_period


def is_true_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def get_period_columns(df: pd.DataFrame) -> list:
    """Return columns that are recognized as annual/monthly/quarterly periods."""
    return [col for col in df.columns if col != "Entity" and parse_period(col) is not None]


def numeric_period_matrix(df: pd.DataFrame, period_columns: list) -> pd.DataFrame:
    if not period_columns:
        return pd.DataFrame(index=df.index)
    return df[period_columns].apply(pd.to_numeric, errors="coerce")


def classify_cell(value: Any) -> tuple[str, float | None]:
    if is_true_blank(value):
        return "blank", None
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "invalid", None
    return "number", float(numeric)
