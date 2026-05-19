"""
Enterprise Data Quality Observability Platform — Operational Dashboard
Run: streamlit run ui/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import httpx
import pandas as pd
import streamlit as st
from datetime import datetime

# ── Page Config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DQ Observability Platform",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Enterprise CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* ── Global typography ─────────────────────────────────── */
    html, body, [class*="css"] { font-family: 'Inter', 'Segoe UI', sans-serif; }

    /* ── Sidebar ────────────────────────────────────────────── */
    section[data-testid="stSidebar"] { background: #f8fafc; border-right: 1px solid #e2e8f0; }
    section[data-testid="stSidebar"] .stRadio > label { font-size: 0.9rem; font-weight: 600; color: #475569; }
    section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label { font-size: 0.88rem; color: #1e293b; }

    /* ── Page header ────────────────────────────────────────── */
    .page-header {
        font-size: 1.6rem;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 0.25rem;
        letter-spacing: -0.5px;
    }
    .page-sub {
        font-size: 0.82rem;
        color: #64748b;
        margin-bottom: 1.5rem;
    }

    /* ── Section card ───────────────────────────────────────── */
    .section-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1.25rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .section-title {
        font-size: 0.95rem;
        font-weight: 600;
        color: #1e293b;
        margin-bottom: 0.75rem;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }

    /* ── Rule badges ────────────────────────────────────────── */
    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.3px;
    }
    .badge-tech  { background: #dbeafe; color: #1d4ed8; }
    .badge-biz   { background: #ede9fe; color: #7c3aed; }
    .badge-fail  { background: #fee2e2; color: #dc2626; }
    .badge-warn  { background: #fef3c7; color: #d97706; }
    .badge-info  { background: #dcfce7; color: #16a34a; }
    .badge-pass  { background: #dcfce7; color: #16a34a; }

    /* ── Health pill ────────────────────────────────────────── */
    .health-healthy  { background: #dcfce7; color: #15803d; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }
    .health-at-risk  { background: #fef3c7; color: #b45309; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }
    .health-breach   { background: #fee2e2; color: #dc2626; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }

    /* ── Workflow stepper ───────────────────────────────────── */
    .step-done   { color: #16a34a; font-weight: 600; font-size: 0.82rem; }
    .step-active { color: #2563eb; font-weight: 600; font-size: 0.82rem; }
    .step-todo   { color: #94a3b8; font-size: 0.82rem; }

    /* ── KPI metric overrides ───────────────────────────────── */
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; font-weight: 700; }
    [data-testid="stMetricLabel"] { font-size: 0.78rem !important; color: #64748b; }

    /* ── Hide Streamlit branding only — keep nav controls intact ── */
    #MainMenu  { visibility: hidden; }
    footer     { visibility: hidden; }
    [data-testid="stToolbar"]    { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }

    /* ── Dataframe ──────────────────────────────────────────── */
    .stDataFrame thead tr th {
        background: #f8fafc !important;
        color: #475569 !important;
        font-size: 0.78rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.4px !important;
    }

    /* ── Primary button ─────────────────────────────────────── */
    .stButton > button[kind="primary"] {
        background: #2563eb;
        border: none;
        border-radius: 6px;
        font-weight: 600;
        letter-spacing: 0.2px;
        padding: 0.45rem 1.25rem;
    }
    .stButton > button[kind="primary"]:hover { background: #1d4ed8; }

    /* ── Info / warning boxes ───────────────────────────────── */
    .stAlert { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# ── Constants ──────────────────────────────────────────────────────────────────
API_URL = os.getenv("DQ_API_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "rickytokens")
_HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

SEV_ICON = {"FAIL": "🔴", "WARN": "🟡", "INFO": "🟢", "PASS": "✅"}
SEV_BADGE = {
    "FAIL": "badge badge-fail",
    "WARN": "badge badge-warn",
    "INFO": "badge badge-info",
    "PASS": "badge badge-pass",
}


# ── API helpers ────────────────────────────────────────────────────────────────
def _extract_error(exc: Exception) -> str:
    if hasattr(exc, "response"):
        try:
            body = exc.response.json()
            return body.get("detail") or body.get("error") or str(exc)
        except Exception:
            pass
    return str(exc)


def api_get(path: str, timeout: int = 60) -> dict:
    try:
        r = httpx.get(f"{API_URL}{path}", headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"success": False, "error": _extract_error(exc)}


def api_post(path: str, body: dict, timeout: int = 300) -> dict:
    try:
        r = httpx.post(f"{API_URL}{path}", json=body, headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"success": False, "error": _extract_error(exc)}


def api_put(path: str, body: dict, timeout: int = 30) -> dict:
    try:
        r = httpx.put(f"{API_URL}{path}", json=body, headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"success": False, "error": _extract_error(exc)}


def api_delete(path: str, params: dict | None = None, timeout: int = 10) -> dict:
    try:
        r = httpx.delete(f"{API_URL}{path}", headers=_HEADERS, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"success": False, "error": _extract_error(exc)}


# ── Sidebar navigation ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⬡ DQ Platform")
    st.caption("Enterprise Data Quality")
    st.divider()
    page = st.radio(
        "Navigation",
        ["🚀 New Workflow", "📋 Rules Manager", "✅ Approvals", "📊 Observability", "⚙️ Settings"],
    )
    st.divider()
    if st.session_state.get("session_id"):
        st.caption("Active session")
        st.code(st.session_state.session_id[:30], language=None)
    else:
        st.caption("No active session")
    st.caption(f"API: {API_URL}")


# ══════════════════════════════════════════════════════════════════════
# PAGE: NEW WORKFLOW
# ══════════════════════════════════════════════════════════════════════
if page == "🚀 New Workflow":
    st.markdown('<div class="page-header">New DQ Workflow</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Configure target tables and kick off rule generation.</div>',
                unsafe_allow_html=True)

    if "session_id" not in st.session_state:
        st.session_state.session_id = None
    if "workflow_stage" not in st.session_state:
        st.session_state.workflow_stage = None

    # ── Step 1: Discovery ──────────────────────────────────────────────
    st.markdown("#### Step 1 — Configure Target Tables")
    with st.form("discovery_form"):
        col_a, col_b = st.columns(2)
        project_id = col_a.text_input("GCP Project ID", placeholder="my-gcp-project")
        dataset_id = col_b.text_input("BigQuery Dataset", placeholder="my_dataset")
        table_names_raw = st.text_area(
            "Table Names (one per line or comma-separated)",
            placeholder="customers\norders\ntransactions",
            height=80,
        )
        col1, col2 = st.columns(2)
        include_tech = col1.checkbox(
            "Generate Technical Rules",
            value=True,
            help="Null checks, uniqueness, type validation, freshness, volume, etc.",
        )
        include_biz = col2.checkbox(
            "Generate Business Rules",
            value=True,
            help="AI-inferred domain rules: cross-column constraints, SLA rules, business logic.",
        )
        if not include_biz:
            st.caption(
                "ℹ️ Business rule generation is disabled. "
                "Only metadata-driven technical checks will be produced."
            )
        submit_discovery = st.form_submit_button("Run Metadata Discovery", type="primary")

    if submit_discovery:
        if not project_id or not dataset_id or not table_names_raw:
            st.error("All fields are required.")
        else:
            table_names = [t.strip() for t in table_names_raw.replace(",", "\n").splitlines() if t.strip()]
            with st.spinner("Scanning BigQuery schema and profiling tables..."):
                resp = api_post("/api/v1/discovery/start", {
                    "project_id": project_id,
                    "dataset_id": dataset_id,
                    "table_names": table_names,
                })
            if resp.get("success"):
                data = resp["data"]
                st.session_state.session_id = data["session_id"]
                st.session_state.workflow_stage = "discovered"
                st.session_state.include_tech = include_tech
                st.session_state.include_biz = include_biz
                st.success(f"Discovery complete — session `{data['session_id']}`")
                st.json(data)
            else:
                st.error(f"Discovery failed: {resp.get('error', 'Unknown error')}")

    # ── Step 2: Rule Generation ────────────────────────────────────────
    if st.session_state.get("session_id") and st.session_state.get("workflow_stage") == "discovered":
        st.divider()
        st.markdown("#### Step 2 — Generate DQ Rules")
        inc_t = st.session_state.get("include_tech", True)
        inc_b = st.session_state.get("include_biz", True)
        label_parts = []
        if inc_t:
            label_parts.append("technical")
        if inc_b:
            label_parts.append("AI business")
        st.caption(f"Will generate: **{' + '.join(label_parts)} rules**")

        if st.button("Generate Rules", type="primary"):
            with st.spinner("Rule Intelligence Engine analysing schema..."):
                resp = api_post("/api/v1/rules/generate", {
                    "session_id": st.session_state.session_id,
                    "include_technical": inc_t,
                    "include_business": inc_b,
                })
            if resp.get("success"):
                data = resp["data"]
                st.session_state.workflow_stage = "rules_generated"
                c1, c2, c3 = st.columns(3)
                c1.metric("Technical Rules", data.get("technical_rules", 0))
                c2.metric("Business Rules", data.get("business_rules", 0))
                c3.metric("Total Rules", data.get("total_rules", 0))
                st.success(f"{data.get('total_rules', 0)} rules generated.")
                st.info("Go to **Rules Manager** to review, approve, or remove rules before submission.")
            else:
                st.error(f"Rule generation failed: {resp.get('error', 'Unknown error')}")


# ══════════════════════════════════════════════════════════════════════
# PAGE: RULES MANAGER
# ══════════════════════════════════════════════════════════════════════
elif page == "📋 Rules Manager":
    st.markdown('<div class="page-header">Rules Manager</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-sub">Review, select, and manage generated DQ rules before approval.</div>',
        unsafe_allow_html=True,
    )

    session_id = st.text_input(
        "Session ID",
        value=st.session_state.get("session_id", ""),
        placeholder="session_abc123",
    )
    if not session_id:
        st.info("Enter a session ID to manage rules.")
        st.stop()

    resp = api_get(f"/api/v1/rules/{session_id}")
    if not resp.get("success"):
        st.error(f"Error loading rules: {resp.get('error')}")
        st.stop()

    all_rules: list[dict] = resp.get("data", {}).get("rules", [])
    if not all_rules:
        st.info("No rules found for this session. Run rule generation first.")
        st.stop()

    tech_rules = [r for r in all_rules if r.get("source") == "technical"]
    biz_rules  = [r for r in all_rules if r.get("source") == "business"]

    # ── Selection state ────────────────────────────────────────────────
    sel_key = f"selections_{session_id}"
    if sel_key not in st.session_state:
        st.session_state[sel_key] = {r["rule_id"]: r.get("is_active", True) for r in all_rules}

    deleted_key = f"deleted_{session_id}"
    if deleted_key not in st.session_state:
        st.session_state[deleted_key] = set()

    def _render_rule_section(rules: list[dict], section_title: str, icon: str, badge_cls: str) -> None:
        """Render a rule section with per-rule select/delete actions."""
        visible = [r for r in rules if r["rule_id"] not in st.session_state[deleted_key]]
        selected_count = sum(1 for r in visible if st.session_state[sel_key].get(r["rule_id"], True))

        st.markdown(
            f'<div class="section-title">{icon} {section_title} '
            f'<span class="badge {badge_cls}">{len(visible)} rules</span></div>',
            unsafe_allow_html=True,
        )

        if not visible:
            st.caption("No rules in this category.")
            return

        # Quick-select controls
        qc1, qc2, _ = st.columns([1, 1, 6])
        if qc1.button("Select All", key=f"sel_all_{badge_cls}"):
            for r in visible:
                st.session_state[sel_key][r["rule_id"]] = True
            st.rerun()
        if qc2.button("Deselect All", key=f"desel_all_{badge_cls}"):
            for r in visible:
                st.session_state[sel_key][r["rule_id"]] = False
            st.rerun()

        # Per-rule rows
        for rule in visible:
            rid = rule["rule_id"]
            sev = rule.get("severity", "INFO")
            sev_icon = SEV_ICON.get(sev, "⚪")
            col_check, col_name, col_cat, col_sev, col_col, col_sql, col_del = st.columns(
                [0.04, 0.28, 0.14, 0.09, 0.14, 0.09, 0.06]
            )
            with col_check:
                new_val = st.checkbox(
                    "incl",
                    value=st.session_state[sel_key].get(rid, True),
                    key=f"cb_{rid}",
                    label_visibility="collapsed",
                )
                st.session_state[sel_key][rid] = new_val
            with col_name:
                st.markdown(
                    f'<span style="font-size:0.82rem;font-weight:{"600" if new_val else "400"};'
                    f'color:{"#1e293b" if new_val else "#94a3b8"}">{rule["rule_name"]}</span>',
                    unsafe_allow_html=True,
                )
                if rule.get("description"):
                    st.caption(rule["description"][:70] + ("…" if len(rule.get("description", "")) > 70 else ""))
            with col_cat:
                st.caption(rule.get("category", "—"))
            with col_sev:
                st.markdown(
                    f'<span class="badge {SEV_BADGE.get(sev, "badge")}">{sev_icon} {sev}</span>',
                    unsafe_allow_html=True,
                )
            with col_col:
                st.caption(rule.get("column") or "—")
            with col_sql:
                st.markdown(
                    "✅" if rule.get("has_sql") else "⏳",
                    unsafe_allow_html=True,
                )
            with col_del:
                if st.button("🗑", key=f"del_{rid}", help="Remove this rule"):
                    st.session_state[deleted_key].add(rid)
                    st.session_state[sel_key].pop(rid, None)
                    st.rerun()

        st.caption(f"{selected_count} / {len(visible)} selected")

    # ── Column headers ─────────────────────────────────────────────────
    h1, h2, h3, h4, h5, h6, h7 = st.columns([0.04, 0.28, 0.14, 0.09, 0.14, 0.09, 0.06])
    for col, label in zip([h1, h2, h3, h4, h5, h6, h7],
                          ["", "Rule", "Category", "Sev.", "Column", "SQL", ""]):
        col.markdown(
            f'<div style="font-size:0.72rem;font-weight:600;color:#64748b;text-transform:uppercase;'
            f'letter-spacing:0.4px">{label}</div>',
            unsafe_allow_html=True,
        )

    # ── Technical Rules ────────────────────────────────────────────────
    with st.container():
        _render_rule_section(tech_rules, "Technical DQ Rules", "🔧", "badge-tech")

    st.divider()

    # ── Business Rules ─────────────────────────────────────────────────
    with st.container():
        _render_rule_section(biz_rules, "Business DQ Rules", "💼", "badge-biz")

    st.divider()

    # ── Add Custom SQL Rule ────────────────────────────────────────────
    st.divider()
    with st.expander("➕ Add Custom SQL Rule"):
        st.caption(
            "Write your own BigQuery SQL validation. "
            "Use `@run_id` in your SELECT to pass the execution run ID. "
            "Your SQL must INSERT into `dq_results` or be a SELECT that the platform wraps."
        )
        with st.form("custom_rule_form"):
            cr_c1, cr_c2 = st.columns(2)
            cr_name = cr_c1.text_input("Rule Name *", placeholder="Revenue must be non-negative")
            cr_table = cr_c2.text_input("Table Name", placeholder="orders")
            cr_c3, cr_c4, cr_c5 = st.columns(3)
            cr_cat = cr_c3.selectbox("Category", ["validity", "completeness", "uniqueness",
                                                   "integrity", "freshness", "volume", "consistency"])
            cr_sev = cr_c4.selectbox("Severity", ["FAIL", "WARN", "INFO"])
            cr_col = cr_c5.text_input("Column (optional)", placeholder="amount")
            cr_desc = st.text_input("Description", placeholder="Checks that revenue is always >= 0")
            cr_sql = st.text_area(
                "Custom SQL *",
                height=160,
                placeholder=(
                    "INSERT INTO `{project}.{dq_dataset}.dq_results`\n"
                    "  (run_id, rule_id, project_id, dataset_name, table_name, column_name,\n"
                    "   rule_type, severity, status, observed_value, expected_value,\n"
                    "   threshold_value, failure_count, execution_time, created_at)\n"
                    "SELECT\n"
                    "  @run_id, 'CUST_xxxx', 'project', 'dataset', 'orders', 'amount',\n"
                    "  'validity', 'FAIL',\n"
                    "  CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,\n"
                    "  CAST(COUNT(*) AS STRING), '0', '0',\n"
                    "  COUNT(*), CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()\n"
                    "FROM `project.dataset.orders` WHERE amount < 0"
                ),
            )
            add_btn = st.form_submit_button("Add Custom Rule", type="primary")

        if add_btn:
            if not cr_name or not cr_sql:
                st.error("Rule Name and Custom SQL are required.")
            else:
                resp = api_post("/api/v1/rules/add-custom", {
                    "session_id": session_id,
                    "rule_name": cr_name,
                    "category": cr_cat,
                    "severity": cr_sev,
                    "column_name": cr_col or None,
                    "table_name": cr_table,
                    "description": cr_desc,
                    "custom_sql": cr_sql,
                })
                if resp.get("success"):
                    st.success(
                        f"Custom rule `{resp['data']['rule_id']}` added. "
                        "Refresh the page to see it in the rule list."
                    )
                    st.session_state.pop(sel_key, None)
                    st.session_state.pop(deleted_key, None)
                    st.rerun()
                else:
                    st.error(f"Failed: {resp.get('error')}")

    # ── Summary & Sync ─────────────────────────────────────────────────
    all_visible = [r for r in all_rules if r["rule_id"] not in st.session_state[deleted_key]]
    total_selected = sum(1 for r in all_visible if st.session_state[sel_key].get(r["rule_id"], True))

    sum_c1, sum_c2 = st.columns([3, 1])
    sum_c1.markdown(
        f'<span style="font-size:0.9rem;font-weight:600;color:#1e293b">'
        f'{total_selected} rules selected</span> '
        f'<span style="font-size:0.82rem;color:#64748b">of {len(all_visible)} active</span>',
        unsafe_allow_html=True,
    )

    if sum_c2.button("Save Selections →", type="primary", use_container_width=True):
        errors = []
        for rid in st.session_state[deleted_key]:
            r = api_delete(f"/api/v1/rules/{rid}", params={"session_id": session_id})
            if not r.get("success"):
                errors.append(rid)

        for rule in all_visible:
            rid = rule["rule_id"]
            new_active = st.session_state[sel_key].get(rid, True)
            if new_active != rule.get("is_active", True):
                api_put(f"/api/v1/rules/{rid}", {"session_id": session_id, "is_active": new_active})

        if errors:
            st.warning(f"Some rules could not be removed: {errors}")
        else:
            st.success(f"Selections saved — {total_selected} rules will proceed to SQL generation.")
            st.info("Go to **Approvals** to submit Checkpoint 1.")


# ══════════════════════════════════════════════════════════════════════
# PAGE: APPROVALS
# ══════════════════════════════════════════════════════════════════════
elif page == "✅ Approvals":
    st.markdown('<div class="page-header">Approval Checkpoints</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-sub">Human-in-the-loop gates for rule approval and execution governance.</div>',
        unsafe_allow_html=True,
    )

    session_id = st.text_input(
        "Session ID",
        value=st.session_state.get("session_id", ""),
        placeholder="session_abc123",
    )
    if not session_id:
        st.info("Enter a session ID to manage approvals.")
        st.stop()

    status_resp = api_get(f"/api/v1/approvals/{session_id}")
    appr_data   = status_resp.get("data", {}) if status_resp.get("success") else {}
    cp1         = appr_data.get("approval_1_status", "pending")
    cp2         = appr_data.get("approval_2_status", "pending")
    cur_stage   = appr_data.get("current_stage", "init")

    # ── Workflow stepper ───────────────────────────────────────────────
    STAGES = [
        ("Discovery", cur_stage not in ("init",)),
        ("Rules Generated", cur_stage not in ("init", "metadata_discovery", "technical_rules", "business_rules")),
        ("CP1 Approved", cp1 == "approved"),
        ("SQL Generated", cp1 == "approved"),
        ("CP2 Approved", cp2 == "approved"),
        ("Complete", cur_stage == "complete"),
    ]
    cols = st.columns(len(STAGES))
    for i, (col, (label, done)) in enumerate(zip(cols, STAGES)):
        if done:
            col.markdown(f'<div class="step-done">✓ {label}</div>', unsafe_allow_html=True)
        elif i == next((j for j, (_, d) in enumerate(STAGES) if not d), len(STAGES)):
            col.markdown(f'<div class="step-active">▶ {label}</div>', unsafe_allow_html=True)
        else:
            col.markdown(f'<div class="step-todo">○ {label}</div>', unsafe_allow_html=True)

    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # CHECKPOINT 1
    # ══════════════════════════════════════════════════════════════════
    status_label = {"approved": "✅ APPROVED", "rejected": "❌ REJECTED",
                    "modified": "🔄 MODIFIED", "pending": "⏳ PENDING"}.get(cp1, "⏳ PENDING")
    st.markdown(f"#### Checkpoint 1 — Rule Set Approval &nbsp; `{status_label}`",
                unsafe_allow_html=True)

    rules_resp = api_get(f"/api/v1/rules/{session_id}")
    rules = rules_resp.get("data", {}).get("rules", []) if rules_resp.get("success") else []
    active_rules = [r for r in rules if r.get("is_active", True)]

    if rules:
        tech_r = [r for r in active_rules if r.get("source") == "technical"]
        biz_r  = [r for r in active_rules if r.get("source") == "business"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Active Rules", len(active_rules))
        c2.metric("Technical", len(tech_r))
        c3.metric("Business", len(biz_r))

        with st.expander("Preview active rules"):
            if active_rules:
                df_r = pd.DataFrame(active_rules)
                disp = [c for c in ["rule_name", "source", "category", "severity", "column", "has_sql"]
                        if c in df_r.columns]
                st.dataframe(df_r[disp], use_container_width=True, height=260)
    else:
        st.info("No rules found. Run rule generation first.")

    if cp1 != "approved":
        with st.form("cp1_form"):
            approver_id = st.text_input("Approver ID / Email", placeholder="data-steward@company.com")
            decision = st.radio("Decision", ["APPROVED", "REJECTED", "MODIFIED"],
                                horizontal=True, key="cp1_dec")
            comments = st.text_area("Comments", placeholder="Rules look correct for this dataset.",
                                    key="cp1_comments")
            submitted = st.form_submit_button("Submit Checkpoint 1", type="primary")

        if submitted:
            if not approver_id:
                st.error("Approver ID is required.")
            else:
                with st.spinner(
                    "Submitting approval and auto-generating SQL + consolidated stored procedure..."
                    if decision == "APPROVED" else "Submitting..."
                ):
                    resp = api_post("/api/v1/approvals/submit", {
                        "session_id": session_id,
                        "stage": "approval_1",
                        "status": decision.lower(),
                        "approver_id": approver_id,
                        "comments": comments,
                        "rule_modifications": [],
                    })
                if resp.get("success"):
                    d = resp.get("data", {})
                    if decision == "APPROVED":
                        st.success(
                            "Checkpoint 1 approved. SQL generated and consolidated stored "
                            "procedure created in BigQuery automatically."
                        )
                        st.info(d.get("next_action", ""))
                    elif decision == "REJECTED":
                        st.error("Checkpoint 1 rejected. Workflow halted.")
                    else:
                        st.warning("Sent back for modification.")
                    st.rerun()
                else:
                    st.error(f"Submission failed: {resp.get('error')}")
    else:
        st.success("Checkpoint 1 approved — SQL generated and consolidated stored procedure ready.")
        if active_rules:
            sql_ready = sum(1 for r in active_rules if r.get("has_sql"))
            st.caption(f"SQL generated for {sql_ready} / {len(active_rules)} active rules.")

        st.divider()
        st.markdown("#### Run DQ Checks")

        tab_exec, tab_dag = st.tabs(["▶ Execute Now", "📅 Schedule via Airflow / Cloud Composer"])

        # ── Tab 1: Execute Now ─────────────────────────────────────────
        with tab_exec:
            st.caption(
                "Calls the consolidated stored procedure directly and writes results to `dq_results`."
            )
            if st.button("Execute DQ Checks", type="primary", key="exec_now_btn"):
                with st.spinner("Executing consolidated DQ stored procedure..."):
                    exec_resp = api_post("/api/v1/sql/execute", {"session_id": session_id},
                                         timeout=300)
                if exec_resp.get("success"):
                    d = exec_resp["data"]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Total Rules", d.get("total_rules", 0))
                    c2.metric("Passed", d.get("passed", 0))
                    c3.metric("Failed", d.get("failed", 0))
                    c4.metric("Pass Rate", f"{d.get('pass_rate', 0) * 100:.1f}%")
                    st.success(
                        f"Run complete — health score {d.get('health_score', 0):.0f}/100 "
                        f"in {d.get('duration_seconds', 0):.1f}s"
                    )
                    st.info("View results in the **Observability** dashboard.")
                else:
                    st.error(f"Execution failed: {exec_resp.get('error')}")

        # ── Tab 2: Schedule via DAG ────────────────────────────────────
        with tab_dag:
            st.markdown(
                "Generate an Airflow DAG that calls the consolidated stored procedure "
                "on a cron schedule. Upload the generated file to your Cloud Composer "
                "DAGs bucket to activate scheduling."
            )

            col_sched, col_owner = st.columns(2)
            schedule = col_sched.text_input(
                "Cron Schedule",
                value="0 6 * * *",
                help="Standard cron: minute hour day month weekday. E.g. '0 6 * * *' = daily at 06:00.",
            )
            owner = col_owner.text_input("DAG Owner", value="data-quality")

            common_schedules = {
                "Every day at 06:00": "0 6 * * *",
                "Every hour": "0 * * * *",
                "Every 6 hours": "0 */6 * * *",
                "Every Monday 07:00": "0 7 * * 1",
                "First of month 08:00": "0 8 1 * *",
            }
            quick = st.selectbox("Quick schedule picker", ["— custom —"] + list(common_schedules))
            if quick != "— custom —":
                schedule = common_schedules[quick]
                st.caption(f"Selected cron: `{schedule}`")

            if st.button("Generate DAG", type="primary", key="gen_dag_btn"):
                with st.spinner("Generating Airflow DAG..."):
                    dag_resp = api_post("/api/v1/monitoring/generate-dag", {
                        "session_id": session_id,
                        "schedule": schedule,
                        "owner": owner,
                    })

                if dag_resp.get("success"):
                    d = dag_resp["data"]
                    st.success(
                        f"DAG `{d['dag_id']}` generated — calls stored procedure "
                        f"`{d['sp_name']}` on schedule `{d['schedule']}`"
                    )
                    st.code(d["dag_content"], language="python")
                    st.download_button(
                        label=f"Download {d['filename']}",
                        data=d["dag_content"],
                        file_name=d["filename"],
                        mime="text/x-python",
                    )
                    st.markdown(
                        "**Next steps:**\n"
                        "1. Download the DAG file above\n"
                        "2. Upload it to your Cloud Composer DAGs bucket: "
                        "`gsutil cp {filename} gs://<composer-bucket>/dags/`\n"
                        "3. The DAG will appear in Airflow and run on the configured schedule"
                    )
                else:
                    st.error(f"DAG generation failed: {dag_resp.get('error')}")


# ══════════════════════════════════════════════════════════════════════
# PAGE: OBSERVABILITY DASHBOARD
# ══════════════════════════════════════════════════════════════════════
elif page == "📊 Observability":
    st.markdown('<div class="page-header">Observability Dashboard</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="page-sub">Live results from BigQuery views — refreshed {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC</div>',
        unsafe_allow_html=True,
    )

    # ── Toolbar ───────────────────────────────────────────────────────
    col_refresh, col_setup, col_days, _ = st.columns([1, 1.4, 1.2, 4])
    if col_refresh.button("Refresh", use_container_width=True):
        st.rerun()
    if col_setup.button("Create / Refresh Views", use_container_width=True):
        with st.spinner("Creating reporting views in BigQuery..."):
            setup_resp = api_post("/api/v1/reporting/setup-views", {})
        if setup_resp.get("success"):
            d = setup_resp.get("data", {})
            st.success(f"{d.get('created', 0)}/{d.get('total', 0)} views created successfully.")
        else:
            st.error(f"View setup failed: {setup_resp.get('error')}")
        st.rerun()
    trend_days = col_days.selectbox("Trend window", [7, 14, 30], index=2, label_visibility="collapsed")

    st.divider()

    # ── KPI Row ───────────────────────────────────────────────────────
    kpi_resp = api_get("/api/v1/reporting/kpi")
    kpi = kpi_resp.get("data", {}) if kpi_resp.get("success") else {}

    c1, c2, c3, c4 = st.columns(4)
    if kpi:
        pass_rate = kpi.get("pass_rate_pct", 0)
        health    = kpi.get("health_score", 0)
        critical  = kpi.get("critical_failures", 0)
        total     = kpi.get("total_checks", 0)

        c1.metric("Pass Rate", f"{pass_rate:.1f}%", delta=f"{pass_rate - 80:.1f}% vs 80% target")
        c2.metric(
            "Health Score",
            f"{health:.0f} / 100",
            delta_color="normal" if health >= 80 else "inverse",
        )
        c3.metric("Critical Failures", str(critical), delta_color="inverse" if critical > 0 else "off")
        c4.metric("Total Checks", str(total))
    else:
        for col, lbl in zip([c1, c2, c3, c4], ["Pass Rate", "Health Score", "Critical Failures", "Total Checks"]):
            col.metric(lbl, "—")
        st.info(
            "No execution data yet. Run DQ checks from the **Approvals** page to populate this dashboard.",
            icon="ℹ️",
        )

    st.divider()

    # ── Table Health + Trend ──────────────────────────────────────────
    col_health, col_trend = st.columns([3, 2])

    with col_health:
        st.markdown("**Table Health Scores** — from `v_dq_table_health`")
        health_resp = api_get("/api/v1/reporting/health")
        health_data = health_resp.get("data", {}).get("tables", []) if health_resp.get("success") else []
        if health_data:
            df_h = pd.DataFrame(health_data)
            if "health_score" in df_h.columns:
                df_h = df_h.sort_values("health_score", ascending=True)
            show_cols = [c for c in [
                "table_name", "health_score", "pass_rate_pct",
                "total_checks", "passed", "failed",
                "critical_failures", "hours_since_last_run",
            ] if c in df_h.columns]
            st.dataframe(df_h[show_cols], use_container_width=True, height=280)

            total_failed = sum(t.get("failed", 0) for t in health_data)
            if total_failed == 0:
                st.success(f"All checks passing across {len(health_data)} table(s).")
            else:
                st.error(f"{total_failed} active failure(s) across {len(health_data)} table(s).")
        else:
            st.caption("No table health data. Views may need to be created or DQ checks haven't run yet.")

    with col_trend:
        st.markdown(f"**Pass Rate Trend ({trend_days}d)** — from `v_dq_trend_analysis`")
        trend_resp = api_get(f"/api/v1/reporting/trends?days={trend_days}")
        trend_data = trend_resp.get("data", {}).get("trends", []) if trend_resp.get("success") else []
        if trend_data:
            df_t = pd.DataFrame(trend_data)
            if "run_date" in df_t.columns and "pass_rate_pct" in df_t.columns:
                df_t["run_date"] = pd.to_datetime(df_t["run_date"])
                pivot = df_t.groupby("run_date")["pass_rate_pct"].mean().reset_index()
                st.line_chart(pivot.set_index("run_date")["pass_rate_pct"], height=260)
        else:
            st.caption("No trend data available yet.")

    st.divider()

    # ── Active Failures ────────────────────────────────────────────────
    st.markdown("**Active Failures (last 7 days)** — from `v_dq_failed_rules`")
    failed_resp = api_get("/api/v1/reporting/failed-rules")
    failed_data = failed_resp.get("data", {}).get("rules", []) if failed_resp.get("success") else []

    if failed_data:
        df_f = pd.DataFrame(failed_data)
        show_f = [c for c in [
            "severity", "table_name", "column_name", "rule_type", "rule_id",
            "observed_value", "expected_value", "failure_count",
            "hours_open", "execution_time",
        ] if c in df_f.columns]

        # Colour-code severity column if present
        def _sev_style(val: str) -> str:
            colours = {"FAIL": "background-color:#fee2e2;color:#dc2626",
                       "WARN": "background-color:#fef3c7;color:#d97706"}
            return colours.get(val, "")

        if "severity" in df_f.columns:
            st.dataframe(
                df_f[show_f].style.applymap(_sev_style, subset=["severity"]),
                use_container_width=True,
                height=300,
            )
        else:
            st.dataframe(df_f[show_f], use_container_width=True, height=300)

        crit = sum(1 for r in failed_data if r.get("severity") == "FAIL")
        warns = sum(1 for r in failed_data if r.get("severity") == "WARN")
        st.caption(f"{len(failed_data)} open failure(s) — {crit} critical, {warns} warnings")
    else:
        st.success("No active failures in the last 7 days.")

    st.divider()

    # ── Freshness Report ───────────────────────────────────────────────
    st.markdown("**Data Freshness** — from `v_dq_freshness_report`")
    fresh_resp = api_get("/api/v1/reporting/freshness")
    fresh_data = fresh_resp.get("data", {}).get("tables", []) if fresh_resp.get("success") else []

    if fresh_data:
        df_fr = pd.DataFrame(fresh_data)
        show_fr = [c for c in [
            "table_name", "freshness_health", "sla_status",
            "current_lag_hours", "sla_max_lag_hours", "last_checked_at",
        ] if c in df_fr.columns]

        def _fresh_style(val: str) -> str:
            colours = {
                "HEALTHY": "background-color:#dcfce7;color:#15803d",
                "AT_RISK": "background-color:#fef3c7;color:#b45309",
                "SLA_BREACH": "background-color:#fee2e2;color:#dc2626",
            }
            return colours.get(val, "")

        if "freshness_health" in df_fr.columns:
            st.dataframe(
                df_fr[show_fr].style.applymap(_fresh_style, subset=["freshness_health"]),
                use_container_width=True,
                height=220,
            )
        else:
            st.dataframe(df_fr[show_fr], use_container_width=True, height=220)
    else:
        st.caption("No freshness data available yet.")


# ══════════════════════════════════════════════════════════════════════
# PAGE: SETTINGS
# ══════════════════════════════════════════════════════════════════════
elif page == "⚙️ Settings":
    st.markdown('<div class="page-header">Platform Settings</div>', unsafe_allow_html=True)

    with st.expander("API Connection", expanded=True):
        st.text_input("API Base URL", value=API_URL)
        st.text_input("API Key", value=API_KEY, type="password")
        if st.button("Test Connection"):
            try:
                r = httpx.get(f"{API_URL}/health", headers=_HEADERS, timeout=5)
                if r.status_code == 200:
                    st.success(f"Connected — {r.json()}")
                else:
                    st.error(f"HTTP {r.status_code}")
            except Exception as exc:
                st.error(f"Connection failed: {exc}")

    with st.expander("Session Management"):
        st.code(st.session_state.get("session_id") or "No active session")
        if st.button("Clear Session"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    with st.expander("About"):
        st.markdown("""
        **Enterprise DQ Observability Platform v2.0**

        | Component | Details |
        |-----------|---------|
        | AI Engine | Rule Intelligence Engine (generative model) |
        | Data Warehouse | Google BigQuery |
        | Orchestration | Multi-agent pipeline |
        | API | FastAPI + Pydantic v2 |
        | Dashboard | Streamlit |
        | SP Strategy | Consolidated per-session stored procedure |

        Built for production data quality governance in enterprise environments.
        """)
