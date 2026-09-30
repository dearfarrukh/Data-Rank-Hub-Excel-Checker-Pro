from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from modules.error_checker import CheckerConfig, run_core_checks
from modules.file_reader import get_sheet_names, read_table
from modules.lifecycle import build_lifecycle_summary, load_lifecycle_rules
from modules.orientation import detect_orientation, normalize_to_checker
from modules.ranking_engine import build_top_n_risk_table, classify_top_n_safety
from modules.report_builder import build_action_table, category_summary, final_status, severity_counts


st.set_page_config(page_title="Data Rank Hub Excel Checker Pro", page_icon="📊", layout="wide")

st.title("Data Rank Hub Excel Checker Pro")
st.caption("UPLOAD → CHECK → REVIEW → FIX → RECHECK → DOWNLOAD")
st.info(
    "Stage 4: clear problem display + historical lifecycle protection + smarter period-by-period Top-N risk. "
    "Safe Auto Series Fill is the next stage."
)

uploaded_file = st.file_uploader(
    "Upload Excel or CSV",
    type=["xlsx", "xls", "csv"],
    help="Supports Data Rank Hub checker format and AlienArt format.",
)
if uploaded_file is None:
    st.stop()

file_bytes = uploaded_file.getvalue()
file_hash = hashlib.sha256(file_bytes).hexdigest()

try:
    sheet_names = get_sheet_names(file_bytes, uploaded_file.name)
except Exception as exc:
    st.error(f"Could not inspect the file: {exc}")
    st.stop()

selected_sheet = st.selectbox("Sheet", sheet_names, index=0) if sheet_names else None
try:
    loaded = read_table(file_bytes, uploaded_file.name, selected_sheet)
except Exception as exc:
    st.error(f"Could not read the selected table: {exc}")
    st.stop()

original_df = loaded.dataframe
orientation = detect_orientation(original_df)
orientation_label = {
    "checker": "Checker format",
    "alienart": "AlienArt format",
    "unknown": "Unknown",
}.get(orientation.orientation, orientation.orientation)

st.subheader("1. File detected")
a, b, c, d = st.columns(4)
a.metric("Rows", f"{len(original_df):,}")
b.metric("Columns", f"{len(original_df.columns):,}")
c.metric("Layout", orientation_label)
d.metric("Detection confidence", f"{orientation.confidence:.0%}")

if orientation.orientation == "unknown":
    st.warning(orientation.reason)
    st.stop()

try:
    normalized_df = normalize_to_checker(original_df, orientation)
except Exception as exc:
    st.error(f"Could not normalize this table: {exc}")
    st.stop()

st.caption(f"Detected {orientation.frequency or 'unknown'} periods. Original layout is remembered for corrected-file export.")
with st.expander("Preview uploaded data"):
    st.dataframe(original_df.head(30), use_container_width=True, hide_index=True)
with st.expander("Technical: internal checker view"):
    st.dataframe(normalized_df.head(30), use_container_width=True, hide_index=True)

st.subheader("2. Check dataset")
left, right = st.columns([2, 1])
with left:
    top_n = st.selectbox(
        "Important ranking",
        options=[10, 15, 20, 25, 30],
        index=1,
        format_func=lambda n: f"Top {n}",
        help="Ranking is calculated separately for every period.",
    )
with right:
    data_mode = st.selectbox(
        "Data type",
        ["Regular Data", "Cumulative Totals"],
        help="Choose Cumulative Totals only when the series should never decrease.",
    )

with st.expander("Advanced settings", expanded=False):
    c1, c2, c3 = st.columns(3)
    with c1:
        repeated_threshold = st.number_input("Repeated value threshold", 2, 20, 2, 1)
    with c2:
        suspicious_jump_threshold = st.number_input("Suspicious jump %", 100, 10000, 500, 50)
    with c3:
        check_negative_values = st.checkbox("Check negative values", value=True)

