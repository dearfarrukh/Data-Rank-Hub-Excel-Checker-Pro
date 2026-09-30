import pandas as pd

from modules.orientation import (
    detect_orientation,
    normalize_to_checker,
    parse_period,
    restore_original_orientation,
)


def test_annual_period_parser():
    token = parse_period("1950")
    assert token is not None
    assert token.frequency == "Annual"
    assert token.key == (1950, 0, 0)


def test_monthly_period_parser():
    assert parse_period("2024-03").frequency == "Monthly"
    assert parse_period("Mar 2024").key == (2024, 3, 0)


def test_quarterly_period_parser():
    assert parse_period("2024 Q2").frequency == "Quarterly"
    assert parse_period("Q2 2024").key == (2024, 0, 2)


def test_detect_checker_orientation():
    df = pd.DataFrame({
        "Country": ["USA", "China"],
        "1950": [10, 20],
        "1951": [11, 21],
        "1952": [12, 22],
    })
    result = detect_orientation(df)
    assert result.orientation == "checker"
    assert result.entity_column == "Country"
    assert result.frequency == "Annual"


def test_detect_alienart_orientation_and_normalize():
    df = pd.DataFrame({
        "Year": [1950, 1951, 1952],
        "USA": [10, 11, 12],
        "China": [20, 21, 22],
    })
    result = detect_orientation(df)
    assert result.orientation == "alienart"
    assert result.period_column == "Year"

    normalized = normalize_to_checker(df, result)
    assert list(normalized.columns) == ["Entity", "1950", "1951", "1952"]
    assert normalized.loc[0, "Entity"] == "USA"
    assert normalized.loc[1, "1952"] == 22


def test_round_trip_alienart():
    original = pd.DataFrame({
        "Year": [1950, 1951],
        "USA": [10, 11],
        "China": [20, 21],
    })
    result = detect_orientation(original)
    normalized = normalize_to_checker(original, result)
    restored = restore_original_orientation(normalized, result, original)
    assert list(restored.columns) == ["Year", "USA", "China"]
    assert restored.to_dict("records") == [
        {"Year": "1950", "USA": 10, "China": 20},
        {"Year": "1951", "USA": 11, "China": 21},
    ]


def test_detect_monthly_checker():
    df = pd.DataFrame({
        "State": ["NY", "CA"],
        "Jan 2024": [1, 2],
        "Feb 2024": [3, 4],
        "Mar 2024": [5, 6],
    })
    result = detect_orientation(df)
    assert result.orientation == "checker"
    assert result.frequency == "Monthly"
