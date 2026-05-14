"""Business Rule Recommendation Agent — Stage 3 of the DQ workflow."""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from agents.base import BaseAgent
from prompts.business_dq_agent import (
    BUSINESS_RULE_SYSTEM_PROMPT_V1,
    RULE_INFERENCE_PROMPT_V1,
)
from schemas.models import DQRule, RuleCategory, Severity

logger = structlog.get_logger(__name__)

_CATEGORY_MAP = {
    "completeness": RuleCategory.COMPLETENESS,
    "uniqueness": RuleCategory.UNIQUENESS,
    "validity": RuleCategory.VALIDITY,
    "integrity": RuleCategory.INTEGRITY,
    "freshness": RuleCategory.FRESHNESS,
    "volume": RuleCategory.VOLUME,
    "schema_drift": RuleCategory.SCHEMA_DRIFT,
    "consistency": RuleCategory.CONSISTENCY,
}

_SEVERITY_MAP = {
    "INFO": Severity.INFO,
    "WARN": Severity.WARN,
    "FAIL": Severity.FAIL,
}


class BusinessRuleRecommendationAgent(BaseAgent):
    """Uses Claude to infer intelligent business DQ rules from table semantics."""

    def __init__(self) -> None:
        super().__init__(
            agent_name="BusinessRuleRecommendationAgent",
            system_prompt=BUSINESS_RULE_SYSTEM_PROMPT_V1,
        )

    async def run(
        self,
        project_id: str,
        dataset_id: str,
        table_name: str,
        metadata: dict[str, Any],
        profiles: dict[str, Any],
        semantics: dict[str, Any],
        rule_set_version_id: str,
        custom_context: str | None = None,
    ) -> list[DQRule]:
        """Generate Claude-inferred business DQ rules for a single table."""
        self._log.info(
            "business_rule_inference_start",
            table=table_name,
            columns=len(metadata.get("columns", [])),
        )

        prompt = RULE_INFERENCE_PROMPT_V1.format(
            project_id=project_id,
            dataset_id=dataset_id,
            table_name=table_name,
            metadata_json=json.dumps(metadata, indent=2, default=str)[:4000],
            profiles_json=json.dumps(profiles, indent=2, default=str)[:4000],
            semantics_json=json.dumps(semantics, indent=2, default=str)[:2000],
        )

        if custom_context:
            prompt += f"\n\nAdditional business context:\n{custom_context}"

        try:
            result = await self._call_claude_json(prompt)
            raw_rules = result.get("rules", [])

            dq_rules = [
                self._parse_rule(raw, project_id, dataset_id, table_name, rule_set_version_id)
                for raw in raw_rules
                if isinstance(raw, dict)
            ]

            self._log.info("business_rules_generated", count=len(dq_rules))
            return dq_rules

        except Exception as exc:
            self._log.error("business_rule_inference_failed", error=str(exc))
            return []

    def _parse_rule(
        self,
        raw: dict[str, Any],
        project: str,
        dataset: str,
        table: str,
        version_id: str,
    ) -> DQRule:
        category_str = raw.get("rule_category", "validity").lower()
        severity_str = raw.get("severity", "WARN").upper()

        return DQRule(
            rule_id=raw.get("rule_id") or f"BRUL_{uuid.uuid4().hex[:8]}",
            rule_name=raw.get("rule_name", "Unnamed Business Rule"),
            rule_category=_CATEGORY_MAP.get(category_str, RuleCategory.VALIDITY),
            description=raw.get("description", ""),
            severity=_SEVERITY_MAP.get(severity_str, Severity.WARN),
            threshold=float(raw.get("threshold", 0.0)),
            execution_frequency=raw.get("execution_frequency", "daily"),
            project_id=project,
            dataset_name=dataset,
            table_name=table,
            column_name=raw.get("column_name"),
            sql_template=raw.get("sql_template"),
            parameters=raw.get("parameters", {}),
            rationale=raw.get("rationale"),
            rule_set_version_id=version_id,
        )
