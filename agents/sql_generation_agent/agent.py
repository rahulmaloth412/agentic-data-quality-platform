"""SQL Generation Agent — Stage 6 of the DQ workflow."""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from agents.base import BaseAgent
from prompts.sql_generation_agent import (
    SQL_GENERATION_PROMPT_V1,
    SQL_GENERATION_SYSTEM_PROMPT_V1,
    SQL_REVIEW_PROMPT_V1,
)
from schemas.models import DQRule
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
