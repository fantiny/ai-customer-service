from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from ..dependencies import get_chat_service, get_current_user_id, get_container
from ..schemas import ChatReplyPayload, ChatRequest, HistoryResponse, MessageOut, ResumeRequest
from ...use_cases.chat_service import ChatResponse as _ServiceResponse, ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


def _to_api_response(svc_resp: _ServiceResponse) -> ChatReplyPayload:
    """Translate service-layer ChatResponse → HTTP ChatReplyPayload."""
    return ChatReplyPayload(
        thread_id=svc_resp.thread_id,
        reply=svc_resp.reply,
        status=svc_resp.status,
        pending_action=svc_resp.pending_action,
    )


@router.post("", response_model=ChatReplyPayload, status_code=status.HTTP_200_OK)
async def post_message(
    body: ChatRequest,
    user_id: str = Depends(get_current_user_id),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatReplyPayload:
    """Send a message and receive a reply.

    If `thread_id` is omitted, a new conversation is started.
    Returns `status=interrupted` when a high-risk order action requires approval.
    """
    thread_id = body.thread_id or chat_service.new_thread_id()
    try:
        result = await chat_service.send_message(thread_id, user_id, body.message)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Graph execution error: {exc}",
        ) from exc
    return _to_api_response(result)


@router.get("/{thread_id}", response_model=HistoryResponse)
async def get_history(
    thread_id: str,
    user_id: str = Depends(get_current_user_id),
    chat_service: ChatService = Depends(get_chat_service),
) -> HistoryResponse:
    """Retrieve the full message history for a conversation thread."""
    conversation = await chat_service.get_history(thread_id)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread '{thread_id}' not found",
        )
    return HistoryResponse(
        thread_id=conversation.thread_id,
        user_id=conversation.user_id,
        messages=[
            MessageOut(
                role=m.role.value,
                content=m.content,
                timestamp=m.timestamp.isoformat(),
            )
            for m in conversation.messages
        ],
    )


@router.get("/sessions/mine", tags=["chat"])
async def list_my_sessions(
    user_id: str = Depends(get_current_user_id),
    container=Depends(get_container),
) -> JSONResponse:
    """Return the current user's past session summaries, newest first."""
    repo = container.session_repo
    sessions = await repo.list_by_user(user_id, limit=30)
    return JSONResponse(content=sessions)


@router.post("/{thread_id}/resume", response_model=ChatReplyPayload)
async def resume_hitl(
    thread_id: str,
    body: ResumeRequest,
    user_id: str = Depends(get_current_user_id),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatReplyPayload:
    """Resume a graph interrupted for Human-in-the-Loop approval.

    Send `approved: true` to proceed with the high-risk action,
    or `approved: false` to cancel it.
    """
    try:
        result = await chat_service.resume_hitl(
            thread_id, user_id, {"approved": body.approved, "notes": body.reviewer_notes}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Resume error: {exc}",
        ) from exc
    return _to_api_response(result)
