from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from modules.error_checker import CheckerConfig, run_core_checks
from modules.file_reader import get_sheet_names, read_table
from modules.orientation import detect_orientation, normalize_to_checker
from modules.ranking_engine import build_top_n_risk_table, classify_top_n_safety
from modules.report_builder import category_summary, final_status, severity_counts


st.set_page_config(page_title="Data Rank Hub Excel Checker Pro", page_icon="📊", layout="wide")

st.title("Data Rank Hub Excel Checker Pro")
st.caption("UPLOAD → CHECK → REVIEW → FIX → RECHECK → DOWNLOAD")
st.info(
    "Stage 3: core checker + year-by-year Top-N risk + simpler review experience. "
    "Historical lifecycle protection and Auto Series Fill come next after this stage is tested."
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

st.caption(
    f"Detected {orientation.frequency or 'unknown'} periods. Original layout is remembered for future corrected-file export."
)
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
        help="Top-N is calculated separately for every period. The checker does not use an entity's best rank across its whole history.",
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
    risk_table, ranking = build_top_n_risk_table(
        normalized_df, result.period_columns, result.numeric_matrix, int(top_n)
    ) if result.period_columns else (pd.DataFrame(), None)
    st.session_state["stage3_result"] = result
    st.session_state["stage3_risk_table"] = risk_table
    st.session_state["stage3_signature"] = settings_signature

if st.session_state.get("stage3_signature") != settings_signature:
    st.caption("Choose the settings above and press CHECK DATASET.")
    st.stop()

result = st.session_state.get("stage3_result")
risk_table = st.session_state.get("stage3_risk_table", pd.DataFrame())
if result is None:
    st.stop()

findings_df = result.findings_frame()
counts = severity_counts(findings_df)
core_status = final_status(findings_df)
top_n_status = classify_top_n_safety(findings_df, risk_table)
internal_gaps = int((findings_df["Category"] == "Internal Gap").sum()) if not findings_df.empty else 0

st.subheader("3. Results")
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Must Fix", counts.get("MUST FIX", 0))
m2.metric("Must Check", counts.get("MUST CHECK", 0))
m3.metric("Review", counts.get("REVIEW", 0))
m4.metric("Internal Gaps", internal_gaps)
m5.metric(f"Top {top_n} Risk", len(risk_table))
m6.metric("Core Data", core_status)

st.markdown(f"**Top-N Ranking Safety:** `{top_n_status}`")
if core_status == "READY" and top_n_status == "YES":
    st.success("No critical core issues or identified Top-N missing-data risks were found in the active checks.")
elif top_n_status == "NO":
    st.error("A definite structural/data problem can affect ranking. Fix Must Fix items before using the ranking.")
elif top_n_status == "UNRESOLVED":
    st.warning(f"Ranking safety is not certified yet. Review the Top {top_n} risk items below.")
else:
    st.warning("Review the items below before final use.")

# A direct next-action guide makes the screen useful without reading every table.
if counts.get("MUST FIX", 0):
    st.write(f"**Recommended next action:** Fix the {counts['MUST FIX']} Must Fix item(s) first.")
elif counts.get("MUST CHECK", 0):
    st.write(f"**Recommended next action:** Verify the {counts['MUST CHECK']} Must Check item(s), then recheck.")
elif len(risk_table):
    st.write(f"**Recommended next action:** Review {len(risk_table)} missing value(s) that may affect Top {top_n}.")
elif counts.get("REVIEW", 0):
    st.write(f"**Recommended next action:** Core data is clear; {counts['REVIEW']} Review item(s) are optional verification points.")
else:
    st.write("**Recommended next action:** No action required from the active Stage-3 checks.")

st.subheader(f"4. Top {top_n} ranking risk")
st.caption(
    "The checker evaluates each period separately. A missing value is flagged only when nearby period evidence suggests it could realistically matter to the selected Top-N. "
    "Risk estimates are for review only; they are never written into your data."
)
if risk_table.empty:
    st.success(f"No missing cells were identified as likely Top {top_n} risks by the active Stage-3 rules.")
else:
    entity_options = ["All"] + sorted(risk_table["Entity"].dropna().astype(str).unique().tolist())
    selected_entity = st.selectbox("Review entity", entity_options, key="risk_entity")
    shown_risk = risk_table if selected_entity == "All" else risk_table[risk_table["Entity"] == selected_entity]
    st.dataframe(shown_risk, use_container_width=True, hide_index=True)
    st.info(
        "What this means: these values are missing and local ranking evidence says they may matter. "
        "Do not fill them blindly; verify the source or wait for the Safe Series Fill stage."
    )

st.subheader("5. Other findings")
if findings_df.empty:
    st.success("No findings from the active core checks.")
else:
    quick_filter = st.radio(
        "Show",
        ["Needs attention", "Must Fix", "Must Check", "Review", "All"],
        horizontal=True,
    )
    if quick_filter == "Needs attention":
        filtered = findings_df[findings_df["Severity"].isin(["MUST FIX", "MUST CHECK"])]
    elif quick_filter == "All":
        filtered = findings_df
    else:
        severity_name = quick_filter.upper() if quick_filter != "Must Fix" and quick_filter != "Must Check" else quick_filter.upper()
        filtered = findings_df[findings_df["Severity"] == severity_name]

    if filtered.empty:
        st.success("Nothing in this filter.")
    else:
        st.dataframe(filtered, use_container_width=True, hide_index=True)

    with st.expander("Counts by problem type"):
        st.dataframe(category_summary(findings_df), use_container_width=True, hide_index=True)

st.subheader("6. Coverage")
st.caption(
    "Leading and trailing blanks are coverage information for now. Historical lifecycle rules will decide whether they are expected or need checking in the next stage."
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
        "top_n_engine": f"Active — period-by-period Top {top_n}",
        "historical_lifecycle": "Not active yet — Stage 4",
        "auto_series_fill": "Not active yet — after lifecycle protection",
    })
