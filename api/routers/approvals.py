"""Approvals API endpoints — human-in-the-loop checkpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from api.middleware.auth import verify_api_key
from api.routers.discovery import _sessions, _get_orchestrator
from schemas.models import APIResponse, ApprovalRequest, ApprovalStatus

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post(
    "/submit",
    response_model=APIResponse,
    summary="Submit approval decision",
    description="Submit APPROVED, REJECTED, or MODIFIED decision for a workflow checkpoint.",
)
async def submit_approval(
    request: ApprovalRequest,
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
        if request.stage == "approval_1":
            state = await orchestrator.process_approval_1(
                state=state,
                status=request.status,
                approver_id=request.approver_id,
                approver_email=request.approver_email,
                comments=request.comments,
                rule_modifications=request.rule_modifications,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown stage: {request.stage}")

        _sessions[request.session_id] = state

        next_action = (
            "Proceed to SQL generation via POST /sql/generate"
            if request.status == ApprovalStatus.APPROVED
            else "Workflow halted. Review rejection comments."
        )

        return APIResponse(
            success=True,
            data={
                "session_id": request.session_id,
                "stage": request.stage,
                "decision": request.status.value,
                "next_action": next_action,
            },
            message=f"Approval {request.status.value} recorded for stage {request.stage}",
        )
    except Exception as exc:
        logger.error("approval_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/{session_id}",
    response_model=APIResponse,
    summary="Get approval status",
    description="Retrieve the current approval status for a session.",
)
async def get_approval_status(
    session_id: str,
    _: str = Depends(verify_api_key),
) -> APIResponse:
    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return APIResponse(
        success=True,
        data={
            "session_id": session_id,
            "approval_1_status": state.approval_1_status.value,
            "approval_2_status": state.approval_2_status.value,
            "current_stage": state.current_stage.value,
        },
    )
