import pandas as pd

from modules.error_checker import run_core_checks
from modules.ranking_engine import (
    build_ranking_matrix,
    build_top_n_risk_table,
    classify_top_n_safety,
)


def test_ranks_are_calculated_per_period():
    matrix = pd.DataFrame({"1950": [100, 90, 80], "1951": [70, 120, 60]})
    result = build_ranking_matrix(matrix, top_n=2)
    assert int(result.ranks.loc[0, "1950"]) == 1
    assert int(result.ranks.loc[0, "1951"]) == 2
    assert result.cutoffs["1950"] == 90
    assert result.cutoffs["1951"] == 70


def test_internal_missing_near_top_n_is_flagged():
    df = pd.DataFrame({
        "Entity": ["A", "B", "C"],
        "1950": [100, 90, 80],
        "1951": [None, 95, 85],
        "1952": [110, 100, 90],
    })
    core = run_core_checks(df)
    risks, _, _ = build_top_n_risk_table(df, core.period_columns, core.numeric_matrix, top_n=2)
    assert "A" in risks["Entity"].tolist()
    row = risks.loc[risks["Entity"] == "A"].iloc[0]
    assert row["Previous Rank"] == 1
    assert row["Next Rank"] == 1
    assert row["Current Rank"] is None


def test_missing_far_from_top_n_is_not_flagged():
    df = pd.DataFrame({
        "Entity": ["A", "B", "C", "D", "E"],
        "1950": [100, 90, 80, 70, 10],
        "1951": [101, 91, 81, 71, None],
        "1952": [102, 92, 82, 72, 12],
    })
    core = run_core_checks(df)
    risks, _, _ = build_top_n_risk_table(df, core.period_columns, core.numeric_matrix, top_n=2, rank_margin=1)
    assert "E" not in risks["Entity"].tolist()


def test_local_only_logic_does_not_flag_distant_historical_top_n():
    df = pd.DataFrame({
        "Entity": ["A", "B", "C", "D"],
        "1950": [100, 90, 80, 70],
        "1951": [5, 95, 85, 75],
        "1952": [None, 100, 90, 80],
        "1953": [6, 105, 95, 85],
    })
    core = run_core_checks(df)
    risks, _, _ = build_top_n_risk_table(df, core.period_columns, core.numeric_matrix, top_n=2, rank_margin=1)
    assert "A" not in risks["Entity"].tolist()


def test_structural_must_fix_makes_top_n_no():
    df = pd.DataFrame({"Entity": ["A", "A"], "1950": [10, 9], "1951": [11, 10]})
    core = run_core_checks(df)
    frame = core.findings_frame()
    risks, _, _ = build_top_n_risk_table(df, core.period_columns, core.numeric_matrix, top_n=1)
    assert classify_top_n_safety(frame, risks) == "NO"


def test_risk_table_makes_top_n_unresolved():
    df = pd.DataFrame({
        "Entity": ["A", "B", "C"],
        "1950": [100, 90, 80],
        "1951": [None, 95, 85],
        "1952": [110, 100, 90],
    })
    core = run_core_checks(df)
    risks, _, _ = build_top_n_risk_table(df, core.period_columns, core.numeric_matrix, top_n=2)
    assert classify_top_n_safety(core.findings_frame(), risks) == "UNRESOLVED"


def test_clean_complete_data_is_top_n_yes():
    df = pd.DataFrame({"Entity": ["A", "B"], "1950": [10, 9], "1951": [11, 10]})
    core = run_core_checks(df)
    risks, _, _ = build_top_n_risk_table(df, core.period_columns, core.numeric_matrix, top_n=1)
    assert risks.empty
    assert classify_top_n_safety(core.findings_frame(), risks) == "YES"
