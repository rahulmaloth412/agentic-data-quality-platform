"""Airflow DAG generation and injection logic for DQ orchestration."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Optional


def generate_standalone_dag(
    session_id: str,
    rules: list[dict[str, Any]],
    schedule: str,
    gcp_project: str,
    gcp_dataset: str,
    dq_dataset: str = "dq_observability",
    owner: str = "data-quality",
) -> str:
    """Generate a complete Airflow 2.x DAG Python file for DQ orchestration."""
    dag_id = f"dq_pipeline_{session_id}"
    task_blocks = "\n\n".join(
        _generate_rule_task(rule, gcp_project, gcp_dataset, dq_dataset)
        for rule in rules
    )
    rule_task_ids = [_safe_task_id(r.get("rule_id", "")) for r in rules]
    task_ids_list = "[" + ", ".join(f'"{t}"' for t in rule_task_ids) + "]"

    return f'''"""
Auto-generated DQ Pipeline DAG — session: {session_id}
Generated at: {datetime.utcnow().isoformat()}Z
DO NOT EDIT MANUALLY — regenerate via the DQ platform.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag, task_group
from airflow.operators.python import PythonOperator
from airflow.providers.google.cloud.operators.bigquery import (
    BigQueryInsertJobOperator,
    BigQueryCheckOperator,
)
from airflow.utils.dates import days_ago
import uuid

DAG_ID = "{dag_id}"
GCP_PROJECT = "{gcp_project}"
GCP_DATASET = "{gcp_dataset}"
DQ_DATASET = "{dq_dataset}"

DEFAULT_ARGS = {{
    "owner": "{owner}",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=60),
    "depends_on_past": False,
    "email_on_failure": True,
    "email_on_retry": False,
}}


@dag(
    dag_id=DAG_ID,
    default_args=DEFAULT_ARGS,
    description="Agentic DQ Pipeline — session {session_id}",
    schedule_interval="{schedule}",
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    tags=["data-quality", "dq", "{session_id}"],
    params={{
        "run_id": "{{{{ dag_run.run_id }}}}",
        "session_id": "{session_id}",
    }},
)
def dq_pipeline():

    @task_group(group_id="dq_initialization")
    def init_group():
        init = PythonOperator(
            task_id="initialize_run",
            python_callable=_initialize_run,
            op_kwargs={{"session_id": "{session_id}", "run_id": "{{{{ dag_run.run_id }}}}"}},
        )
        return init

    @task_group(group_id="dq_rules_execution")
    def rules_group():
{_indent(task_blocks, 8)}

    @task_group(group_id="dq_summary")
    def summary_group():
        summary = PythonOperator(
            task_id="compute_summary",
            python_callable=_compute_summary,
            op_kwargs={{
                "session_id": "{session_id}",
                "run_id": "{{{{ dag_run.run_id }}}}",
                "project": GCP_PROJECT,
                "dq_dataset": DQ_DATASET,
            }},
        )
        return summary

    init = init_group()
    rules = rules_group()
    summary = summary_group()
    init >> rules >> summary


def _initialize_run(session_id: str, run_id: str, **kwargs) -> None:
    import logging
    logging.info(f"Initializing DQ run {{run_id}} for session {{session_id}}")


def _compute_summary(session_id: str, run_id: str, project: str, dq_dataset: str, **kwargs) -> None:
    import logging
    logging.info(f"Computing DQ run summary for run_id={{run_id}}")


dag_instance = dq_pipeline()
'''


def generate_bigquery_check_operator(rule: dict[str, Any]) -> str:
    """Generate a BigQueryCheckOperator task definition string."""
    task_id = _safe_task_id(rule.get("rule_id", "dq_check"))
    sql = (rule.get("generated_sql", "") or "").replace('"', '\\"').replace("\n", " ")

    return f'''    BigQueryCheckOperator(
        task_id="{task_id}",
        sql="""{sql}""",
        use_legacy_sql=False,
        gcp_conn_id="google_cloud_default",
    )'''


def generate_bigquery_insert_job_operator(rule: dict[str, Any]) -> str:
    """Generate a BigQueryInsertJobOperator task definition string."""
    task_id = _safe_task_id(rule.get("rule_id", "dq_insert"))
    project = rule.get("project_id", "")
    sql = (rule.get("generated_sql", "") or "").replace('"', '\\"').replace("\n", " ")

    return f'''    BigQueryInsertJobOperator(
        task_id="{task_id}",
        configuration={{
            "query": {{
                "query": """{sql}""",
                "useLegacySql": False,
            }}
        }},
        project_id="{project}",
        gcp_conn_id="google_cloud_default",
    )'''


def inject_task_group_into_dag(
    dag_file_content: str,
    session_id: str,
    rules: list[dict[str, Any]],
    upstream_task: str,
    downstream_task: str,
    gcp_project: str,
    gcp_dataset: str,
    dq_dataset: str = "dq_observability",
) -> str:
    """Inject a DQ TaskGroup into an existing Airflow DAG file content."""
    task_group_code = _build_task_group_code(
        session_id, rules, gcp_project, gcp_dataset, dq_dataset
    )

    injection_marker = f"# DQ_INJECT_POINT:{session_id}"
    if injection_marker in dag_file_content:
        pattern = re.compile(
            rf"{re.escape(injection_marker)}.*?# END_DQ_INJECT:{session_id}",
            re.DOTALL,
        )
        dag_file_content = pattern.sub(
            f"{injection_marker}\n{task_group_code}\n# END_DQ_INJECT:{session_id}",
            dag_file_content,
        )
    else:
        dag_file_content += f"\n\n{injection_marker}\n{task_group_code}\n# END_DQ_INJECT:{session_id}\n"

    return dag_file_content


def _generate_rule_task(
    rule: dict[str, Any], project: str, dataset: str, dq_dataset: str
) -> str:
    task_id = _safe_task_id(rule.get("rule_id", "dq_rule"))
    rule_name = rule.get("rule_name", task_id)
    severity = rule.get("severity", "WARN")
    sql = (rule.get("generated_sql", f"SELECT 1 -- placeholder for {rule_name}") or "").strip()
    sql_escaped = sql.replace('"""', '\\"\\"\\"').replace("\n", "\\n")

    return f'''        # Rule: {rule_name} | Severity: {severity}
        {task_id}_task = BigQueryInsertJobOperator(
            task_id="{task_id}",
            configuration={{
                "query": {{
                    "query": """{sql_escaped}""",
                    "useLegacySql": False,
                }}
            }},
            project_id="{project}",
            gcp_conn_id="google_cloud_default",
        )'''


def _build_task_group_code(
    session_id: str,
    rules: list[dict[str, Any]],
    project: str,
    dataset: str,
    dq_dataset: str,
) -> str:
    task_blocks = "\n\n".join(
        _generate_rule_task(r, project, dataset, dq_dataset) for r in rules
    )
    return f'''
@task_group(group_id="dq_{session_id[:8]}")
def dq_group_{session_id[:8]}():
{_indent(task_blocks, 4)}
'''


def _safe_task_id(rule_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", rule_id).lower()[:63]


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line.strip() else line for line in text.splitlines())
