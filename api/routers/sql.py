"""SQL API endpoints — generate and execute DQ SQL."""

from __future__ import annotations

import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from api.middleware.auth import verify_api_key
from api.routers.discovery import _sessions, _get_orchestrator
from schemas.models import APIResponse, SQLGenerationRequest

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post(
    "/generate",
    response_model=APIResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate DQ SQL",
    description="Generate parameterized BigQuery SQL for all approved rules.",
)
async def generate_sql(
    request: SQLGenerationRequest,
    _: str = Depends(verify_api_key),
) -> APIResponse:
    state = _sessions.get(request.session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session {request.session_id} not found")

    from schemas.models import ApprovalStatus
    if state.approval_1_status != ApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=400,
            detail="Checkpoint 1 approval is required before SQL generation. Submit approval first.",
        )

    orchestrator = _get_orchestrator()
    try:
        state = await orchestrator.run_stage_sql_generation(state)
        _sessions[request.session_id] = state

        rules = state.rule_set.all_rules if state.rule_set else []
        with_sql = sum(1 for r in rules if r.generated_sql)

        return APIResponse(
            success=True,
            data={
                "session_id": request.session_id,
                "total_rules": len(rules),
                "sql_generated": with_sql,
                "stage": state.current_stage.value,
                "message": "SQL generated. Execute via POST /sql/execute",
            },
        )
    except Exception as exc:
        logger.error("sql_generation_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/execute",
    response_model=APIResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Execute DQ SQL",
    description="Execute all generated DQ SQL and write results to BigQuery.",
)
async def execute_sql(
    body: dict,
    _: str = Depends(verify_api_key),
) -> APIResponse:
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    if not state.rule_set:
        raise HTTPException(status_code=400, detail="No rules available for execution")

    from agents.validation_agent.agent import ValidationAgent
    from tools.bigquery.client import get_bq_client
    from configs.settings import get_settings

    settings = get_settings()
    bq_client = get_bq_client()
    validation_agent = ValidationAgent(bq_client, settings.gcp.project_id, settings.gcp.dq_dataset)

    try:
        run_result = await validation_agent.run(
            session_id=session_id,
            rules=state.rule_set.all_rules,
            rule_set_version_id=state.rule_set.rule_set_version_id,
            consolidated_sp_name=state.consolidated_sp_name,
        )
        state.run_results = run_result
        _sessions[session_id] = state

        return APIResponse(
            success=True,
            data={
                "run_id": run_result.run_id,
                "session_id": session_id,
                "total_rules": run_result.total_rules,
                "passed": run_result.passed,
                "failed": run_result.failed,
                "errors": run_result.errors,
                "pass_rate": run_result.pass_rate,
                "health_score": run_result.health_score,
                "duration_seconds": run_result.duration_seconds,
            },
        )
    except Exception as exc:
        logger.error("sql_execution_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
