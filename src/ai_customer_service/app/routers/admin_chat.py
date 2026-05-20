"""Admin AI Chat — conversational configuration interface.

POST /api/admin/chat
  body: { "message": str, "thread_id": str? }
  auth: Bearer JWT (any authenticated user)
  returns: { "thread_id": str, "reply": str }

The admin agent is a ReAct LangGraph that can read and write business rules,
knowledge-base documents, and node prompts via structured tool calls.

Each thread_id is a persistent conversation session backed by the same
PostgreSQL checkpointer used by the customer graph — admins can continue
multi-turn configuration dialogues across HTTP requests.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from ...graph.nodes._utils import strip_thinking
from pydantic import BaseModel

from ..dependencies import get_container, require_user
from ...infrastructure.auth import AuthUser

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminChatRequest(BaseModel):
    message: str
    thread_id: str | None = None


@router.post("/chat")
async def admin_chat(
    body: AdminChatRequest,
    user: AuthUser = Depends(require_user),
    container=Depends(get_container),
) -> JSONResponse:
    """Send a message to the admin AI agent and get a configuration-aware reply.

    The agent can read system config, update business rules, manage knowledge-base
    documents, and configure node prompts — all via natural language.

    Thread IDs persist conversation history across requests. Pass the returned
    thread_id in subsequent requests to continue the same session.
    """
    thread_id = body.thread_id or f"admin-{user.user_id}-{uuid.uuid4().hex[:8]}"

    graph = container.admin_graph
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=body.message)]},
        config={"configurable": {"thread_id": thread_id}},
    )

    # Extract the last AI message from the result
    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    reply = strip_thinking(ai_messages[-1].content) if ai_messages else "（无回复）"

    return JSONResponse(content={"thread_id": thread_id, "reply": reply})


@router.get("/chat/history/{thread_id}")
async def admin_chat_history(
    thread_id: str,
    user: AuthUser = Depends(require_user),
    container=Depends(get_container),
) -> JSONResponse:
    """Return the conversation history for an admin chat thread.

    Messages are serialized as:
      { "role": "human"|"ai"|"tool", "content": str }

    Tool messages (internal agent steps) are included so the admin UI can
    optionally render the agent's reasoning/tool calls.
    """
    graph = container.admin_graph
    state = await graph.aget_state(
        config={"configurable": {"thread_id": thread_id}}
    )
    if not state or not state.values:
        return JSONResponse(content={"thread_id": thread_id, "messages": []})

    messages = []
    for m in state.values.get("messages", []):
        if isinstance(m, HumanMessage):
            messages.append({"role": "human", "content": m.content})
        elif isinstance(m, AIMessage):
            messages.append({"role": "ai", "content": m.content})
        elif isinstance(m, ToolMessage):
            messages.append({"role": "tool", "content": m.content, "tool_call_id": m.tool_call_id})

    return JSONResponse(content={"thread_id": thread_id, "messages": messages})
