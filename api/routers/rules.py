"""Rules API endpoints — rule generation, retrieval, and management."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from api.middleware.auth import verify_api_key
from api.routers.discovery import _sessions, _get_orchestrator
from schemas.models import APIResponse, DQRule, RuleCategory, RuleGenerationRequest, Severity

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
            state = await orchestrator.run_stage_business_rules(
                state, custom_context=request.custom_context
            )

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
            "source": "business" if r.rule_id.startswith("BRUL_") else "technical",
            "category": r.rule_category.value,
            "severity": r.severity.value,
            "threshold": r.threshold,
            "table": r.table_name,
            "column": r.column_name,
            "description": r.description,
            "rationale": r.rationale,
            "has_sql": bool(r.generated_sql),
            "is_active": r.is_active,
        }
        for r in state.rule_set.all_rules
    ]

    return APIResponse(success=True, data={"session_id": session_id, "rules": rules, "total": len(rules)})


@router.post(
    "/add-custom",
    response_model=APIResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a custom rule",
    description="Add a user-provided SQL rule to the session. The SQL must use @run_id as a named parameter.",
)
async def add_custom_rule(
    body: dict,
    _: str = Depends(verify_api_key),
) -> APIResponse:
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    state = _sessions.get(session_id)
    if not state or not state.rule_set:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found or has no rule set")

    rule_name = body.get("rule_name", "").strip()
    custom_sql = body.get("custom_sql", "").strip()
    if not rule_name:
        raise HTTPException(status_code=400, detail="rule_name is required")
    if not custom_sql:
        raise HTTPException(status_code=400, detail="custom_sql is required")

    cat_str = body.get("category", "validity").lower()
    sev_str = body.get("severity", "WARN").upper()

    try:
        category = RuleCategory(cat_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid category: {cat_str}")
    try:
        severity = Severity(sev_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid severity: {sev_str}")

    from datetime import datetime
    rule = DQRule(
        rule_id=f"CUST_{uuid.uuid4().hex[:8]}",
        rule_name=rule_name,
        rule_category=category,
        description=body.get("description", "User-provided custom rule"),
        severity=severity,
        threshold=float(body.get("threshold", 0.0)),
        project_id=state.project_id,
        dataset_name=state.dataset_id,
        table_name=body.get("table_name", ""),
        column_name=body.get("column_name") or None,
        generated_sql=custom_sql,
        rationale=body.get("rationale"),
        rule_set_version_id=state.rule_set.rule_set_version_id,
        is_active=True,
    )

    state.rule_set.business_rules.append(rule)
    _sessions[session_id] = state

    return APIResponse(
        success=True,
        data={
            "session_id": session_id,
            "rule_id": rule.rule_id,
            "rule_name": rule.rule_name,
            "message": "Custom rule added. It will be included in SQL generation and the consolidated stored procedure.",
        },
    )


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
