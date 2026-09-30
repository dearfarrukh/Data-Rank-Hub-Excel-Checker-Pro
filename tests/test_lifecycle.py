import pandas as pd

from modules.error_checker import run_core_checks
from modules.lifecycle import (
    LifecycleRule,
    build_lifecycle_summary,
    classify_lifecycle,
    rule_lookup,
)
from modules.ranking_engine import build_top_n_risk_table
from modules.report_builder import build_action_table


def sample_rules():
    return [
        LifecycleRule("USSR", ("Soviet Union",), None, 1991, frozenset({1991, 1992}), "USSR transition"),
        LifecycleRule("Russia", ("Russian Federation",), 1992, None, frozenset({1991, 1992}), "Russia transition"),
        LifecycleRule("Czechoslovakia", (), None, 1992, frozenset({1992, 1993}), "split"),
        LifecycleRule("Czechia", ("Czech Republic",), 1993, None, frozenset({1992, 1993}), "split"),
    ]


def test_lifecycle_expected_after_end_and_before_start():
    lookup = rule_lookup(sample_rules())
    assert classify_lifecycle("USSR", "1993", lookup)[0] == "EXPECTED_AFTER_END"
    assert classify_lifecycle("Russia", "1990", lookup)[0] == "EXPECTED_BEFORE_START"
    assert classify_lifecycle("Czech Republic", "1992", lookup)[0] == "EXPECTED_BEFORE_START"


def test_transition_year_is_protected_when_inside_active_window():
    lookup = rule_lookup(sample_rules())
    assert classify_lifecycle("USSR", "1991", lookup)[0] == "PROTECTED_TRANSITION"
    assert classify_lifecycle("Russia", "1992", lookup)[0] == "PROTECTED_TRANSITION"


def test_historical_expected_blank_is_removed_from_top_n_risk():
    df = pd.DataFrame({
        "Entity": ["USSR", "B", "C"],
        "1991": [100, 90, 80],
        "1992": [None, 95, 85],
        "1993": [None, 100, 90],
    })
    core = run_core_checks(df)
    risks, _, skipped = build_top_n_risk_table(
        df, core.period_columns, core.numeric_matrix, top_n=2, lifecycle_rules=sample_rules()
    )
    assert risks.empty
    assert set(skipped["Period"].tolist()) == {"1992", "1993"}


def test_distant_leading_blank_is_not_flagged_by_boundary_logic():
    df = pd.DataFrame({
        "Entity": ["A", "B", "C"],
        "1950": [None, 100, 90],
        "1951": [None, 101, 91],
        "1952": [110, 102, 92],
    })
    core = run_core_checks(df)
    risks, _, _ = build_top_n_risk_table(df, core.period_columns, core.numeric_matrix, top_n=2, lifecycle_rules=[])
    # 1951 may be locally relevant because it is adjacent to 1952; 1950 must not be flagged from a distant anchor.
    a_periods = risks.loc[risks["Entity"] == "A", "Error Period"].tolist()
    assert "1950" not in a_periods


def test_lifecycle_summary_counts_expected_blanks():
    df = pd.DataFrame({"Entity": ["Russia"], "1990": [None], "1991": [None], "1992": [10], "1993": [11]})
    core = run_core_checks(df)
    summary = build_lifecycle_summary(df, core.period_columns, core.numeric_matrix, sample_rules())
    row = summary.iloc[0]
    assert row["Expected Historical Blanks"] == 2


def test_action_table_includes_top_n_problem_and_instruction():
    findings = pd.DataFrame(columns=["Category", "Severity", "Entity", "Period", "Value", "Details", "Suggestion", "Fixable"])
    risks = pd.DataFrame([{
        "Entity": "A", "Error Period": "1951", "Problem Type": "Missing value may affect Top-N",
        "Previous Value": 100, "Previous Rank": 1, "Current Value": None,
        "Next Value": 110, "Next Rank": 1, "Top-N Cutoff": 90,
        "Why Flagged": "previous rank was 1", "What To Do": "Verify source",
    }])
    action = build_action_table(findings, risks)
    assert action.iloc[0]["Severity"] == "MUST CHECK"
    assert action.iloc[0]["Entity"] == "A"
    assert action.iloc[0]["What To Do"] == "Verify source"
