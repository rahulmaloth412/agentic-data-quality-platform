"""SQL builder using Jinja2 templates for DQ rule SQL generation."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Optional

import structlog
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

logger = structlog.get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "sql_templates"


def _get_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=()),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


class SQLBuilder:
    """Builds parameterized, idempotent BigQuery DQ SQL from Jinja2 templates."""

    def __init__(
        self,
        dq_project: str,
        dq_dataset: str,
    ) -> None:
        self._dq_project = dq_project
        self._dq_dataset = dq_dataset
        self._env = _get_jinja_env()

    def render_template(self, template_name: str, context: dict[str, Any]) -> str:
        """Load and render a Jinja2 SQL template."""
        template = self._env.get_template(template_name)
        ctx = {**context, "dq_project": self._dq_project, "dq_dataset": self._dq_dataset}
        sql = template.render(**ctx)
        return sql.strip()

    def build_completeness_check(
        self,
        run_id: str,
        rule_id: str,
        project: str,
        dataset: str,
        table: str,
        column: str,
        threshold: float = 0.0,
        severity: str = "FAIL",
        partition_filter: Optional[str] = None,
    ) -> str:
        return self.render_template(
            "completeness_check.sql.j2",
            {
                "run_id": run_id,
                "rule_id": rule_id,
                "project_id": project,
                "dataset_name": dataset,
                "table_name": table,
                "column_name": column,
                "threshold": threshold,
                "threshold_pct": round(threshold * 100, 2),
                "severity": severity,
                "partition_filter": partition_filter or "",
                "query_hash": _hash_sql(f"completeness:{project}.{dataset}.{table}.{column}"),
            },
        )

    def build_uniqueness_check(
        self,
        run_id: str,
        rule_id: str,
        project: str,
        dataset: str,
        table: str,
        columns: list[str],
        severity: str = "FAIL",
        partition_filter: Optional[str] = None,
    ) -> str:
        return self.render_template(
            "uniqueness_check.sql.j2",
            {
                "run_id": run_id,
                "rule_id": rule_id,
                "project_id": project,
                "dataset_name": dataset,
                "table_name": table,
                "columns": columns,
                "columns_str": ", ".join(f"`{c}`" for c in columns),
                "severity": severity,
                "partition_filter": partition_filter or "",
                "query_hash": _hash_sql(f"uniqueness:{project}.{dataset}.{table}.{','.join(columns)}"),
            },
        )

    def build_validity_regex_check(
        self,
        run_id: str,
        rule_id: str,
        project: str,
        dataset: str,
        table: str,
        column: str,
        regex_pattern: str,
        threshold: float = 1.0,
        severity: str = "WARN",
        partition_filter: Optional[str] = None,
    ) -> str:
        return self.render_template(
            "validity_regex_check.sql.j2",
            {
                "run_id": run_id,
                "rule_id": rule_id,
                "project_id": project,
                "dataset_name": dataset,
                "table_name": table,
                "column_name": column,
                "regex_pattern": regex_pattern,
                "threshold": threshold,
                "severity": severity,
                "partition_filter": partition_filter or "",
                "query_hash": _hash_sql(f"validity:{project}.{dataset}.{table}.{column}"),
            },
        )

    def build_freshness_check(
        self,
        run_id: str,
        rule_id: str,
        project: str,
        dataset: str,
        table: str,
        timestamp_column: str,
        max_lag_hours: float,
        severity: str = "FAIL",
    ) -> str:
        return self.render_template(
            "freshness_check.sql.j2",
            {
                "run_id": run_id,
                "rule_id": rule_id,
                "project_id": project,
                "dataset_name": dataset,
                "table_name": table,
                "timestamp_column": timestamp_column,
                "max_lag_hours": max_lag_hours,
                "severity": severity,
                "query_hash": _hash_sql(f"freshness:{project}.{dataset}.{table}.{timestamp_column}"),
            },
        )

    def build_volume_check(
        self,
        run_id: str,
        rule_id: str,
        project: str,
        dataset: str,
        table: str,
        min_rows: int,
        max_rows: Optional[int] = None,
        severity: str = "WARN",
        partition_filter: Optional[str] = None,
    ) -> str:
        return self.render_template(
            "volume_check.sql.j2",
            {
                "run_id": run_id,
                "rule_id": rule_id,
                "project_id": project,
                "dataset_name": dataset,
                "table_name": table,
                "min_rows": min_rows,
                "max_rows": max_rows,
                "has_max_rows": max_rows is not None,
                "severity": severity,
                "partition_filter": partition_filter or "",
                "query_hash": _hash_sql(f"volume:{project}.{dataset}.{table}"),
            },
        )

    def build_referential_integrity_check(
        self,
        run_id: str,
        rule_id: str,
        project: str,
        dataset: str,
        table: str,
        column: str,
        ref_project: str,
        ref_dataset: str,
        ref_table: str,
        ref_column: str,
        severity: str = "FAIL",
    ) -> str:
        return self.render_template(
            "referential_integrity_check.sql.j2",
            {
                "run_id": run_id,
                "rule_id": rule_id,
                "project_id": project,
                "dataset_name": dataset,
                "table_name": table,
                "column_name": column,
                "ref_project": ref_project,
                "ref_dataset": ref_dataset,
                "ref_table": ref_table,
                "ref_column": ref_column,
                "severity": severity,
                "query_hash": _hash_sql(f"ri:{project}.{dataset}.{table}.{column}->{ref_table}.{ref_column}"),
            },
        )

    def build_enum_values_check(
        self,
        run_id: str,
        rule_id: str,
        project: str,
        dataset: str,
        table: str,
        column: str,
        allowed_values: list[str],
        severity: str = "WARN",
        partition_filter: Optional[str] = None,
    ) -> str:
        return self.render_template(
            "enum_values_check.sql.j2",
            {
                "run_id": run_id,
                "rule_id": rule_id,
                "project_id": project,
                "dataset_name": dataset,
                "table_name": table,
                "column_name": column,
                "allowed_values": allowed_values,
                "allowed_values_str": ", ".join(f"'{v}'" for v in allowed_values),
                "severity": severity,
                "partition_filter": partition_filter or "",
                "query_hash": _hash_sql(f"enum:{project}.{dataset}.{table}.{column}"),
            },
        )

    def build_range_check(
        self,
        run_id: str,
        rule_id: str,
        project: str,
        dataset: str,
        table: str,
        column: str,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        severity: str = "WARN",
        partition_filter: Optional[str] = None,
    ) -> str:
        return self.render_template(
            "range_check.sql.j2",
            {
                "run_id": run_id,
                "rule_id": rule_id,
                "project_id": project,
                "dataset_name": dataset,
                "table_name": table,
                "column_name": column,
                "min_value": min_value,
                "max_value": max_value,
                "has_min": min_value is not None,
                "has_max": max_value is not None,
                "severity": severity,
                "partition_filter": partition_filter or "",
                "query_hash": _hash_sql(f"range:{project}.{dataset}.{table}.{column}"),
            },
        )

    def build_schema_drift_check(
        self,
        run_id: str,
        rule_id: str,
        project: str,
        dataset: str,
        table: str,
        baseline_columns: list[dict[str, Any]],
        severity: str = "WARN",
    ) -> str:
        import json as _json
        return self.render_template(
            "schema_drift_check.sql.j2",
            {
                "run_id": run_id,
                "rule_id": rule_id,
                "project_id": project,
                "dataset_name": dataset,
                "table_name": table,
                "baseline_columns_json": _json.dumps(baseline_columns),
                "severity": severity,
                "query_hash": _hash_sql(f"schema_drift:{project}.{dataset}.{table}"),
            },
        )

    def build_custom_sql(self, template_str: str, params: dict[str, Any]) -> str:
        """Render an arbitrary Jinja2 template string with parameters."""
        from jinja2 import Template
        template = Template(
            template_str,
            undefined=StrictUndefined,
            autoescape=False,
        )
        return template.render(**params).strip()


def _hash_sql(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def get_sql_builder(dq_project: str, dq_dataset: str) -> SQLBuilder:
    return SQLBuilder(dq_project=dq_project, dq_dataset=dq_dataset)
