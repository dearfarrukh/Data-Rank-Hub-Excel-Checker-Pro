from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from modules.file_reader import get_sheet_names, read_table
from modules.orientation import detect_orientation, normalize_to_checker


st.set_page_config(
    page_title="Data Rank Hub Excel Checker Pro",
    page_icon="📊",
    layout="wide",
)

st.title("Data Rank Hub Excel Checker Pro")
st.caption("UPLOAD → CHECK → REVIEW → FIX → RECHECK → DOWNLOAD")

st.info(
    "Stage 1: file upload + sheet selection + smart orientation detection. "
    "Core checker rules will be added only after this foundation passes testing."
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
result = detect_orientation(original_df)

st.subheader("1. File detected")
left, middle, right = st.columns(3)
left.metric("Rows", f"{len(original_df):,}")
middle.metric("Columns", f"{len(original_df.columns):,}")
right.metric("File fingerprint", file_hash[:10])

st.dataframe(original_df.head(20), use_container_width=True, hide_index=True)

st.subheader("2. Orientation")
col1, col2, col3, col4 = st.columns(4)

orientation_label = {
    "checker": "Checker format",
    "alienart": "AlienArt format",
    "unknown": "Unknown",
}.get(result.orientation, result.orientation)

col1.metric("Orientation", orientation_label)
col2.metric("Confidence", f"{result.confidence:.0%}")
col3.metric("Frequency", result.frequency or "Unknown")
col4.metric("Periods", f"{result.period_count:,}")

if result.orientation == "checker":
    st.success(
        f"Detected Checker format. Entity column: '{result.entity_column}'. "
        f"{result.reason}"
    )
elif result.orientation == "alienart":
    st.success(
        f"Detected AlienArt format. Period column: '{result.period_column}'. "
        f"{result.reason}"
    )
else:
    st.warning(result.reason)
    st.write(
        "The checker will not guess. We will add a manual orientation override in the next stage "
        "for unusual files."
    )
    st.stop()

try:
    normalized_df = normalize_to_checker(original_df, result)
except Exception as exc:
    st.error(f"Could not normalize this table: {exc}")
    st.stop()

st.subheader("3. Internal checker view")
st.caption(
    "The app converts both supported layouts into one internal structure. "
    "The original orientation is remembered for later corrected-file export."
)

c1, c2 = st.columns(2)
c1.metric("Entities", f"{len(normalized_df):,}")
c2.metric("Period columns", f"{max(0, len(normalized_df.columns) - 1):,}")

st.dataframe(normalized_df.head(25), use_container_width=True, hide_index=True)

with st.expander("Stage 1 detection details"):
    st.write({
        "filename": loaded.filename,
        "sheet": loaded.sheet_name,
        "original_orientation": result.orientation,
        "entity_column": result.entity_column,
        "period_column": result.period_column,
        "frequency": result.frequency,
        "confidence": round(result.confidence, 4),
        "entities": result.entity_count,
        "periods": result.period_count,
    })

st.success("Stage 1 passed for this file: upload and orientation normalization are working.")
st.caption("Next stage: V10 core structural/data checks without the old historical-best-rank priority logic.")
