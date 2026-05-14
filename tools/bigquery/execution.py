"""DQ SQL execution engine with parallel rule execution and result persistence."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from typing import Any, Optional

import structlog

from tools.bigquery.client import BigQueryClient

logger = structlog.get_logger(__name__)

_DEFAULT_CONCURRENCY = 10


async def execute_dq_rule(
    client: BigQueryClient,
    rule: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    """Execute a single DQ rule's generated SQL and return a DQResult-compatible dict."""
    rule_id = rule.get("rule_id", "unknown")
    sql = rule.get("generated_sql", "")
    log = logger.bind(rule_id=rule_id, run_id=run_id)

    if not sql:
        log.warning("no_sql_for_rule")
        return _build_result(rule, run_id, "SKIPPED", error="No SQL generated for rule")

    start = time.monotonic()
    try:
        log.info("executing_dq_rule")
        await client.execute_dml(sql)
        duration = time.monotonic() - start

        result_rows = await _fetch_latest_result(client, rule, run_id)
        if result_rows:
            result = dict(result_rows[0])
            result["execution_duration_seconds"] = round(duration, 3)
            return result

        log.warning("no_result_row_after_execution")
        return _build_result(rule, run_id, "ERROR", error="No result row found after execution", duration=duration)

    except Exception as exc:
        duration = time.monotonic() - start
        log.error("dq_rule_execution_failed", error=str(exc))
        return _build_result(rule, run_id, "ERROR", error=str(exc), duration=duration)


async def execute_dq_ruleset(
    client: BigQueryClient,
    rules: list[dict[str, Any]],
    run_id: str,
    concurrency: int = _DEFAULT_CONCURRENCY,
) -> list[dict[str, Any]]:
    """Execute all DQ rules in parallel with a concurrency limit."""
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(rule: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            return await execute_dq_rule(client, rule, run_id)

    tasks = [_bounded(rule) for rule in rules]
    results = await asyncio.gather(*tasks)
    logger.info("ruleset_execution_complete", run_id=run_id, total=len(results))
    return list(results)


async def persist_dq_results(
    client: BigQueryClient,
    results: list[dict[str, Any]],
    project: str,
    dataset: str,
) -> None:
    """Insert DQ result rows into the dq_results table via streaming insert."""
    table_id = f"{project}.{dataset}.dq_results"
    if not results:
        return

    rows = []
    now = datetime.utcnow().isoformat()
    for r in results:
        rows.append({
            "run_id": r.get("run_id", ""),
            "rule_id": r.get("rule_id", ""),
            "project_id": r.get("project_id", project),
            "dataset_name": r.get("dataset_name", dataset),
            "table_name": r.get("table_name", ""),
            "column_name": r.get("column_name"),
            "rule_type": r.get("rule_type", ""),
            "severity": r.get("severity", "INFO"),
            "status": r.get("status", "ERROR"),
            "observed_value": str(r["observed_value"]) if r.get("observed_value") is not None else None,
            "expected_value": str(r["expected_value"]) if r.get("expected_value") is not None else None,
            "threshold_value": str(r["threshold_value"]) if r.get("threshold_value") is not None else None,
            "failure_count": r.get("failure_count"),
            "execution_time": r.get("execution_time", now),
            "execution_duration_seconds": r.get("execution_duration_seconds"),
            "query_executed": r.get("query_executed"),
            "error_message": r.get("error_message"),
            "created_at": now,
        })

    await client.insert_rows(table_id, rows)
    logger.info("dq_results_persisted", count=len(rows), table=table_id)


async def get_run_summary(
    client: BigQueryClient,
    run_id: str,
    project: str,
    dataset: str,
) -> dict[str, Any]:
    """Aggregate pass/fail/error counts for a completed DQ run."""
    sql = f"""
    SELECT
        status,
        severity,
        COUNT(*) AS count
    FROM `{project}.{dataset}.dq_results`
    WHERE run_id = @run_id
    GROUP BY status, severity
    """
    rows = await client.execute_query(sql, params={"run_id": run_id})

    totals: dict[str, int] = {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIPPED": 0}
    critical_failures = 0
    for row in rows:
        status = row["status"]
        count = row["count"]
        totals[status] = totals.get(status, 0) + count
        if status == "FAIL" and row["severity"] == "FAIL":
            critical_failures += count

    total = sum(totals.values())
    passed = totals.get("PASS", 0)
    failed = totals.get("FAIL", 0)
    errors = totals.get("ERROR", 0)
    pass_rate = passed / total if total > 0 else 0.0
    health_score = (pass_rate * 0.6 + (1 - critical_failures / max(total, 1)) * 0.4) * 100

    return {
        "run_id": run_id,
        "total_rules": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": totals.get("SKIPPED", 0),
        "critical_failures": critical_failures,
        "pass_rate": round(pass_rate, 4),
        "health_score": round(health_score, 2),
    }


async def _fetch_latest_result(
    client: BigQueryClient,
    rule: dict[str, Any],
    run_id: str,
) -> list[dict[str, Any]]:
    """Fetch the result row inserted by the rule's SQL from dq_results."""
    project = rule.get("project_id", "")
    dataset = rule.get("dataset_name", "")
    rule_id = rule.get("rule_id", "")

    if not all([project, dataset, rule_id]):
        return []

    sql = f"""
    SELECT *
    FROM `{project}.{dataset}.dq_results`
    WHERE run_id = @run_id AND rule_id = @rule_id
    ORDER BY execution_time DESC
    LIMIT 1
    """
    return await client.execute_query(sql, params={"run_id": run_id, "rule_id": rule_id})


def _build_result(
    rule: dict[str, Any],
    run_id: str,
    status: str,
    error: Optional[str] = None,
    duration: Optional[float] = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "rule_id": rule.get("rule_id", "unknown"),
        "project_id": rule.get("project_id", ""),
        "dataset_name": rule.get("dataset_name", ""),
        "table_name": rule.get("table_name", ""),
        "column_name": rule.get("column_name"),
        "rule_type": rule.get("rule_category", ""),
        "severity": rule.get("severity", "INFO"),
        "status": status,
        "observed_value": None,
        "expected_value": None,
        "threshold_value": str(rule.get("threshold", "")),
        "failure_count": None,
        "execution_time": datetime.utcnow().isoformat(),
        "execution_duration_seconds": round(duration, 3) if duration else None,
        "query_executed": rule.get("generated_sql", "")[:1000] if rule.get("generated_sql") else None,
        "error_message": error,
        "created_at": datetime.utcnow().isoformat(),
    }
