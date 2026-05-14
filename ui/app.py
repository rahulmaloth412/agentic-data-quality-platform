"""
Agentic DQ Observability Platform — Operational Dashboard
Run: streamlit run ui/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import httpx
import streamlit as st
from datetime import datetime

# ── Page Config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DQ Observability Platform",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Shared state keys ──────────────────────────────────────────────────────────
API_URL = os.getenv("DQ_API_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "changeme")
_HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}


# ── Helpers ────────────────────────────────────────────────────────────────────
def api_get(path: str) -> dict:
    try:
        r = httpx.get(f"{API_URL}{path}", headers=_HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def api_post(path: str, body: dict) -> dict:
    try:
        r = httpx.post(f"{API_URL}{path}", json=body, headers=_HEADERS, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def severity_badge(sev: str) -> str:
    colors = {"FAIL": "#dc3545", "WARN": "#ffc107", "INFO": "#28a745", "PASS": "#28a745"}
    return f'<span style="background:{colors.get(sev,"#6c757d")};color:white;padding:2px 8px;border-radius:3px;font-size:12px;font-weight:bold">{sev}</span>'


# ── Sidebar navigation ─────────────────────────────────────────────────────────
st.sidebar.image("https://img.icons8.com/color/96/database-restore.png", width=60)
st.sidebar.title("DQ Platform")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Navigate",
    ["🏠 Dashboard", "🔍 New DQ Workflow", "📋 Rules Manager", "✅ Approvals", "📊 Reports", "⚙️ Settings"],
    label_visibility="collapsed",
)
st.sidebar.markdown("---")
st.sidebar.caption(f"API: `{API_URL}`")


# ══════════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ══════════════════════════════════════════════════════════════════════
if page == "🏠 Dashboard":
    st.title("🔍 Data Quality Observability Dashboard")
    st.caption(f"Last refreshed: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    # ── KPI Metrics row ────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)

    kpi_resp = api_get("/api/v1/reporting/kpi")
    kpi = kpi_resp.get("data", {}) if kpi_resp.get("success") else {}

    if kpi:
        col1.metric("Overall Pass Rate", f"{kpi.get('pass_rate_pct', 0):.1f}%",
                    delta=f"{kpi.get('pass_rate_pct', 0) - 80:.1f}% vs target")
        col2.metric("Health Score", f"{kpi.get('health_score', 0):.0f}/100")
        col3.metric("Critical Failures", str(kpi.get("critical_failures", 0)),
                    delta_color="inverse")
        col4.metric("Total Checks", str(kpi.get("total_checks", 0)))
    else:
        for col, label, val in [
            (col1, "Overall Pass Rate", "—"),
            (col2, "Health Score", "—"),
            (col3, "Critical Failures", "—"),
            (col4, "Total Checks", "—"),
        ]:
            col.metric(label, val)
        st.info("No KPI data available yet. Run a DQ workflow first.", icon="ℹ️")

    st.divider()

    # ── Table Health ───────────────────────────────────────────────────
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("Table Health Scores")
        health_resp = api_get("/api/v1/reporting/health")
        health_data = health_resp.get("data", {}).get("tables", []) if health_resp.get("success") else []

        if health_data:
            import pandas as pd
            df = pd.DataFrame(health_data)
            if "health_score" in df.columns:
                df = df.sort_values("health_score", ascending=True)

            st.dataframe(
                df[["table_name", "health_score", "pass_rate_pct", "failed", "critical_failures", "hours_since_last_run"]]
                if all(c in df.columns for c in ["table_name", "health_score", "pass_rate_pct", "failed"])
                else df,
                use_container_width=True,
                height=350,
            )
        else:
            st.info("No table health data available.")

    with col_right:
        st.subheader("Pass Rate Trend")
        trend_resp = api_get("/api/v1/reporting/trends?days=7")
        trend_data = trend_resp.get("data", {}).get("trends", []) if trend_resp.get("success") else []

        if trend_data:
            import pandas as pd
            df_trend = pd.DataFrame(trend_data)
            if "run_date" in df_trend.columns and "pass_rate_pct" in df_trend.columns:
                df_trend["run_date"] = pd.to_datetime(df_trend["run_date"])
                pivot = df_trend.groupby("run_date")["pass_rate_pct"].mean().reset_index()
                st.line_chart(pivot.set_index("run_date")["pass_rate_pct"])
            else:
                st.info("Trend data not in expected format.")
        else:
            st.info("No trend data available yet.")

    # ── Failed Rules ───────────────────────────────────────────────────
    st.subheader("Active Failures")

    if health_data:
        total_failed = sum(t.get("failed", 0) for t in health_data)
        if total_failed == 0:
            st.success(f"✅ All checks passing across {len(health_data)} table(s).")
        else:
            st.error(f"⚠️ {total_failed} active failure(s) across {len(health_data)} table(s).")
    else:
        st.caption("Run a DQ workflow to see failures here.")


# ══════════════════════════════════════════════════════════════════════
# PAGE: NEW DQ WORKFLOW
# ══════════════════════════════════════════════════════════════════════
elif page == "🔍 New DQ Workflow":
    st.title("🔍 Start New DQ Workflow")
    st.markdown("Kick off a full metadata discovery and rule generation session.")

    if "session_id" not in st.session_state:
        st.session_state.session_id = None
    if "workflow_stage" not in st.session_state:
        st.session_state.workflow_stage = None

    with st.form("discovery_form"):
        st.subheader("Step 1 — Configure Target Tables")
        project_id = st.text_input("GCP Project ID", placeholder="my-gcp-project")
        dataset_id = st.text_input("BigQuery Dataset", placeholder="my_dataset")
        table_names_raw = st.text_area(
            "Table Names (one per line or comma-separated)",
            placeholder="customers\norders\ntransactions",
        )
        col1, col2 = st.columns(2)
        include_tech = col1.checkbox("Generate Technical Rules", value=True)
        include_biz = col2.checkbox("Generate Business Rules (Claude)", value=True)
        submit_discovery = st.form_submit_button("🚀 Start Discovery", type="primary")

    if submit_discovery:
        if not project_id or not dataset_id or not table_names_raw:
            st.error("All fields are required.")
        else:
            table_names = [t.strip() for t in table_names_raw.replace(",", "\n").splitlines() if t.strip()]
            with st.spinner("Running metadata discovery..."):
                resp = api_post("/api/v1/discovery/start", {
                    "project_id": project_id,
                    "dataset_id": dataset_id,
                    "table_names": table_names,
                })

            if resp.get("success"):
                data = resp["data"]
                st.session_state.session_id = data["session_id"]
                st.session_state.workflow_stage = "discovered"
                st.success(f"✅ Discovery complete! Session: `{data['session_id']}`")
                st.json(data)
            else:
                st.error(f"Discovery failed: {resp.get('error', 'Unknown error')}")

    if st.session_state.session_id and st.session_state.workflow_stage == "discovered":
        st.divider()
        st.subheader("Step 2 — Generate DQ Rules")

        if st.button("⚙️ Generate Rules", type="primary"):
            with st.spinner("Generating rules (Claude is reasoning about your data)..."):
                resp = api_post("/api/v1/rules/generate", {
                    "session_id": st.session_state.session_id,
                    "include_technical": include_tech,
                    "include_business": include_biz,
                })

            if resp.get("success"):
                data = resp["data"]
                st.session_state.workflow_stage = "rules_generated"
                st.success(f"✅ {data.get('total_rules', 0)} rules generated!")
                col1, col2, col3 = st.columns(3)
                col1.metric("Technical Rules", data.get("technical_rules", 0))
                col2.metric("Business Rules", data.get("business_rules", 0))
                col3.metric("Total Rules", data.get("total_rules", 0))
                st.info("👉 Go to **Rules Manager** to review and approve.")
            else:
                st.error(f"Rule generation failed: {resp.get('error', 'Unknown error')}")

    if st.session_state.session_id:
        st.sidebar.success(f"Active Session:\n`{st.session_state.session_id}`")


# ══════════════════════════════════════════════════════════════════════
# PAGE: RULES MANAGER
# ══════════════════════════════════════════════════════════════════════
elif page == "📋 Rules Manager":
    st.title("📋 DQ Rules Manager")

    session_id = st.text_input(
        "Session ID",
        value=st.session_state.get("session_id", ""),
        placeholder="session_abc123",
    )

    if not session_id:
        st.info("Enter a session ID to view and manage rules.")
        st.stop()

    resp = api_get(f"/api/v1/rules/{session_id}")

    if not resp.get("success"):
        st.error(f"Error loading rules: {resp.get('error')}")
        st.stop()

    rules_data = resp.get("data", {})
    rules = rules_data.get("rules", [])

    st.caption(f"Total rules: **{len(rules)}** | Session: `{session_id}`")

    if not rules:
        st.info("No rules found for this session.")
        st.stop()

    # ── Filters ────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    filter_sev = col1.multiselect("Severity", ["FAIL", "WARN", "INFO"], default=["FAIL", "WARN", "INFO"])
    filter_cat = col2.multiselect(
        "Category",
        list({r["category"] for r in rules}),
        default=list({r["category"] for r in rules}),
    )
    filter_active = col3.checkbox("Active only", value=True)

    filtered = [
        r for r in rules
        if r.get("severity") in filter_sev
        and r.get("category") in filter_cat
        and (not filter_active or r.get("is_active", True))
    ]

    st.markdown(f"Showing **{len(filtered)}** of {len(rules)} rules")

    # ── Rule table ─────────────────────────────────────────────────────
    import pandas as pd
    df = pd.DataFrame(filtered)
    if not df.empty:
        display_cols = [c for c in ["rule_id", "rule_name", "category", "severity", "table", "column", "has_sql", "is_active"] if c in df.columns]
        st.dataframe(df[display_cols], use_container_width=True, height=400)

    # ── Inline edit ────────────────────────────────────────────────────
    st.divider()
    st.subheader("Edit a Rule")

    rule_ids = [r["rule_id"] for r in filtered]
    if rule_ids:
        selected_id = st.selectbox("Select rule to edit", rule_ids)
        selected = next((r for r in filtered if r["rule_id"] == selected_id), {})

        with st.form("edit_rule_form"):
            new_severity = st.selectbox(
                "Severity",
                ["FAIL", "WARN", "INFO"],
                index=["FAIL", "WARN", "INFO"].index(selected.get("severity", "WARN")),
            )
            new_threshold = st.slider(
                "Threshold",
                min_value=0.0, max_value=1.0,
                value=float(selected.get("threshold", 0.0)),
                step=0.01,
            )
            new_active = st.checkbox("Active", value=selected.get("is_active", True))
            save_btn = st.form_submit_button("💾 Save Changes")

        if save_btn:
            upd_resp = httpx.put(
                f"{API_URL}/api/v1/rules/{selected_id}",
                json={"session_id": session_id, "severity": new_severity, "threshold": new_threshold, "is_active": new_active},
                headers=_HEADERS,
                timeout=10,
            )
            if upd_resp.status_code == 200:
                st.success(f"✅ Rule `{selected_id}` updated.")
                st.rerun()
            else:
                st.error(f"Update failed: {upd_resp.text}")


# ══════════════════════════════════════════════════════════════════════
# PAGE: APPROVALS
# ══════════════════════════════════════════════════════════════════════
elif page == "✅ Approvals":
    st.title("✅ Human Approval Checkpoints")
    st.markdown("Review and approve DQ rule sets and monitoring configurations before they go live.")

    session_id = st.text_input(
        "Session ID",
        value=st.session_state.get("session_id", ""),
        placeholder="session_abc123",
    )

    if not session_id:
        st.info("Enter a session ID to manage approvals.")
        st.stop()

    # Show current approval status
    status_resp = api_get(f"/api/v1/approvals/{session_id}")
    if status_resp.get("success"):
        data = status_resp["data"]
        col1, col2 = st.columns(2)
        col1.metric("Checkpoint 1 (Rules)", data.get("approval_1_status", "UNKNOWN"))
        col2.metric("Checkpoint 2 (Monitoring)", data.get("approval_2_status", "UNKNOWN"))

    st.divider()

    # Show rules for review
    rules_resp = api_get(f"/api/v1/rules/{session_id}")
    if rules_resp.get("success"):
        rules = rules_resp["data"].get("rules", [])

        st.subheader(f"Checkpoint 1 — Review Rule Set ({len(rules)} rules)")

        tab_fail, tab_warn, tab_info = st.tabs(["🔴 FAIL Rules", "🟡 WARN Rules", "🟢 INFO Rules"])

        for tab, sev in [(tab_fail, "FAIL"), (tab_warn, "WARN"), (tab_info, "INFO")]:
            with tab:
                filtered = [r for r in rules if r.get("severity") == sev]
                if filtered:
                    import pandas as pd
                    df = pd.DataFrame(filtered)
                    disp = [c for c in ["rule_id", "rule_name", "category", "table", "column", "threshold"] if c in df.columns]
                    st.dataframe(df[disp], use_container_width=True, height=300)
                else:
                    st.caption(f"No {sev} rules in this set.")

    # Approval form
    st.divider()
    st.subheader("Submit Approval Decision")

    with st.form("approval_form"):
        stage = st.selectbox("Checkpoint", ["approval_1", "approval_2"])
        approver_id = st.text_input("Your Email / ID", placeholder="data-steward@company.com")
        decision = st.radio("Decision", ["APPROVED", "REJECTED", "MODIFIED"], horizontal=True)
        comments = st.text_area("Comments", placeholder="Reviewed all rules. Adjusting email threshold to 0.98.")
        submit_approval = st.form_submit_button("📝 Submit Decision", type="primary")

    if submit_approval:
        if not approver_id:
            st.error("Approver ID is required.")
        else:
            with st.spinner("Submitting approval..."):
                resp = api_post("/api/v1/approvals/submit", {
                    "session_id": session_id,
                    "stage": stage,
                    "status": decision,
                    "approver_id": approver_id,
                    "comments": comments,
                    "rule_modifications": [],
                })

            if resp.get("success"):
                data = resp["data"]
                if decision == "APPROVED":
                    st.success(f"✅ {stage} approved by {approver_id}.")
                    st.info(f"Next action: {data.get('next_action', '')}")
                elif decision == "REJECTED":
                    st.error(f"❌ {stage} rejected. Workflow halted.")
                else:
                    st.warning(f"🔄 {stage} sent back for modification.")
                st.rerun()
            else:
                st.error(f"Approval submission failed: {resp.get('error')}")


# ══════════════════════════════════════════════════════════════════════
# PAGE: REPORTS
# ══════════════════════════════════════════════════════════════════════
elif page == "📊 Reports":
    st.title("📊 DQ Reporting & Analytics")

    tab_kpi, tab_health, tab_trends, tab_freshness = st.tabs([
        "Executive KPI", "Table Health", "Trend Analysis", "Freshness Report"
    ])

    # ── KPI Tab ────────────────────────────────────────────────────────
    with tab_kpi:
        st.subheader("Executive Data Quality KPI")
        kpi_resp = api_get("/api/v1/reporting/kpi")

        if kpi_resp.get("success") and kpi_resp.get("data"):
            kpi = kpi_resp["data"]
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Checks", kpi.get("total_checks", 0))
            col2.metric("Passed", kpi.get("passed_checks", 0))
            col3.metric(
                "Pass Rate",
                f"{kpi.get('pass_rate_pct', 0):.1f}%",
                delta=f"{kpi.get('pass_rate_pct', 0) - 80:.1f}% vs 80% target",
            )
            col4.metric("Health Score", f"{kpi.get('health_score', 0):.0f}/100")

            st.divider()
            col5, col6 = st.columns(2)
            col5.metric("Failed Checks", kpi.get("failed_checks", 0), delta_color="inverse")
            col6.metric("Critical Failures", kpi.get("critical_failures", 0), delta_color="inverse")
        else:
            st.info("No KPI data yet. Execute a DQ run first.")

    # ── Table Health Tab ───────────────────────────────────────────────
    with tab_health:
        st.subheader("Per-Table Health Scores")
        health_resp = api_get("/api/v1/reporting/health")

        if health_resp.get("success"):
            tables = health_resp["data"].get("tables", [])
            if tables:
                import pandas as pd
                df = pd.DataFrame(tables)

                # Health score bar chart
                if "health_score" in df.columns and "table_name" in df.columns:
                    chart_df = df[["table_name", "health_score"]].set_index("table_name")
                    st.bar_chart(chart_df)

                st.dataframe(df, use_container_width=True)
            else:
                st.info("No health data available.")
        else:
            st.error(f"Failed to load health data: {health_resp.get('error')}")

    # ── Trend Analysis Tab ─────────────────────────────────────────────
    with tab_trends:
        st.subheader("DQ Pass Rate Trends")
        days = st.slider("Days to show", 7, 90, 30)
        trend_resp = api_get(f"/api/v1/reporting/trends?days={days}")

        if trend_resp.get("success"):
            trends = trend_resp["data"].get("trends", [])
            if trends:
                import pandas as pd
                df = pd.DataFrame(trends)
                if "run_date" in df.columns and "pass_rate_pct" in df.columns:
                    df["run_date"] = pd.to_datetime(df["run_date"])
                    pivot = df.groupby(["run_date", "rule_type"])["pass_rate_pct"].mean().reset_index()
                    chart_pivot = pivot.pivot(index="run_date", columns="rule_type", values="pass_rate_pct")
                    st.line_chart(chart_pivot)
                st.dataframe(df, use_container_width=True)
            else:
                st.info(f"No trend data for the last {days} days.")
        else:
            st.error(f"Failed to load trends: {trend_resp.get('error')}")

    # ── Freshness Tab ──────────────────────────────────────────────────
    with tab_freshness:
        st.subheader("Data Freshness Report")
        st.info(
            "This view shows freshness lag per table vs. SLA target. "
            "Data is sourced from the `v_dq_freshness_report` BigQuery view."
        )

        # Would query freshness from BigQuery directly in a real deployment
        st.caption("Connect to BigQuery to populate this view, or run a DQ workflow with freshness rules enabled.")


# ══════════════════════════════════════════════════════════════════════
# PAGE: SETTINGS
# ══════════════════════════════════════════════════════════════════════
elif page == "⚙️ Settings":
    st.title("⚙️ Platform Settings")

    with st.expander("API Connection", expanded=True):
        new_url = st.text_input("API Base URL", value=API_URL)
        new_key = st.text_input("API Key", value=API_KEY, type="password")

        if st.button("Test Connection"):
            try:
                r = httpx.get(f"{new_url}/health", headers={"X-API-Key": new_key}, timeout=5)
                if r.status_code == 200:
                    st.success(f"✅ Connected: {r.json()}")
                else:
                    st.error(f"HTTP {r.status_code}: {r.text}")
            except Exception as exc:
                st.error(f"Connection failed: {exc}")

    with st.expander("Active Session"):
        st.code(st.session_state.get("session_id") or "No active session")
        if st.button("Clear Session"):
            st.session_state.session_id = None
            st.session_state.workflow_stage = None
            st.rerun()

    with st.expander("About"):
        st.markdown("""
        **Agentic DQ Observability Platform v1.0**

        - **AI Engine:** Claude API (`claude-sonnet-4-6`)
        - **Data Warehouse:** Google BigQuery
        - **Orchestration:** LangGraph multi-agent pipeline
        - **API:** FastAPI + Pydantic v2
        - **Dashboard:** Streamlit

        Built for production data quality governance in enterprise environments.
        """)
