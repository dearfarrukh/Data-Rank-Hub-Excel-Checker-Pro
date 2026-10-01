from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from modules.audit_log import make_audit_entry
from modules.coverage_engine import detect_start_end_candidates
from modules.correction_manager import (
    FORCE_REASONS,
    add_resolution,
    apply_manual_value,
    build_force_override,
)
from modules.error_checker import CheckerConfig, run_core_checks
from modules.export_manager import build_audit_report_bytes, build_corrected_workbook_bytes
from modules.file_reader import get_sheet_names, read_table
from modules.lifecycle import build_lifecycle_summary, load_lifecycle_rules
from modules.orientation import detect_orientation, normalize_to_checker
from modules.ranking_engine import build_top_n_risk_table
from modules.report_builder import build_action_table
from modules.review_manager import (
    add_ranking_context,
    apply_resolutions,
    clean_display_value,
    entity_counts,
    filter_issues,
)
from modules.series_fill import apply_fill_candidates, find_safe_fill_candidates


st.set_page_config(page_title="Data Rank Hub Excel Checker Pro", page_icon="📊", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 3rem;}
    div[data-testid="stMetric"] {background: rgba(120,120,120,.06); border-radius: 14px; padding: 12px;}
    .small-muted {color:#777; font-size:0.9rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def _state_key(file_hash: str, sheet: str | None) -> str:
    return f"{file_hash}|{sheet or ''}"


def _reset_workspace(normalized_df: pd.DataFrame, workspace_key: str) -> None:
    st.session_state["workspace_key"] = workspace_key
    st.session_state["working_df"] = normalized_df.copy()
    st.session_state["resolutions"] = {}
    st.session_state["force_overrides"] = []
    st.session_state["audit_log"] = []
    st.session_state["fix_mode"] = ""
    st.session_state["country_complete"] = set()


def _append_audit(entry: dict) -> None:
    st.session_state.setdefault("audit_log", []).append(entry)


def _resolve(issue_id: str, action: str, reason: str, entity: str = "", period: str = "") -> None:
    st.session_state["resolutions"] = add_resolution(
        st.session_state.get("resolutions", {}), issue_id, action, reason
    )
    _append_audit(make_audit_entry(action, entity, period, reason=reason, method="Review action"))


def _rerun() -> None:
    st.session_state["fix_mode"] = ""
    st.rerun()


# -----------------------------------------------------------------------------
# Header + upload
# -----------------------------------------------------------------------------
st.title("Data Rank Hub Excel Checker Pro")
st.caption("UPLOAD → CHECK → REVIEW BY COUNTRY → FIX → RECHECK → DOWNLOAD")

uploaded_file = st.file_uploader(
    "Upload Excel or CSV",
    type=["xlsx", "xls", "csv"],
    help="Supports Checker format and AlienArt format. The original layout is remembered for corrected export.",
)
if uploaded_file is None:
    st.info("Upload a dataset to start. The checker will organize problems country-by-country.")
    st.stop()

file_bytes = uploaded_file.getvalue()
file_hash = hashlib.sha256(file_bytes).hexdigest()

try:
    sheet_names = get_sheet_names(file_bytes, uploaded_file.name)
except Exception as exc:
    st.error(f"Could not inspect this file: {exc}")
    st.stop()

selected_sheet = st.selectbox("Sheet", sheet_names, index=0) if sheet_names else None

try:
    loaded = read_table(file_bytes, uploaded_file.name, selected_sheet)
except Exception as exc:
    st.error(f"Could not read the selected table: {exc}")
    st.stop()

original_df = loaded.dataframe
orientation = detect_orientation(original_df)
if orientation.orientation == "unknown":
    st.error("I could not confidently recognize the dataset layout.")
    st.caption(orientation.reason)
    st.stop()

try:
    normalized_df = normalize_to_checker(original_df, orientation)
except Exception as exc:
    st.error(f"Could not normalize this dataset: {exc}")
    st.stop()

workspace_key = _state_key(file_hash, selected_sheet)
if st.session_state.get("workspace_key") != workspace_key:
    _reset_workspace(normalized_df, workspace_key)

working_df = st.session_state["working_df"]

# -----------------------------------------------------------------------------
# Sidebar settings / navigation
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("Checker Menu")
    top_n = st.selectbox("Important ranking", [10, 15, 20, 25, 30], index=1, format_func=lambda n: f"Top {n}")
    data_mode = st.selectbox("Data type", ["Regular Data", "Cumulative Totals"])

    with st.expander("Advanced settings", expanded=False):
        repeated_threshold = st.number_input("Repeated value threshold", 2, 20, 2, 1)
        suspicious_jump_threshold = st.number_input("Suspicious jump %", 100, 10000, 500, 50)
        check_negative_values = st.checkbox("Check negative values", value=True)

# -----------------------------------------------------------------------------
# Run checker on the current working copy
# -----------------------------------------------------------------------------
config = CheckerConfig(
    data_mode=data_mode,
    repeated_threshold=int(repeated_threshold),
    suspicious_jump_threshold=float(suspicious_jump_threshold),
    check_negative_values=bool(check_negative_values),
)
result = run_core_checks(working_df, config)
lifecycle_rules = load_lifecycle_rules()

risk_table, ranking, lifecycle_skips = build_top_n_risk_table(
    working_df,
    result.period_columns,
    result.numeric_matrix,
    int(top_n),
    lifecycle_rules=lifecycle_rules,
    user_overrides=st.session_state.get("force_overrides", []),
)
lifecycle_summary = build_lifecycle_summary(
    working_df, result.period_columns, result.numeric_matrix, lifecycle_rules
)

coverage_candidates = detect_start_end_candidates(
    working_df,
    result.period_columns,
    result.numeric_matrix,
    lifecycle_rules=lifecycle_rules,
    user_overrides=st.session_state.get("force_overrides", []),
)

raw_action_table = build_action_table(result.findings_frame(), risk_table, coverage_candidates)
raw_action_table = add_ranking_context(raw_action_table, working_df, ranking)
unresolved, resolved = apply_resolutions(raw_action_table, st.session_state.get("resolutions", {}))

safe_fill_candidates = find_safe_fill_candidates(
    working_df,
    result.period_columns,
    lifecycle_rules=lifecycle_rules,
    user_overrides=st.session_state.get("force_overrides", []),
)

must_fix = int((unresolved["Severity"] == "MUST FIX").sum()) if not unresolved.empty else 0
must_check = int((unresolved["Severity"] == "MUST CHECK").sum()) if not unresolved.empty else 0
review_count = int(((unresolved["Severity"] == "REVIEW") & (unresolved["Source"] != "Coverage start/end")).sum()) if not unresolved.empty else 0
top_risk_count = int((unresolved["Source"] == "Top-N risk").sum()) if not unresolved.empty else 0
start_end_count = int((unresolved["Source"] == "Coverage start/end").sum()) if not unresolved.empty else 0
missing_period_count = int((unresolved["Problem"] == "Missing Period").sum()) if not unresolved.empty else 0

core_status = "READY" if must_fix == 0 and must_check == 0 else "REVIEW NEEDED"
if must_fix:
    top_n_safety = "NO"
elif top_risk_count or missing_period_count:
    top_n_safety = "UNRESOLVED"
else:
    top_n_safety = "YES"

historical_expected = int(lifecycle_summary["Expected Historical Blanks"].sum()) if not lifecycle_summary.empty else 0
protected_transition = int(lifecycle_summary["Protected Transition Blanks"].sum()) if not lifecycle_summary.empty else 0
user_forced = int((lifecycle_skips["Lifecycle Status"] == "USER_FORCE_CORRECT").sum()) if not lifecycle_skips.empty else 0

with st.sidebar:
    labels = {
        "All Errors": len(unresolved),
        "Must Fix": must_fix,
        "Must Check": must_check,
        "Review": review_count,
        "Top-N Risk": top_risk_count,
        "Start / End Years": start_end_count,
        "Historical / Expected": historical_expected + protected_transition + user_forced,
        "Fixed / Ignored": len(resolved),
        "Download": None,
        "Advanced Details": None,
    }
    menu = st.radio(
        "View",
        list(labels),
        format_func=lambda x: f"{x} ({labels[x]})" if labels[x] is not None else x,
    )

    st.divider()
    if st.button("APPLY HISTORICAL RULES", use_container_width=True):
        st.toast(
            f"Historical rules active: {historical_expected} expected blanks + {protected_transition} protected transition blanks.",
            icon="✅",
        )

    if safe_fill_candidates.empty:
        st.button("AUTO FILL ALL SAFE GAPS", disabled=True, use_container_width=True)
        st.caption("No safe internal gaps are ready for automatic fill.")
    else:
        st.caption(f"{len(safe_fill_candidates)} safe internal cell(s) ready for linear Series Fill.")
        if st.button("AUTO FILL ALL SAFE GAPS", type="primary", use_container_width=True):
            filled_df, logs = apply_fill_candidates(working_df, safe_fill_candidates)
            st.session_state["working_df"] = filled_df
            st.session_state.setdefault("audit_log", []).extend(logs)
            _rerun()

    if st.button("RECHECK", use_container_width=True):
        st.toast("Dataset rechecked using the current working copy.", icon="🔄")

# -----------------------------------------------------------------------------
# Compact status bar
# -----------------------------------------------------------------------------
layout_label = "AlienArt format" if orientation.orientation == "alienart" else "Checker format"
with st.container(border=True):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Must Fix", must_fix)
    c2.metric("Must Check", must_check)
    c3.metric("Review", review_count)
    c4.metric("Status", core_status)
    st.caption(
        f"{layout_label} • {orientation.frequency or 'Unknown frequency'} • Top {top_n} safety: {top_n_safety} • "
        f"Historical expected: {historical_expected:,} • Start/End checks: {start_end_count:,} • Safe fill ready: {len(safe_fill_candidates):,}"
    )

if must_fix:
    st.error(f"Start with the {must_fix} MUST FIX item(s).")
elif must_check:
    st.warning(f"{must_check} item(s) need verification before this dataset is fully ready.")
elif review_count:
    st.success("No critical blockers. Review items are optional verification points.")
else:
    st.success("No unresolved problems found by the active checks.")

# -----------------------------------------------------------------------------
# Main menu pages
# -----------------------------------------------------------------------------
if menu in {"All Errors", "Must Fix", "Must Check", "Review", "Top-N Risk", "Start / End Years"}:
    filtered = filter_issues(unresolved, menu)
    st.subheader(menu)
    if filtered.empty:
        st.success("Nothing to review in this section.")
    else:
        st.caption("Open a country to see every problem for that country and fix them one by one.")
        counts = entity_counts(filtered)

        for _, entity_row in counts.iterrows():
            entity = str(entity_row["Entity"])
            entity_issues = filtered[
                filtered["Entity"].replace("", "Dataset / Structure").fillna("Dataset / Structure").eq(entity)
            ].copy()
            label = f"{entity} ({len(entity_issues)})"
            if entity in st.session_state.get("country_complete", set()):
                label += " ✓"

            with st.expander(label, expanded=len(counts) <= 3):
                for _, issue in entity_issues.iterrows():
                    issue_id = str(issue["Issue ID"])
                    severity = str(issue.get("Severity", ""))
                    period = str(issue.get("Period", ""))
                    problem = str(issue.get("Problem", ""))
                    current = clean_display_value(issue.get("Current Value"))
                    prev = clean_display_value(issue.get("Previous Value"))
                    nxt = clean_display_value(issue.get("Next Value"))
                    prev_rank = clean_display_value(issue.get("Previous Rank"))
                    current_rank = clean_display_value(issue.get("Current Rank"))
                    next_rank = clean_display_value(issue.get("Next Rank"))
                    cutoff = clean_display_value(issue.get("Top-N Cutoff"))

                    with st.container(border=True):
                        if severity == "MUST FIX":
                            st.markdown(f"### 🔴 {period} — {problem}")
                        elif severity == "MUST CHECK":
                            st.markdown(f"### 🟠 {period} — {problem}")
                        else:
                            st.markdown(f"### 🟡 {period} — {problem}")

                        source = str(issue.get("Source", ""))
                        why = str(issue.get("Why Flagged", "")).strip()
                        action = str(issue.get("What To Do", "")).strip()

                        if source == "Coverage start/end":
                            candidate_type = str(issue.get("Candidate Type", ""))
                            candidate_period = str(issue.get("Candidate Period", ""))
                            boundary_period = str(issue.get("Boundary Period", ""))
                            blank_from = str(issue.get("Blank From", ""))
                            blank_to = str(issue.get("Blank To", ""))
                            blank_count = clean_display_value(issue.get("Blank Count"))
                            if candidate_type == "START":
                                st.markdown(f"**Suggested start year: {candidate_period}**")
                                st.write(f"Blank before start: **{blank_from}–{blank_to}** ({blank_count} periods)")
                                st.write(f"First available value: **{nxt}**")
                            else:
                                st.markdown(f"**Suggested end year: {candidate_period}**")
                                st.write(f"Blank after end: **{blank_from}–{blank_to}** ({blank_count} periods)")
                                st.write(f"Last available value: **{prev}**")
                            if why:
                                st.caption(why)
                            if action:
                                st.caption(action)

                            c1, c2, c3 = st.columns(3)
                            confirm_label = f"Confirm {'Start' if candidate_type == 'START' else 'End'} Year {candidate_period}"
                            if c1.button(confirm_label, key=f"confirm_boundary_{issue_id}", type="primary", use_container_width=True):
                                reason = "Series intentionally starts here" if candidate_type == "START" else "Series intentionally ends here"
                                scope = "This and all earlier periods" if candidate_type == "START" else "This and all later periods"
                                note = f"Confirmed {'start' if candidate_type == 'START' else 'end'} year {candidate_period}"
                                override = build_force_override(str(issue.get("Entity", "")), boundary_period, reason, scope, note)
                                st.session_state.setdefault("force_overrides", []).append(override)
                                _resolve(issue_id, confirm_label, note, str(issue.get("Entity", "")), period)
                                _rerun()
                            if c2.button("Force Correct", key=f"force_{issue_id}", use_container_width=True):
                                st.session_state["fix_mode"] = f"force:{issue_id}"
                            if c3.button("Keep for Review", key=f"keep_review_{issue_id}", use_container_width=True):
                                st.toast("Left unresolved so you can research it later.", icon="🔎")
                        else:
                            x1, x2, x3, x4 = st.columns(4)
                            x1.markdown(f"**Current**  \n{current}")
                            x2.markdown(f"**Previous**  \n{prev}  \nRank: {prev_rank}")
                            x3.markdown(f"**Next**  \n{nxt}  \nRank: {next_rank}")
                            x4.markdown(f"**Top {top_n}**  \nCutoff: {cutoff}  \nCurrent rank: {current_rank}")
                            if why:
                                st.caption(f"Why: {why}")
                            if action:
                                st.caption(f"Next: {action}")

                            exact_period = period in working_df.columns
                            candidate_rows = safe_fill_candidates[
                                safe_fill_candidates["Entity"].eq(str(issue.get("Entity", "")))
                            ] if not safe_fill_candidates.empty else pd.DataFrame()
                            exact_candidate = candidate_rows[candidate_rows["Period"].eq(period)] if not candidate_rows.empty else pd.DataFrame()

                            b1, b2, b3, b4 = st.columns(4)
                            if b1.button("Enter Correct Value", key=f"manual_{issue_id}", disabled=not exact_period, use_container_width=True):
                                st.session_state["fix_mode"] = f"manual:{issue_id}"
                            series_disabled = exact_candidate.empty and not (problem == "Internal Gap" and not candidate_rows.empty)
                            if b2.button("Series Fill", key=f"fill_{issue_id}", disabled=series_disabled, use_container_width=True):
                                selected = exact_candidate if not exact_candidate.empty else candidate_rows
                                filled_df, logs = apply_fill_candidates(working_df, selected)
                                st.session_state["working_df"] = filled_df
                                st.session_state.setdefault("audit_log", []).extend(logs)
                                _rerun()
                            keep_label = "Keep Blank" if current == "Not available" else "Keep Original"
                            if b3.button(keep_label, key=f"ignore_{issue_id}", use_container_width=True):
                                _resolve(issue_id, keep_label, "User reviewed and accepted the original data", str(issue.get("Entity", "")), period)
                                _rerun()
                            if b4.button("Force Correct", key=f"force_{issue_id}", disabled=not exact_period, use_container_width=True):
                                st.session_state["fix_mode"] = f"force:{issue_id}"

                        if st.session_state.get("fix_mode") == f"manual:{issue_id}":
                            st.markdown("**Enter corrected numeric value**")
                            value_text = st.text_input("Correct value", key=f"value_{issue_id}", placeholder="Example: 275300")
                            s1, s2 = st.columns([1, 1])
                            if s1.button("Save Value", key=f"save_{issue_id}", type="primary", use_container_width=True):
                                try:
                                    numeric_value = float(value_text.replace(",", "").strip())
                                    updated, log = apply_manual_value(working_df, str(issue.get("Entity", "")), period, numeric_value)
                                    st.session_state["working_df"] = updated
                                    _append_audit(log)
                                    _rerun()
                                except Exception as exc:
                                    st.error(str(exc))
                            if s2.button("Cancel", key=f"cancel_manual_{issue_id}", use_container_width=True):
                                st.session_state["fix_mode"] = ""
                                st.rerun()

                        if st.session_state.get("fix_mode") == f"force:{issue_id}":
                            st.markdown("**Force Correct — explain why this blank/value is valid**")
                            reason = st.selectbox("Reason", FORCE_REASONS, key=f"reason_{issue_id}")
                            default_scope_index = 0
                            if reason in {"Production not started yet", "Entity did not exist yet", "Covered by predecessor country", "Series intentionally starts here"}:
                                default_scope_index = 1
                            elif reason == "Series intentionally ends here":
                                default_scope_index = 2
                            scope_options = ["This period only", "This and all earlier periods", "This and all later periods"]
                            scope = st.selectbox("Apply to", scope_options, index=default_scope_index, key=f"scope_{issue_id}")
                            note = st.text_input("Optional note / predecessor name", key=f"note_{issue_id}")
                            f1, f2 = st.columns(2)
                            if f1.button("Apply Force Correct", key=f"apply_force_{issue_id}", type="primary", use_container_width=True):
                                force_period = str(issue.get("Boundary Period", period)) if source == "Coverage start/end" else period
                                override = build_force_override(str(issue.get("Entity", "")), force_period, reason, scope, note)
                                st.session_state.setdefault("force_overrides", []).append(override)
                                _resolve(issue_id, "Force Correct", f"{override['reason']} — {scope}", str(issue.get("Entity", "")), period)
                                _rerun()
                            if f2.button("Cancel", key=f"cancel_force_{issue_id}", use_container_width=True):
                                st.session_state["fix_mode"] = ""
                                st.rerun()

                # Country completion is a review convenience, not a data edit.
                entity_unresolved = unresolved[
                    unresolved["Entity"].replace("", "Dataset / Structure").fillna("Dataset / Structure").eq(entity)
                ]
                critical_left = int(entity_unresolved["Severity"].isin(["MUST FIX", "MUST CHECK"]).sum())
                if critical_left == 0 and len(entity_unresolved):
                    if st.button(f"Mark {entity} Reviewed ✓", key=f"complete_{entity}"):
                        completed = set(st.session_state.get("country_complete", set()))
                        completed.add(entity)
                        st.session_state["country_complete"] = completed
                        st.toast(f"{entity} marked reviewed.", icon="✅")

elif menu == "Historical / Expected":
    st.subheader("Historical / Expected")
    st.caption("These are protected historical blanks. They are not automatically turned into zero and no predecessor values are copied into successor countries.")
    if lifecycle_skips.empty:
        st.info("No historical/forced blank classifications are active for this dataset.")
    else:
        display_cols = [c for c in ["Entity", "Period", "Lifecycle Status", "Rule", "Why"] if c in lifecycle_skips.columns]
        st.dataframe(lifecycle_skips[display_cols], use_container_width=True, hide_index=True)
    if st.session_state.get("force_overrides"):
        st.markdown("#### Your Force Correct rules")
        st.dataframe(pd.DataFrame(st.session_state["force_overrides"]), use_container_width=True, hide_index=True)

elif menu == "Fixed / Ignored":
    st.subheader("Fixed / Ignored")
    if resolved.empty and not st.session_state.get("audit_log"):
        st.info("Nothing has been resolved or changed yet.")
    else:
        if not resolved.empty:
            st.markdown("#### Resolved review items")
            st.dataframe(resolved, use_container_width=True, hide_index=True)
        if st.session_state.get("audit_log"):
            st.markdown("#### Change log")
            st.dataframe(pd.DataFrame(st.session_state["audit_log"]), use_container_width=True, hide_index=True)

elif menu == "Download":
    st.subheader("Download")
    st.caption("The corrected workbook is restored to the original Checker/AlienArt orientation. For .xlsx files, other workbook sheets are preserved.")

    summary = {
        "File": uploaded_file.name,
        "Sheet": selected_sheet or "",
        "Layout": layout_label,
        "Frequency": orientation.frequency or "",
        "Top N": int(top_n),
        "Must Fix": must_fix,
        "Must Check": must_check,
        "Review": review_count,
        "Top-N Safety": top_n_safety,
        "Historical Expected": historical_expected,
        "Protected Transition": protected_transition,
        "User Force Correct": user_forced,
        "Safe Fill Remaining": int(len(safe_fill_candidates)),
        "Start / End Candidates": int(start_end_count),
    }

    corrected_bytes = build_corrected_workbook_bytes(
        file_bytes,
        uploaded_file.name,
        selected_sheet,
        original_df,
        working_df,
        orientation,
    )
    audit_bytes = build_audit_report_bytes(
        unresolved,
        resolved,
        st.session_state.get("audit_log", []),
        lifecycle_summary,
        safe_fill_candidates,
        summary,
        coverage_candidates,
    )

    base_name = Path(uploaded_file.name).stem
    d1, d2 = st.columns(2)
    d1.download_button(
        "DOWNLOAD CORRECTED EXCEL",
        corrected_bytes,
        file_name=f"{base_name}_Corrected.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        type="primary",
    )
    d2.download_button(
        "DOWNLOAD AUDIT REPORT",
        audit_bytes,
        file_name=f"{base_name}_Audit_Report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    if must_fix or must_check:
        st.warning("The corrected workbook can still be downloaded, but unresolved Must Fix/Must Check items remain.")
    else:
        st.success("No unresolved Must Fix or Must Check items remain.")

elif menu == "Advanced Details":
    st.subheader("Advanced Details")
    with st.expander("Original file preview"):
        st.dataframe(original_df.head(100), use_container_width=True, hide_index=True)
    with st.expander("Internal checker view"):
        st.dataframe(working_df.head(100), use_container_width=True, hide_index=True)
    with st.expander("Full unresolved findings"):
        st.dataframe(unresolved, use_container_width=True, hide_index=True)
    with st.expander("Safe Series Fill preview"):
        if safe_fill_candidates.empty:
            st.info("No safe internal gaps found.")
        else:
            st.dataframe(safe_fill_candidates, use_container_width=True, hide_index=True)
    with st.expander("Lifecycle summary"):
        st.dataframe(lifecycle_summary, use_container_width=True, hide_index=True)
    st.json({
        "filename": uploaded_file.name,
        "sheet": selected_sheet,
        "layout": orientation.orientation,
        "detection_confidence": round(float(orientation.confidence), 4),
        "frequency": orientation.frequency,
        "recognized_periods": len(result.period_columns),
        "entities": len(working_df),
        "top_n": int(top_n),
        "top_n_safety": top_n_safety,
        "historical_expected": historical_expected,
        "protected_transition": protected_transition,
        "user_force_correct": user_forced,
        "safe_fill_candidates": len(safe_fill_candidates),
        "start_end_candidates": int(start_end_count),
    })

