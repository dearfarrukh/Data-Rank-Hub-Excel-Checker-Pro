import pandas as pd

from modules.coverage_engine import detect_start_end_candidates
from modules.correction_manager import build_force_override
from modules.lifecycle import LifecycleRule


def test_detects_start_year_candidate_for_unclassified_leading_blanks():
    df = pd.DataFrame({
        "Entity": ["China"],
        "1950": [None], "1951": [None], "1952": [None],
        "1953": [60], "1954": [100], "1955": [150],
    })
    numeric = df.drop(columns=["Entity"]).apply(pd.to_numeric, errors="coerce")
    out = detect_start_end_candidates(df, list(numeric.columns), numeric, lifecycle_rules=[])
    start = out[out["Candidate Type"] == "START"]
    assert len(start) == 1
    row = start.iloc[0]
    assert row["Candidate Period"] == "1953"
    assert row["Boundary Period"] == "1952"
    assert row["Blank From"] == "1950"
    assert row["Blank To"] == "1952"


def test_known_lifecycle_start_does_not_create_candidate():
    df = pd.DataFrame({"Entity": ["Russia"], "1990": [None], "1991": [None], "1992": [100], "1993": [120]})
    numeric = df.drop(columns=["Entity"]).apply(pd.to_numeric, errors="coerce")
    rules = [LifecycleRule("Russia", tuple(), 1992, None, frozenset(), "USSR predecessor")]
    out = detect_start_end_candidates(df, list(numeric.columns), numeric, lifecycle_rules=rules)
    assert out.empty


def test_confirmed_force_start_removes_start_candidate():
    df = pd.DataFrame({"Entity": ["Example"], "2000": [None], "2001": [None], "2002": [10], "2003": [20]})
    numeric = df.drop(columns=["Entity"]).apply(pd.to_numeric, errors="coerce")
    override = build_force_override("Example", "2001", "Series intentionally starts here", "This and all earlier periods")
    out = detect_start_end_candidates(df, list(numeric.columns), numeric, lifecycle_rules=[], user_overrides=[override])
    assert out.empty


def test_detects_end_year_candidate():
    df = pd.DataFrame({"Entity": ["A"], "2000": [10], "2001": [20], "2002": [None], "2003": [None]})
    numeric = df.drop(columns=["Entity"]).apply(pd.to_numeric, errors="coerce")
    out = detect_start_end_candidates(df, list(numeric.columns), numeric, lifecycle_rules=[])
    end = out[out["Candidate Type"] == "END"]
    assert len(end) == 1
    assert end.iloc[0]["Candidate Period"] == "2001"
    assert end.iloc[0]["Boundary Period"] == "2002"