check_clicked = st.button("CHECK DATASET", type="primary", use_container_width=True)
settings_signature = (
    file_hash, selected_sheet, int(top_n), data_mode, int(repeated_threshold),
    float(suspicious_jump_threshold), bool(check_negative_values),
)

if check_clicked:
    config = CheckerConfig(
        data_mode=data_mode,
        repeated_threshold=int(repeated_threshold),
        suspicious_jump_threshold=float(suspicious_jump_threshold),
        check_negative_values=bool(check_negative_values),
    )
    result = run_core_checks(normalized_df, config)
    lifecycle_rules = load_lifecycle_rules()
    if result.period_columns:
        risk_table, ranking, lifecycle_skips = build_top_n_risk_table(
            normalized_df,
            result.period_columns,
            result.numeric_matrix,
            int(top_n),
            lifecycle_rules=lifecycle_rules,
        )
        lifecycle_summary = build_lifecycle_summary(
            normalized_df, result.period_columns, result.numeric_matrix, lifecycle_rules
        )
    else:
        risk_table, ranking = pd.DataFrame(), None
        lifecycle_skips = pd.DataFrame()
        lifecycle_summary = pd.DataFrame()

    st.session_state["stage4_result"] = result
    st.session_state["stage4_risk_table"] = risk_table
    st.session_state["stage4_lifecycle_skips"] = lifecycle_skips
    st.session_state["stage4_lifecycle_summary"] = lifecycle_summary
    st.session_state["stage4_signature"] = settings_signature

if st.session_state.get("stage4_signature") != settings_signature:
    st.caption("Choose the settings above and press CHECK DATASET.")
    st.stop()

result = st.session_state.get("stage4_result")
risk_table = st.session_state.get("stage4_risk_table", pd.DataFrame())
lifecycle_skips = st.session_state.get("stage4_lifecycle_skips", pd.DataFrame())
lifecycle_summary = st.session_state.get("stage4_lifecycle_summary", pd.DataFrame())
if result is None:
    st.stop()

findings_df = result.findings_frame()
core_counts = severity_counts(findings_df)
core_status = final_status(findings_df)
top_n_status = classify_top_n_safety(findings_df, risk_table)
action_table = build_action_table(findings_df, risk_table)

# Top-N risk rows are actual MUST CHECK items in Stage 4.
combined_must_check = int(core_counts.get("MUST CHECK", 0)) + int(len(risk_table))
internal_gaps = int((findings_df["Category"] == "Internal Gap").sum()) if not findings_df.empty else 0
historical_expected = 0
protected_transition = 0
if not lifecycle_summary.empty:
    historical_expected = int(lifecycle_summary["Expected Historical Blanks"].sum())
    protected_transition = int(lifecycle_summary["Protected Transition Blanks"].sum())

st.subheader("3. Results")
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Must Fix", core_counts.get("MUST FIX", 0))
m2.metric("Must Check", combined_must_check)
m3.metric("Review", core_counts.get("REVIEW", 0))
m4.metric("Internal Gaps", internal_gaps)
m5.metric(f"Top {top_n} Risk", len(risk_table))
m6.metric("Historical Expected", historical_expected)

status_left, status_right = st.columns(2)
with status_left:
    st.markdown(f"**Core Data Status:** `{core_status}`")
with status_right:
    st.markdown(f"**Top-N Ranking Safety:** `{top_n_status}`")

if core_counts.get("MUST FIX", 0):
    st.error(f"Fix {core_counts['MUST FIX']} definite problem(s) before using this dataset.")
elif combined_must_check:
    st.warning(f"{combined_must_check} item(s) need verification before Top {top_n} can be certified.")
elif core_counts.get("REVIEW", 0):
    st.success(f"No critical blockers found. {core_counts['REVIEW']} review item(s) are optional verification points.")
else:
    st.success("No active core or Top-N blockers were found.")

if historical_expected or protected_transition:
    st.info(
        f"Historical lifecycle protection recognized {historical_expected} expected blank(s) and "
        f"{protected_transition} protected transition blank(s). These are not treated as ordinary missing-data errors."
    )

