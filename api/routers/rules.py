"""Rules API endpoints — rule generation, retrieval, and management."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from api.middleware.auth import verify_api_key
from api.routers.discovery import _sessions, _get_orchestrator
from schemas.models import APIResponse, RuleGenerationRequest

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post(
    "/generate",
    response_model=APIResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger rule generation",
    description="Generate technical and business DQ rules for a session.",
)
async def generate_rules(
    request: RuleGenerationRequest,
    _: str = Depends(verify_api_key),
) -> APIResponse:
    state = _sessions.get(request.session_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {request.session_id} not found",
        )

    orchestrator = _get_orchestrator()
    try:
        if request.include_technical:
            state = await orchestrator.run_stage_technical_rules(state)
        if request.include_business:
            state = await orchestrator.run_stage_business_rules(state)

        _sessions[request.session_id] = state

        all_rules = state.rule_set.all_rules if state.rule_set else []
        return APIResponse(
            success=True,
            data={
                "session_id": request.session_id,
                "stage": state.current_stage.value,
                "total_rules": len(all_rules),
                "technical_rules": len(state.rule_set.technical_rules) if state.rule_set else 0,
                "business_rules": len(state.rule_set.business_rules) if state.rule_set else 0,
                "message": "Rules generated. Submit approval via POST /approvals/submit",
            },
        )
    except Exception as exc:
        logger.error("rule_generation_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/{session_id}",
    response_model=APIResponse,
    summary="Get generated rules",
    description="Retrieve all generated DQ rules for a session.",
)
async def get_rules(
    session_id: str,
    _: str = Depends(verify_api_key),
) -> APIResponse:
    state = _sessions.get(session_id)
    if not state or not state.rule_set:
        raise HTTPException(status_code=404, detail=f"No rules found for session {session_id}")

    rules = [
        {
            "rule_id": r.rule_id,
            "rule_name": r.rule_name,
            "category": r.rule_category.value,
            "severity": r.severity.value,
            "threshold": r.threshold,
            "table": r.table_name,
            "column": r.column_name,
            "description": r.description,
            "has_sql": bool(r.generated_sql),
            "is_active": r.is_active,
        }
        for r in state.rule_set.all_rules
    ]

    return APIResponse(success=True, data={"session_id": session_id, "rules": rules, "total": len(rules)})


@router.put(
    "/{rule_id}",
    response_model=APIResponse,
    summary="Update a rule",
    description="Update rule properties (severity, threshold, is_active).",
)
async def update_rule(
    rule_id: str,
    update: dict,
    _: str = Depends(verify_api_key),
) -> APIResponse:
    session_id = update.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required in request body")

    state = _sessions.get(session_id)
    if not state or not state.rule_set:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    all_rules = state.rule_set.all_rules
    target = next((r for r in all_rules if r.rule_id == rule_id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")

    from schemas.models import Severity
    from datetime import datetime
    if "severity" in update:
        target.severity = Severity(update["severity"].upper())
    if "threshold" in update:
        target.threshold = float(update["threshold"])
    if "is_active" in update:
        target.is_active = bool(update["is_active"])
    target.updated_at = datetime.utcnow()

    return APIResponse(success=True, data={"rule_id": rule_id, "updated": True}, message="Rule updated")


@router.delete(
    "/{rule_id}",
    response_model=APIResponse,
    summary="Remove a rule",
    description="Mark a rule as inactive.",
)
async def delete_rule(
    rule_id: str,
    session_id: str,
    _: str = Depends(verify_api_key),
) -> APIResponse:
    state = _sessions.get(session_id)
    if not state or not state.rule_set:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    all_rules = state.rule_set.all_rules
    target = next((r for r in all_rules if r.rule_id == rule_id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")

    target.is_active = False
    return APIResponse(success=True, data={"rule_id": rule_id, "deactivated": True})
