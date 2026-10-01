import pandas as pd

from modules.error_checker import CheckerConfig, run_core_checks


def categories(result):
    return result.findings_frame()["Category"].tolist()


def severities_for(result, category):
    frame = result.findings_frame()
    return frame.loc[frame["Category"] == category, "Severity"].tolist()


def test_clean_annual_dataset_has_no_findings():
    df = pd.DataFrame({
        "Entity": ["A", "B"],
        "1950": [10, 8],
        "1951": [11, 9],
        "1952": [12, 10],
    })
    result = run_core_checks(df)
    assert result.findings_frame().empty
    assert len(result.completeness) == 2


def test_internal_gap_is_review_and_fixable():
    df = pd.DataFrame({"Entity": ["A"], "1950": [10], "1951": [None], "1952": [14]})
    result = run_core_checks(df)
    frame = result.findings_frame()
    row = frame.loc[frame["Category"] == "Internal Gap"].iloc[0]
    assert row["Severity"] == "REVIEW"
    assert bool(row["Fixable"]) is True


def test_leading_and_trailing_blanks_are_not_internal_gaps():
    df = pd.DataFrame({
        "Entity": ["A"],
        "1950": [None], "1951": [10], "1952": [11], "1953": [None],
    })
    result = run_core_checks(df)
    assert "Internal Gap" not in categories(result)
    assert result.completeness.iloc[0]["Missing"] == 2


def test_non_numeric_is_must_fix():
    df = pd.DataFrame({"Entity": ["A"], "1950": [10], "1951": ["bad"]})
    result = run_core_checks(df)
    assert "MUST FIX" in severities_for(result, "Non-Numeric Value")


def test_duplicate_entity_and_row_are_must_fix():
    df = pd.DataFrame({"Entity": ["A", "A"], "1950": [10, 10], "1951": [11, 11]})
    result = run_core_checks(df)
    assert "Duplicate Entity" in categories(result)
    assert "Duplicate Row" in categories(result)


def test_missing_period_is_must_check():
    df = pd.DataFrame({"Entity": ["A"], "1950": [10], "1952": [12]})
    result = run_core_checks(df)
    frame = result.findings_frame()
    row = frame.loc[frame["Category"] == "Missing Period"].iloc[0]
    assert row["Period"] == "1951"
    assert row["Severity"] == "MUST CHECK"


def test_repeated_nonzero_regular_data_is_review():
    df = pd.DataFrame({"Entity": ["A"], "1950": [10], "1951": [10], "1952": [11]})
    result = run_core_checks(df, CheckerConfig(repeated_threshold=2))
    assert "Repeated Consecutive Value" in categories(result)


def test_repeated_nonzero_cumulative_not_flagged_but_decrease_is():
    df = pd.DataFrame({"Entity": ["A"], "1950": [10], "1951": [10], "1952": [9]})
    result = run_core_checks(df, CheckerConfig(data_mode="Cumulative Totals", repeated_threshold=2))
    assert "Repeated Consecutive Value" not in categories(result)
    assert "Cumulative Value Decreased" in categories(result)


def test_zero_run_is_review():
    df = pd.DataFrame({"Entity": ["A"], "1950": [0], "1951": [0], "1952": [1]})
    result = run_core_checks(df, CheckerConfig(repeated_threshold=2))
    assert "Zero Run" in categories(result)


def test_negative_is_review():
    df = pd.DataFrame({"Entity": ["A"], "1950": [-1], "1951": [2]})
    result = run_core_checks(df)
    assert "Negative Value" in categories(result)


def test_suspicious_jump_is_review():
    df = pd.DataFrame({"Entity": ["A"], "1950": [10], "1951": [100]})
    result = run_core_checks(df, CheckerConfig(suspicious_jump_threshold=500))
    assert "Suspicious Jump" in categories(result)


def test_monthly_missing_period_detection():
    df = pd.DataFrame({"Entity": ["A"], "2024-01": [1], "2024-03": [3]})
    result = run_core_checks(df)
    frame = result.findings_frame()
    assert "2024-02" in frame.loc[frame["Category"] == "Missing Period", "Period"].tolist()


def test_quarterly_missing_period_detection():
    df = pd.DataFrame({"Entity": ["A"], "2024 Q1": [1], "2024 Q3": [3]})
    result = run_core_checks(df)
    frame = result.findings_frame()
    assert "2024 Q2" in frame.loc[frame["Category"] == "Missing Period", "Period"].tolist()