if core_counts.get("MUST FIX", 0):
    st.write("**Recommended next action:** Open **Problems to review** and fix the MUST FIX rows first.")
elif combined_must_check:
    st.write("**Recommended next action:** Review the MUST CHECK rows below and verify them against the source.")
elif core_counts.get("REVIEW", 0):
    st.write("**Recommended next action:** Dataset can proceed from the active critical checks; review suspicious items if needed.")
else:
    st.write("**Recommended next action:** No action required from the active Stage-4 checks.")

st.subheader("4. Problems to review")
st.caption("This is the main work list: Entity + Period + exact problem + why it was flagged + what to do next.")
if action_table.empty:
    st.success("No problems found by the active checks.")
else:
    f1, f2 = st.columns([1, 2])
    with f1:
        severity_filter = st.selectbox("Severity", ["Needs attention", "MUST FIX", "MUST CHECK", "REVIEW", "All"])
    with f2:
        entities = ["All entities"] + sorted([e for e in action_table["Entity"].dropna().astype(str).unique().tolist() if e])
        entity_filter = st.selectbox("Entity", entities)

    shown = action_table.copy()
    if severity_filter == "Needs attention":
        shown = shown[shown["Severity"].isin(["MUST FIX", "MUST CHECK"])]
    elif severity_filter != "All":
        shown = shown[shown["Severity"] == severity_filter]
    if entity_filter != "All entities":
        shown = shown[shown["Entity"] == entity_filter]

    if shown.empty:
        st.success("Nothing in this filter.")
    else:
        visible_columns = [
            "Severity", "Entity", "Period", "Problem", "Current Value", "Previous Value", "Previous Rank",
            "Next Value", "Next Rank", "Top-N Cutoff", "Why Flagged", "What To Do",
        ]
        st.dataframe(shown[visible_columns], use_container_width=True, hide_index=True)

st.subheader(f"5. Top {top_n} ranking details")
if risk_table.empty:
    st.success(f"No unresolved missing cells were identified as realistic Top {top_n} risks after lifecycle filtering.")
else:
    st.caption("Each row is period-specific. Historical expected blanks are removed before this table is built.")
    st.dataframe(risk_table, use_container_width=True, hide_index=True)

with st.expander("Historical lifecycle details"):
    if lifecycle_summary.empty:
        st.caption("No configured historical lifecycle rule matched entities in this dataset.")
    else:
        st.dataframe(lifecycle_summary, use_container_width=True, hide_index=True)
    if not lifecycle_skips.empty:
        st.caption("Protected/expected blank periods excluded from Top-N risk:")
        st.dataframe(lifecycle_skips, use_container_width=True, hide_index=True)

st.subheader("6. Other core findings")
if findings_df.empty:
    st.success("No core findings.")
else:
    with st.expander("Counts by problem type"):
        st.dataframe(category_summary(findings_df), use_container_width=True, hide_index=True)
    with st.expander("Full core findings table"):
        st.dataframe(findings_df, use_container_width=True, hide_index=True)

st.subheader("7. Coverage")
st.caption(
    "Leading/trailing blanks remain coverage information unless a configured lifecycle rule classifies them or local ranking evidence makes an adjacent boundary period relevant."
)
st.dataframe(result.completeness, use_container_width=True, hide_index=True)

with st.expander("Technical details"):
    st.write({
        "filename": loaded.filename,
        "sheet": loaded.sheet_name,
        "file_fingerprint": file_hash[:12],
        "original_orientation": orientation.orientation,
        "frequency": orientation.frequency,
        "recognized_period_columns": len(result.period_columns),
        "entities": len(normalized_df),
        "top_n_engine": f"Active — period-by-period Top {top_n}, lifecycle-aware",
        "historical_lifecycle": "Active — configurable rules",
        "historical_expected_blanks": historical_expected,
        "protected_transition_blanks": protected_transition,
        "auto_series_fill": "Not active yet — Stage 5",
    })
