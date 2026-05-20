from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(
        default=None,
        description="Conversation thread ID. Omit to start a new conversation.",
    )


class ChatReplyPayload(BaseModel):
    """HTTP response schema for POST /chat and POST /chat/{thread_id}/resume.

    Named distinctly from use_cases.chat_service.ChatResponse (the service-layer
    dataclass) to avoid import aliasing and reader confusion.
    """
    thread_id: str
    reply: str | None = None
    status: Literal["complete", "interrupted", "error"] = "complete"
    pending_action: dict | None = Field(
        default=None,
        description="Populated when status='interrupted'; contains action details for HITL review.",
    )


class ResumeRequest(BaseModel):
    approved: bool
    reviewer_notes: str = ""


class MessageOut(BaseModel):
    role: str
    content: str
    timestamp: str


class HistoryResponse(BaseModel):
    thread_id: str
    user_id: str
    messages: list[MessageOut]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str = "0.1.0"
