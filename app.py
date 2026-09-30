from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from modules.error_checker import CheckerConfig, run_core_checks
from modules.file_reader import get_sheet_names, read_table
from modules.orientation import detect_orientation, normalize_to_checker
from modules.report_builder import category_summary, final_status, severity_counts, top_n_safety_placeholder


st.set_page_config(
    page_title="Data Rank Hub Excel Checker Pro",
    page_icon="📊",
    layout="wide",
)

st.title("Data Rank Hub Excel Checker Pro")
st.caption("UPLOAD → CHECK → REVIEW → FIX → RECHECK → DOWNLOAD")

st.info(
    "Stage 2: smart upload/orientation + V10 core structural and numeric checks. "
    "Top-N risk, historical lifecycle rules, correction tools, and Auto Series Fill will be added in later tested stages."
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

selected_sheet = None
if sheet_names:
    selected_sheet = st.selectbox("Sheet", sheet_names, index=0)

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

st.subheader("1. Upload detected")
a, b, c, d = st.columns(4)
a.metric("Rows", f"{len(original_df):,}")
b.metric("Columns", f"{len(original_df.columns):,}")
c.metric("Orientation", orientation_label)
d.metric("Confidence", f"{orientation.confidence:.0%}")

with st.expander("Original file preview", expanded=False):
    st.dataframe(original_df.head(30), use_container_width=True, hide_index=True)

if orientation.orientation == "unknown":
    st.warning(orientation.reason)
    st.stop()

try:
    normalized_df = normalize_to_checker(original_df, orientation)
except Exception as exc:
    st.error(f"Could not normalize this table: {exc}")
    st.stop()

st.caption(
    f"Detected {orientation.frequency or 'unknown'} periods. "
    f"The original {orientation_label} layout is remembered for future corrected-file export."
)

with st.expander("Internal checker view", expanded=False):
    st.dataframe(normalized_df.head(30), use_container_width=True, hide_index=True)

st.subheader("2. Check settings")
with st.form("checker_settings"):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        data_mode = st.selectbox(
            "Data Mode",
            ["Regular Data", "Cumulative Totals"],
            help="Use Cumulative Totals for series that should never decrease, such as cumulative deaths.",
        )
    with c2:
        repeated_threshold = st.number_input(
            "Repeated Value Threshold",
            min_value=2,
            max_value=20,
            value=2,
            step=1,
        )
    with c3:
        suspicious_jump_threshold = st.number_input(
            "Suspicious Jump %",
            min_value=100,
            max_value=10000,
            value=500,
            step=50,
        )
    with c4:
        check_negative_values = st.checkbox("Check Negative Values", value=True)

    check_clicked = st.form_submit_button("CHECK DATASET", type="primary", use_container_width=True)

settings_signature = (
    file_hash,
    selected_sheet,
    data_mode,
    int(repeated_threshold),
    float(suspicious_jump_threshold),
    bool(check_negative_values),
)

if check_clicked:
    config = CheckerConfig(
        data_mode=data_mode,
        repeated_threshold=int(repeated_threshold),
        suspicious_jump_threshold=float(suspicious_jump_threshold),
        check_negative_values=bool(check_negative_values),
    )
    result = run_core_checks(normalized_df, config)
    st.session_state["stage2_result"] = result
    st.session_state["stage2_signature"] = settings_signature

if st.session_state.get("stage2_signature") != settings_signature:
    st.caption("Choose the settings above and press CHECK DATASET.")
    st.stop()

result = st.session_state.get("stage2_result")
if result is None:
    st.stop()

findings_df = result.findings_frame()
counts = severity_counts(findings_df)
status = final_status(findings_df)

st.subheader("3. Dashboard")
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Must Fix", counts.get("MUST FIX", 0))
m2.metric("Must Check", counts.get("MUST CHECK", 0))
m3.metric("Review", counts.get("REVIEW", 0))
m4.metric("Internal Gaps", int((findings_df["Category"] == "Internal Gap").sum()) if not findings_df.empty else 0)
m5.metric("Top-N Ranking Safe", top_n_safety_placeholder())
m6.metric("Final Status", status)

if status == "READY":
    st.success("Core Stage-2 checks found no unresolved Must Fix or Must Check items.")
else:
    st.warning("This dataset still has items that need fixing or checking before final certification.")

st.subheader("4. Findings")
if findings_df.empty:
    st.success("No findings from the active Stage-2 checks.")
else:
    severity_filter = st.multiselect(
        "Severity",
        options=["MUST FIX", "MUST CHECK", "REVIEW"],
        default=["MUST FIX", "MUST CHECK", "REVIEW"],
    )
    category_options = sorted(findings_df["Category"].dropna().astype(str).unique().tolist())
    category_filter = st.multiselect("Category", options=category_options, default=category_options)

    filtered = findings_df[
        findings_df["Severity"].isin(severity_filter)
        & findings_df["Category"].isin(category_filter)
    ]
    st.dataframe(filtered, use_container_width=True, hide_index=True)

    with st.expander("Finding counts by category"):
        st.dataframe(category_summary(findings_df), use_container_width=True, hide_index=True)

st.subheader("5. Completeness")
st.caption(
    "Leading/trailing blanks are shown here as coverage information, not automatically called errors. "
    "Historical lifecycle logic will decide those cases in a later stage."
)
st.dataframe(result.completeness, use_container_width=True, hide_index=True)

with st.expander("Stage 2 technical details"):
    st.write({
        "filename": loaded.filename,
        "sheet": loaded.sheet_name,
        "file_fingerprint": file_hash[:12],
        "original_orientation": orientation.orientation,
        "frequency": orientation.frequency,
        "recognized_period_columns": len(result.period_columns),
        "entities": len(normalized_df),
        "top_n_engine": "Not active yet — Stage 3",
        "historical_lifecycle": "Not active yet — later stage",
        "auto_series_fill": "Not active yet — only after checker + lifecycle are stable",
    })
