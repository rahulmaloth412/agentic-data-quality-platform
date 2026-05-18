"""SQL Generation Agent — Stage 6 of the DQ workflow."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any

import structlog

from agents.base import BaseAgent
from prompts.sql_generation_agent import (
    SQL_GENERATION_PROMPT_V1,
    SQL_GENERATION_SYSTEM_PROMPT_V1,
    SQL_REVIEW_PROMPT_V1,
)
from schemas.models import DQRule
from tools.bigquery.client import BigQueryClient
from tools.sql_tools.builder import SQLBuilder, get_sql_builder
from tools.sql_tools.validator import validate_sql_syntax

logger = structlog.get_logger(__name__)


class SQLGenerationAgent(BaseAgent):
    """Generates executable BigQuery SQL for every approved DQ rule."""

    def __init__(self, dq_project: str, dq_dataset: str) -> None:
        super().__init__(
            agent_name="SQLGenerationAgent",
            system_prompt=SQL_GENERATION_SYSTEM_PROMPT_V1,
        )
        self._dq_project = dq_project
        self._dq_dataset = dq_dataset
        self._builder: SQLBuilder = get_sql_builder(dq_project, dq_dataset)

    async def run(
        self,
        rules: list[DQRule],
        table_metadata: dict[str, Any],
        run_id: str | None = None,
        output_formats: list[str] | None = None,
    ) -> list[DQRule]:
        """Generate SQL for all rules and return updated rules with generated_sql set."""
        run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        output_formats = output_formats or ["bigquery_sql"]

        self._log.info("sql_generation_start", rule_count=len(rules), run_id=run_id)

        updated_rules: list[DQRule] = []
        for rule in rules:
            updated = await self._generate_sql_for_rule(rule, table_metadata, run_id)
            updated_rules.append(updated)

        self._log.info("sql_generation_complete", generated=len(updated_rules))
        return updated_rules

    async def _generate_sql_for_rule(
        self, rule: DQRule, metadata: dict[str, Any], run_id: str
    ) -> DQRule:
        """Generate SQL for a single rule using template builder or Claude fallback."""
        try:
            sql = self._generate_from_template(rule, run_id)

            if not sql:
                sql = await self._generate_from_claude(rule, metadata, run_id)

            if sql:
                is_valid, error = validate_sql_syntax(sql)
                if not is_valid:
                    self._log.warning(
                        "generated_sql_invalid",
                        rule_id=rule.rule_id,
                        error=error,
                    )
                rule.generated_sql = sql
            else:
                self._log.warning("no_sql_generated", rule_id=rule.rule_id)

        except Exception as exc:
            self._log.error("sql_generation_failed", rule_id=rule.rule_id, error=str(exc))

        return rule

    def _generate_from_template(self, rule: DQRule, run_id: str) -> str | None:
        """Generate SQL using Jinja2 template builder based on rule category."""
        params = rule.parameters or {}
        cat = rule.rule_category.value

        try:
            if cat == "completeness" and rule.column_name:
                return self._builder.build_completeness_check(
                    run_id=run_id,
                    rule_id=rule.rule_id,
                    project=rule.project_id,
                    dataset=rule.dataset_name,
                    table=rule.table_name,
                    column=rule.column_name,
                    threshold=float(params.get("threshold", rule.threshold)),
                    severity=rule.severity.value,
                    partition_filter=params.get("partition_filter"),
                )
            elif cat == "uniqueness" and rule.column_name:
                columns = params.get("columns", [rule.column_name])
                return self._builder.build_uniqueness_check(
                    run_id=run_id,
                    rule_id=rule.rule_id,
                    project=rule.project_id,
                    dataset=rule.dataset_name,
                    table=rule.table_name,
                    columns=columns,
                    severity=rule.severity.value,
                    partition_filter=params.get("partition_filter"),
                )
            elif cat == "validity" and params.get("regex_pattern") and rule.column_name:
                return self._builder.build_validity_regex_check(
                    run_id=run_id,
                    rule_id=rule.rule_id,
                    project=rule.project_id,
                    dataset=rule.dataset_name,
                    table=rule.table_name,
                    column=rule.column_name,
                    regex_pattern=params["regex_pattern"],
                    threshold=float(params.get("threshold", 0.99)),
                    severity=rule.severity.value,
                    partition_filter=params.get("partition_filter"),
                )
            elif cat == "validity" and params.get("allowed_values") and rule.column_name:
                return self._builder.build_enum_values_check(
                    run_id=run_id,
                    rule_id=rule.rule_id,
                    project=rule.project_id,
                    dataset=rule.dataset_name,
                    table=rule.table_name,
                    column=rule.column_name,
                    allowed_values=params["allowed_values"],
                    severity=rule.severity.value,
                    partition_filter=params.get("partition_filter"),
                )
            elif cat == "validity" and params.get("has_min") and rule.column_name:
                return self._builder.build_range_check(
                    run_id=run_id,
                    rule_id=rule.rule_id,
                    project=rule.project_id,
                    dataset=rule.dataset_name,
                    table=rule.table_name,
                    column=rule.column_name,
                    min_value=params.get("min_value"),
                    max_value=params.get("max_value"),
                    severity=rule.severity.value,
                    partition_filter=params.get("partition_filter"),
                )
            elif cat == "freshness":
                ts_col = rule.column_name or params.get("timestamp_column", "created_at")
                return self._builder.build_freshness_check(
                    run_id=run_id,
                    rule_id=rule.rule_id,
                    project=rule.project_id,
                    dataset=rule.dataset_name,
                    table=rule.table_name,
                    timestamp_column=ts_col,
                    max_lag_hours=float(params.get("max_lag_hours", 24.0)),
                    severity=rule.severity.value,
                )
            elif cat == "volume":
                return self._builder.build_volume_check(
                    run_id=run_id,
                    rule_id=rule.rule_id,
                    project=rule.project_id,
                    dataset=rule.dataset_name,
                    table=rule.table_name,
                    min_rows=int(params.get("min_rows", 1)),
                    max_rows=params.get("max_rows"),
                    severity=rule.severity.value,
                    partition_filter=params.get("partition_filter"),
                )
            elif cat == "integrity" and rule.column_name:
                return self._builder.build_referential_integrity_check(
                    run_id=run_id,
                    rule_id=rule.rule_id,
                    project=rule.project_id,
                    dataset=rule.dataset_name,
                    table=rule.table_name,
                    column=rule.column_name,
                    ref_project=params.get("ref_project", rule.project_id),
                    ref_dataset=params.get("ref_dataset", rule.dataset_name),
                    ref_table=params.get("ref_table", ""),
                    ref_column=params.get("ref_column", rule.column_name),
                    severity=rule.severity.value,
                )
            elif cat == "schema_drift":
                raw = params.get("baseline_columns_json", "[]")
                baseline_cols = json.loads(raw) if isinstance(raw, str) else raw
                return self._builder.build_schema_drift_check(
                    run_id=run_id,
                    rule_id=rule.rule_id,
                    project=rule.project_id,
                    dataset=rule.dataset_name,
                    table=rule.table_name,
                    baseline_columns=baseline_cols or [],
                    severity=rule.severity.value,
                )
        except Exception as exc:
            self._log.warning("template_sql_failed", rule_id=rule.rule_id, error=str(exc))

        return None

    async def _generate_from_claude(
        self, rule: DQRule, metadata: dict[str, Any], run_id: str
    ) -> str | None:
        """Use Claude to generate SQL for rules without matching templates."""
        prompt = SQL_GENERATION_PROMPT_V1.format(
            rule_json=json.dumps(rule.model_dump(), indent=2, default=str),
            metadata_json=json.dumps(metadata, indent=2, default=str)[:3000],
            dq_project=self._dq_project,
            dq_dataset=self._dq_dataset,
            run_id=run_id,
        )

        try:
            result = await self._call_claude_json(prompt)
            return result.get("sql")
        except Exception as exc:
            self._log.error("claude_sql_generation_failed", rule_id=rule.rule_id, error=str(exc))
            return None

    async def persist_rules_to_bigquery(
        self,
        rules: list[DQRule],
        session_id: str,
        rule_set_version_id: str,
        bq_client: BigQueryClient,
    ) -> None:
        """Insert rule configs (with generated SQL) into dq_rule_config."""
        table_id = f"{self._dq_project}.{self._dq_dataset}.dq_rule_config"
        now = datetime.utcnow().isoformat()
        rows = [
            {
                "rule_id": r.rule_id,
                "rule_set_version_id": rule_set_version_id,
                "session_id": session_id,
                "rule_name": r.rule_name,
                "rule_category": r.rule_category.value,
                "description": r.description,
                "severity": r.severity.value,
                "threshold": r.threshold,
                "execution_frequency": r.execution_frequency or "daily",
                "project_id": r.project_id,
                "dataset_name": r.dataset_name,
                "table_name": r.table_name,
                "column_name": r.column_name,
                "generated_sql": r.generated_sql,
                "parameters_json": json.dumps(r.parameters or {}, default=str),
                "rationale": r.rationale,
                "is_active": r.is_active,
                "created_at": now,
                "updated_at": now,
            }
            for r in rules
        ]
        try:
            await bq_client.insert_rows(table_id, rows)
            self._log.info("rules_persisted_to_bq", count=len(rows), table=table_id)
        except Exception as exc:
            self._log.error("rules_persist_failed", error=str(exc))

    async def create_consolidated_stored_procedure(
        self,
        rules: list[DQRule],
        bq_client: BigQueryClient,
        session_id: str,
    ) -> str:
        """Create ONE consolidated BigQuery stored procedure for all approved/active rules.

        The procedure accepts `run_id STRING` and executes every rule's INSERT
        sequentially in a single BEGIN...END block, giving enterprise-grade governance:
        one artifact per session, version-controlled, auditable.

        Returns the procedure name, or empty string on failure.
        """
        active = [r for r in rules if r.generated_sql and r.is_active]
        if not active:
            self._log.warning("no_active_rules_for_sp", session_id=session_id)
            return ""

        sp_name = _safe_sp_name(session_id)
        statements = []
        for rule in active:
            # Replace @run_id query-parameter syntax with the procedure IN parameter
            body = rule.generated_sql.replace("@run_id", "run_id").rstrip(";").strip()
            # Indent the body so it sits cleanly inside the BEGIN block
            indented = "\n".join(
                ("      " + line) if line.strip() else line
                for line in body.splitlines()
            )
            cat = rule.rule_category.value.upper()
            # Wrap in BEGIN...EXCEPTION so one failing rule never aborts the rest
            statements.append(
                f"  -- [{cat}] {rule.rule_name}\n"
                f"  BEGIN\n"
                f"{indented};\n"
                f"  EXCEPTION WHEN ERROR THEN\n"
                f"    -- rule execution failed; continuing with remaining rules\n"
                f"  END;"
            )

        rule_block = "\n\n".join(statements)
        sp_ddl = (
            f"CREATE OR REPLACE PROCEDURE\n"
            f"  `{self._dq_project}.{self._dq_dataset}.{sp_name}`(IN run_id STRING)\n"
            f"BEGIN\n"
            f"  -- ================================================================\n"
            f"  -- Consolidated DQ Validation Procedure\n"
            f"  -- Session  : {session_id}\n"
            f"  -- Rules    : {len(active)}\n"
            f"  -- Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"  -- Each rule is wrapped in BEGIN...EXCEPTION so failures are isolated\n"
            f"  -- ================================================================\n\n"
            f"{rule_block}\n"
            f"END"
        )

        try:
            await bq_client.execute_dml(sp_ddl)
            self._log.info("consolidated_sp_created", sp=sp_name, rules=len(active))
            return sp_name
        except Exception as exc:
            # Surface the error clearly so it appears in the API response
            self._log.error("consolidated_sp_failed", session_id=session_id, error=str(exc))
            raise RuntimeError(
                f"Failed to create consolidated stored procedure `{sp_name}`: {exc}"
            ) from exc


def _safe_sp_name(identifier: str) -> str:
    """Return a BigQuery-safe stored procedure name."""
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", identifier)
    return f"sp_dq_{safe}"
