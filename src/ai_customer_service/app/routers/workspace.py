"""Workspace REST API — tickets, sessions, status events.

Endpoints:
  GET  /api/workspace/tickets              → list open tickets (or filter by status)
  GET  /api/workspace/tickets/{ticket_id}  → single ticket detail
  POST /api/workspace/tickets/{ticket_id}/resolve → close a ticket
  GET  /api/workspace/tickets/{ticket_id}/events  → audit timeline
  GET  /api/workspace/queue                → HITL/human session queue
  GET  /api/workspace/sessions             → all in-memory sessions
"""
from __future__ import annotations

import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...adapters.repositories.agent_repository import PGAgentRepository
from ...adapters.repositories.business_rules_repository import BusinessRulesRepository
from ...adapters.repositories.message_repository import MessageRepository
from ...adapters.repositories.prompt_repository import PromptRepository
from ...adapters.repositories.ticket_repository import PGTicketRepository, StatusEventRepository
from ..dependencies import get_container

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


# ── Dependency helpers ────────────────────────────────────────────────────────

def _ticket_repo(container=Depends(get_container)) -> PGTicketRepository:
    return container.ticket_repo


def _event_repo(container=Depends(get_container)) -> StatusEventRepository:
    return container.event_repo


def _agent_repo(container=Depends(get_container)) -> PGAgentRepository:
    return container.agent_repo


def _rules_repo(container=Depends(get_container)) -> BusinessRulesRepository:
    return container.rules_repo


def _prompt_repo(container=Depends(get_container)) -> PromptRepository:
    return container.prompt_repo


def _message_repo(container=Depends(get_container)) -> MessageRepository:
    return container.message_repo


def _db_pool(container=Depends(get_container)) -> asyncpg.Pool:
    return container.db_pool


# ── Schemas ───────────────────────────────────────────────────────────────────

class ResolveRequest(BaseModel):
    agent_id: str = "api"
    resolution: str | None = None


# ── Ticket routes ─────────────────────────────────────────────────────────────

@router.get("/tickets")
async def list_tickets(
    status: str | None = Query(None, description="Filter: open|in_progress|pending_reply|resolved|closed"),
    date_from: str | None = Query(None, description="ISO date string, e.g. 2025-01-01"),
    limit: int = Query(50, ge=1, le=200),
    ticket_repo: PGTicketRepository = Depends(_ticket_repo),
) -> JSONResponse:
    """Return tickets filtered by status and/or date."""
    if status is None and date_from is None:
        tickets = await ticket_repo.list_open()
    else:
        from datetime import datetime, timezone
        date_from_dt = datetime.fromisoformat(date_from) if date_from else None
        tickets = await ticket_repo.list_all(status=status, date_from=date_from_dt, limit=limit)

    return JSONResponse(content=[_ticket_dict(t) for t in tickets])


@router.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    ticket_repo: PGTicketRepository = Depends(_ticket_repo),
) -> JSONResponse:
    ticket = await ticket_repo.get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return JSONResponse(content=_ticket_dict(ticket))


def _db_pool(container=Depends(get_container)) -> asyncpg.Pool:
    return container.db_pool


@router.post("/tickets/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: str,
    body: ResolveRequest,
    ticket_repo: PGTicketRepository = Depends(_ticket_repo),
    pool: asyncpg.Pool = Depends(_db_pool),
) -> JSONResponse:
    """Close a ticket via REST (alternative to socket resolve_session event).

    Routes through WorkspaceService so that:
    - In-memory session state is updated (mode → ai, resolved_at set)
    - status_events audit trail is written
    - All connected agents receive queue_updated + all_sessions_updated via socket
    """
    from ...app.workspace import socket_server as ss

    ticket = await ticket_repo.get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.status in ("resolved", "closed"):
        return JSONResponse(content={"success": True, "message": "已是结单状态", "ticket": _ticket_dict(ticket)})

    try:
        ws = ss.get_workspace_service()
    except RuntimeError:
        # socket_server not initialised (e.g. integration tests) — fall back to
        # direct repo update so the endpoint still works, just without broadcast.
        ws = None

    if ws is not None:
        # Full path: WorkspaceService handles in-memory + DB + audit event + close report
        resolved_ticket = await ws.resolve_ticket(ticket.session_id, body.agent_id, body.resolution)
        await ss.broadcast_queue_update()
        return JSONResponse(content={"success": True, "ticket": _ticket_dict(resolved_ticket)})

    # Fallback: direct DB update (no broadcast, no in-memory sync)
    import uuid
    from datetime import datetime, timezone
    from ...domain.entities import StatusEvent

    now = datetime.now(timezone.utc)
    old_status = ticket.status
    ticket.status = "resolved"
    ticket.resolution = body.resolution
    ticket.resolved_at = now
    ticket.updated_at = now
    await ticket_repo.update(ticket)

    try:
        from ...adapters.repositories.ticket_repository import StatusEventRepository
        evr = StatusEventRepository(pool)
        await evr.record(StatusEvent(
            event_id=f"evt-{uuid.uuid4().hex[:12]}",
            session_id=ticket.session_id,
            ticket_id=ticket_id,
            from_status=old_status,
            to_status="resolved",
            actor=body.agent_id,
            note=body.resolution or "API 结单（无广播）",
            occurred_at=now,
        ))
    except Exception:
        pass  # event write is best-effort in fallback path

    return JSONResponse(content={"success": True, "ticket": _ticket_dict(ticket)})


@router.get("/tickets/{ticket_id}/events")
async def get_ticket_events(
    ticket_id: str,
    ticket_repo: PGTicketRepository = Depends(_ticket_repo),
    event_repo: StatusEventRepository = Depends(_event_repo),
) -> JSONResponse:
    ticket = await ticket_repo.get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    events = await event_repo.list_for_session(ticket.session_id)
    return JSONResponse(content=[
        {
            "event_id": e.event_id,
            "from_status": e.from_status,
            "to_status": e.to_status,
            "actor": e.actor,
            "note": e.note,
            "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
        }
        for e in events
    ])


# ── Agent routes ─────────────────────────────────────────────────────────────

@router.get("/agents")
async def list_agents(
    online_only: bool = Query(False),
    agent_repo: PGAgentRepository = Depends(_agent_repo),
) -> JSONResponse:
    """List all agents, optionally filtered to online only."""
    agents = await agent_repo.list_online() if online_only else await agent_repo.list_all()
    return JSONResponse(content=[
        {
            "agent_id": a.agent_id,
            "name": a.name,
            "status": a.status,
            "current_session_ids": a.current_session_ids,
        }
        for a in agents
    ])


# ── Metrics (Phase 5) ─────────────────────────────────────────────────────────

@router.get("/metrics/today")
async def metrics_today(
    ticket_repo: PGTicketRepository = Depends(_ticket_repo),
    pool: asyncpg.Pool = Depends(_db_pool),
) -> JSONResponse:
    """Return today's customer-service KPIs."""
    from datetime import date, datetime, timezone
    today = date.today().isoformat()
    today_dt = datetime.combine(date.today(), datetime.min.time())
    all_tickets = await ticket_repo.list_all(date_from=today_dt, limit=1000)

    total = len(all_tickets)
    resolved = sum(1 for t in all_tickets if t.status in ("resolved", "closed"))
    escalated = sum(1 for t in all_tickets if t.assigned_agent_id)
    ai_resolved = resolved - escalated if resolved > escalated else 0

    resolve_times: list[float] = []
    for t in all_tickets:
        if t.resolved_at and t.created_at:
            delta = (t.resolved_at - t.created_at).total_seconds() / 60
            resolve_times.append(delta)
    avg_resolve = round(sum(resolve_times) / len(resolve_times), 1) if resolve_times else 0

    # First-response: proxy via resolved ticket timings
    first_response_ms_list: list[float] = []
    for t in all_tickets:
        if t.resolved_at and t.created_at:
            ms = (t.resolved_at - t.created_at).total_seconds() * 1000
            first_response_ms_list.append(ms)
    avg_first_response_ms = round(
        sum(first_response_ms_list) / len(first_response_ms_list)
    ) if first_response_ms_list else 0

    # HITL decisions persisted via record_hitl_decision → status_events
    async with pool.acquire() as conn:
        hitl_row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE note = 'hitl_approved')  AS approvals,
                COUNT(*) FILTER (WHERE note = 'hitl_rejected')  AS rejections
            FROM status_events
            WHERE occurred_at >= $1
              AND note IN ('hitl_approved', 'hitl_rejected')
            """,
            today_dt,
        )
    hitl_approvals = int(hitl_row["approvals"]) if hitl_row else 0
    hitl_rejections = int(hitl_row["rejections"]) if hitl_row else 0

    return JSONResponse(content={
        "date": today,
        "total_sessions": total,
        "ai_resolved": ai_resolved,
        "escalated_to_human": escalated,
        "resolved": resolved,
        "avg_resolve_min": avg_resolve,
        "hitl_approvals": hitl_approvals,
        "hitl_rejections": hitl_rejections,
        "avg_first_response_ms": avg_first_response_ms,
    })


# ── Business rules (Phase 7) ──────────────────────────────────────────────────

@router.get("/admin/rules", tags=["admin"])
async def list_rules(
    rules_repo: BusinessRulesRepository = Depends(_rules_repo),
) -> JSONResponse:
    return JSONResponse(content=await rules_repo.get_all())


class RuleUpdateRequest(BaseModel):
    value: Any
    description: str | None = None


@router.put("/admin/rules/{key}", tags=["admin"])
async def update_rule(
    key: str,
    body: RuleUpdateRequest,
    rules_repo: BusinessRulesRepository = Depends(_rules_repo),
) -> JSONResponse:
    await rules_repo.set(key, body.value, body.description)
    return JSONResponse(content={"success": True, "key": key, "value": body.value})


@router.delete("/admin/rules/{key}", tags=["admin"])
async def delete_rule(
    key: str,
    rules_repo: BusinessRulesRepository = Depends(_rules_repo),
) -> JSONResponse:
    await rules_repo.delete(key)
    return JSONResponse(content={"success": True, "key": key})


@router.get("/admin/rules/{key}/history", tags=["admin"])
async def get_rule_history(
    key: str,
    limit: int = 20,
    rules_repo: BusinessRulesRepository = Depends(_rules_repo),
) -> JSONResponse:
    history = await rules_repo.get_history(key, limit=limit)
    return JSONResponse(content={"rule_key": key, "history": history})


# ── Prompt management (Phase 8) ───────────────────────────────────────────────

@router.get("/admin/prompts", tags=["admin"])
async def list_prompt_nodes(
    prompt_repo: PromptRepository = Depends(_prompt_repo),
) -> JSONResponse:
    nodes = await prompt_repo.list_nodes()
    return JSONResponse(content=nodes)  # returns array directly


@router.get("/admin/prompts/{node_name}", tags=["admin"])
async def get_prompt_history(
    node_name: str,
    prompt_repo: PromptRepository = Depends(_prompt_repo),
) -> JSONResponse:
    history = await prompt_repo.get_history(node_name)
    active = await prompt_repo.get_active_prompt(node_name)
    active_version = next((h["version"] for h in history if h["active"]), 0)
    return JSONResponse(content={
        "node_name": node_name,
        "active_content": active or "",
        "active_version": active_version,
        "history": history,
    })


class PublishPromptRequest(BaseModel):
    content: str


@router.post("/admin/prompts/{node_name}", tags=["admin"])
async def publish_prompt(
    node_name: str,
    body: PublishPromptRequest,
    prompt_repo: PromptRepository = Depends(_prompt_repo),
) -> JSONResponse:
    prompt_id, version = await prompt_repo.publish_prompt(node_name, body.content)
    return JSONResponse(content={"success": True, "prompt_id": prompt_id, "node_name": node_name, "version": version})


class ActivateVersionRequest(BaseModel):
    prompt_id: str


@router.post("/admin/prompts/{node_name}/activate-version", tags=["admin"])
async def activate_prompt_version(
    node_name: str,
    body: ActivateVersionRequest,
    prompt_repo: PromptRepository = Depends(_prompt_repo),
) -> JSONResponse:
    """Re-publish an older prompt version as the new active version (rollback)."""
    try:
        prompt_id, version = await prompt_repo.activate_version(node_name, body.prompt_id)
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    return JSONResponse(content={"success": True, "prompt_id": prompt_id, "node_name": node_name, "version": version})


# ── Analytics (Phase 6+) ──────────────────────────────────────────────────────

@router.get("/analytics")
async def get_analytics(
    days: int = Query(7, ge=1, le=90, description="Rolling window in days"),
    ticket_repo: PGTicketRepository = Depends(_ticket_repo),
    message_repo: MessageRepository = Depends(_message_repo),
    pool: asyncpg.Pool = Depends(_db_pool),
) -> JSONResponse:
    """Business analytics dashboard: message volume, intent distribution, CSAT, resolution rates.

    Returns aggregated metrics for the specified rolling window (default: 7 days).
    """
    from datetime import date, datetime, timedelta, timezone
    cutoff_date = date.today() - timedelta(days=days)
    cutoff = datetime.combine(cutoff_date, datetime.min.time())

    # Ticket-level stats
    all_tickets = await ticket_repo.list_all(date_from=cutoff, limit=5000)
    total = len(all_tickets)
    resolved = sum(1 for t in all_tickets if t.status in ("resolved", "closed"))
    escalated = sum(1 for t in all_tickets if t.assigned_agent_id)
    ai_resolved = sum(
        1 for t in all_tickets
        if t.status in ("resolved", "closed") and not t.assigned_agent_id
    )

    # Category distribution
    category_counts: dict[str, int] = {}
    for t in all_tickets:
        cat = t.category or "uncategorized"
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # Resolution type distribution (from structured close report)
    resolution_type_counts: dict[str, int] = {}
    for t in all_tickets:
        rt = t.report_resolution_type or "unknown"
        resolution_type_counts[rt] = resolution_type_counts.get(rt, 0) + 1

    # CSAT (ratings 1-5)
    ratings = [t.rating for t in all_tickets if t.rating is not None]
    csat_avg = round(sum(ratings) / len(ratings), 2) if ratings else None
    csat_distribution = {str(i): ratings.count(i) for i in range(1, 6)}

    # Sentiment at session start
    sentiment_start_counts: dict[str, int] = {}
    for t in all_tickets:
        s = t.report_sentiment_start or "unknown"
        sentiment_start_counts[s] = sentiment_start_counts.get(s, 0) + 1

    # AI quality assessment
    ai_quality_counts: dict[str, int] = {}
    for t in all_tickets:
        q = t.report_ai_quality or "unknown"
        ai_quality_counts[q] = ai_quality_counts.get(q, 0) + 1

    # Avg resolve time (minutes)
    resolve_times: list[float] = []
    for t in all_tickets:
        if t.resolved_at and t.created_at:
            delta = (t.resolved_at - t.created_at).total_seconds() / 60
            resolve_times.append(delta)
    avg_resolve_min = round(sum(resolve_times) / len(resolve_times), 1) if resolve_times else None

    # Message-level analytics from session_messages table
    daily_volume = await message_repo.daily_volume(days=days)
    node_distribution = await message_repo.node_distribution(days=days)
    escalation_by_node = await message_repo.escalation_by_node(days=days)
    avg_bot_response_ms = await message_repo.avg_bot_response_ms(days=days)

    # HITL decision counts from status_events
    async with pool.acquire() as conn:
        hitl_analytics_row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS total
            FROM status_events
            WHERE occurred_at >= NOW() - ($1 || ' days')::interval
              AND note IN ('hitl_approved', 'hitl_rejected')
            """,
            str(days),
        )
    hitl_count = int(hitl_analytics_row["total"]) if hitl_analytics_row else 0

    # Build sorted top_intents and category_distribution arrays for chart components
    top_intents = sorted(
        [{"intent": item["node"], "count": item["count"]} for item in node_distribution],
        key=lambda x: x["count"], reverse=True,
    )[:10]
    category_distribution = sorted(
        [{"category": k, "count": v} for k, v in category_counts.items()],
        key=lambda x: x["count"], reverse=True,
    )

    return JSONResponse(content={
        # Flat numeric fields (used by both DigestSection and AgentWorkspace AnalyticsPanel)
        "period_days": days,
        "tickets": total,           # total count as number
        "total_sessions": total,    # alias for compatibility
        "ai_resolved": ai_resolved,
        "resolved_count": resolved,
        "open_count": total - resolved,
        "escalated_to_human": escalated,
        "hitl_count": hitl_count,
        "avg_resolution_minutes": avg_resolve_min,
        "avg_bot_response_ms": avg_bot_response_ms,
        "resolution_rate": round(resolved / total, 3) if total else 0,
        # Dict fields
        "categories": category_counts,
        "resolution_types": resolution_type_counts,
        "sentiment_at_start": sentiment_start_counts,
        "ai_quality": ai_quality_counts,
        "csat": {
            "avg_rating": csat_avg,
            "count": len(ratings),
        },
        "daily_volume": [{"date": d["date"], "count": d["sessions"]} for d in daily_volume],
        "intent_distribution": {item["node"]: item["count"] for item in node_distribution},
        "escalation_by_node": escalation_by_node,
        # Array fields for bar charts
        "top_intents": top_intents,
        "category_distribution": category_distribution,
    })


# ── Conversation replay ───────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    exclude_system: bool = Query(False, description="Exclude system-role messages"),
    ticket_repo: PGTicketRepository = Depends(_ticket_repo),
    message_repo: MessageRepository = Depends(_message_repo),
    event_repo: StatusEventRepository = Depends(_event_repo),
) -> JSONResponse:
    """Return the full conversation chain for a session.

    Includes every message (user/bot/agent/system) in chronological order,
    plus the linked ticket and status audit trail — suitable for conversation replay
    and CS quality review.
    """
    # Resolve linked ticket
    ticket = await ticket_repo.get_by_session(session_id)

    # All messages (canonical store)
    messages = await message_repo.list_for_session(session_id, exclude_system=exclude_system)

    # Role-level counts
    counts = await message_repo.count_by_role(session_id)

    # Status audit timeline
    events = await event_repo.list_for_session(session_id)

    return JSONResponse(content={
        "session_id": session_id,
        "ticket": _ticket_dict(ticket) if ticket else None,
        "message_counts": counts,
        "messages": [
            {
                "message_id": m.message_id,
                "role": m.role,
                "content": m.content,
                "agent_id": m.agent_id,
                "node_name": m.node_name,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "status_timeline": [
            {
                "event_id": e.event_id,
                "from_status": e.from_status,
                "to_status": e.to_status,
                "actor": e.actor,
                "note": e.note,
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            }
            for e in events
        ],
    })


# ── Agent internal notes ─────────────────────────────────────────────────────

class AddNoteRequest(BaseModel):
    content: str
    agent_id: str


@router.post("/sessions/{session_id}/notes", tags=["workspace"])
async def add_session_note(
    session_id: str,
    body: AddNoteRequest,
    message_repo: MessageRepository = Depends(_message_repo),
) -> JSONResponse:
    """Append an internal agent note to a session. Notes use role='note' and are
    never shown to the customer — they appear only in the AgentWorkspace view.
    """
    import uuid as _uuid
    from ...domain.entities import SessionMessage as _SM
    from datetime import datetime as _dt, timezone

    if not body.content.strip():
        return JSONResponse(status_code=422, content={"error": "Note content cannot be empty"})

    note = _SM(
        message_id=f"note-{_uuid.uuid4().hex[:10]}",
        session_id=session_id,
        ticket_id=None,
        role="note",
        content=body.content.strip(),
        agent_id=body.agent_id or None,
        node_name=None,
        created_at=_dt.now(timezone.utc),
    )
    await message_repo.save(note)
    return JSONResponse(content={
        "success": True,
        "message_id": note.message_id,
        "session_id": session_id,
        "created_at": note.created_at.isoformat(),
    })


@router.get("/sessions/{session_id}/notes", tags=["workspace"])
async def get_session_notes(
    session_id: str,
    message_repo: MessageRepository = Depends(_message_repo),
) -> JSONResponse:
    """Return all internal notes for a session, ordered by creation time."""
    messages = await message_repo.list_for_session(session_id, exclude_system=False)
    notes = [
        {
            "message_id": m.message_id,
            "content": m.content,
            "agent_id": m.agent_id,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages if m.role == "note"
    ]
    return JSONResponse(content={"session_id": session_id, "notes": notes})


# ── CSAT (customer satisfaction rating) ─────────────────────────────────────

class CsatRequest(BaseModel):
    rating: int   # 1–5 stars submitted by the customer after session ends


@router.post("/sessions/{session_id}/csat", tags=["customer"])
async def submit_csat(
    session_id: str,
    body: CsatRequest,
    ticket_repo: PGTicketRepository = Depends(_ticket_repo),
) -> JSONResponse:
    """Customer submits a 1–5 star rating after their session ends.

    Called from CustomerPortal once a session is resolved or closed.
    No JWT needed — session_id is the opaque token the customer already holds.
    Rating is validated (1–5) and stored on the linked Ticket row.
    """
    from datetime import datetime, timezone

    if not 1 <= body.rating <= 5:
        raise HTTPException(status_code=422, detail="Rating must be 1–5")

    ticket = await ticket_repo.get_by_session(session_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Session not found")

    ticket.rating = body.rating
    ticket.updated_at = datetime.now(timezone.utc)
    await ticket_repo.update(ticket)
    return JSONResponse(content={"session_id": session_id, "rating": body.rating, "status": "ok"})


# ── Knowledge base (FAQ) management ──────────────────────────────────────────
# All SQL is centralised in FAQDocumentRepository; these endpoints are thin HTTP adapters.

from ...adapters.repositories.faq_document_repository import FAQDocumentRepository


class KnowledgeDocRequest(BaseModel):
    content: str
    title: str
    category: str = "wedding_dress_faq"


def _faq_repo(container=Depends(get_container)) -> FAQDocumentRepository:
    return FAQDocumentRepository(container.db_pool)


def _doc_to_dict(doc: Any, *, preview_only: bool = False) -> dict:
    """Serialise a FAQDocumentRow to a JSON-safe dict."""
    return {
        "doc_id":        doc.doc_id,
        "title":         doc.title,
        "category":      doc.category,
        "knowledge_type": getattr(doc, "knowledge_type", "industry_knowledge"),
        "content":       doc.content[:100] if preview_only else doc.content,
        "has_embedding": doc.has_embedding,
        "created_at":    doc.created_at.isoformat() if doc.created_at else None,
    }


@router.get("/admin/knowledge", tags=["admin"])
async def list_knowledge_docs(
    repo: FAQDocumentRepository = Depends(_faq_repo),
) -> JSONResponse:
    """List all FAQ docs with id, title, category and a 100-char content preview."""
    docs = await repo.list_all()
    return JSONResponse(content=[_doc_to_dict(d, preview_only=True) for d in docs])


@router.post("/admin/knowledge/embed-all", tags=["admin"])
async def embed_all_knowledge_docs(
    category: str = Query("wedding_dress_faq"),
    container=Depends(get_container),
    repo: FAQDocumentRepository = Depends(_faq_repo),
) -> JSONResponse:
    """Generate embeddings for all FAQ documents that currently have NULL embeddings."""
    pending = await repo.list_without_embedding(category)
    if not pending:
        return JSONResponse(content={"success": True, "embedded": 0, "message": "No documents need embedding."})

    try:
        embedding_client = container.embedding_client
        texts = [r["content"] for r in pending]
        vectors = await embedding_client.aembed_documents(texts)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Embedding generation failed: {exc}")

    items = [{"doc_id": r["doc_id"], "vector": v} for r, v in zip(pending, vectors)]
    count = await repo.save_embeddings_batch(items)
    # Rebuild in-memory BM25 index so new docs are immediately searchable
    await container.refresh_retrievers()
    return JSONResponse(content={"success": True, "embedded": count,
                                  "message": f"Generated embeddings for {count} documents."})


@router.post("/admin/knowledge/{doc_id}/embed", tags=["admin"])
async def embed_knowledge_doc(
    doc_id: str,
    container=Depends(get_container),
    repo: FAQDocumentRepository = Depends(_faq_repo),
) -> JSONResponse:
    """Generate and store the embedding vector for a single FAQ document."""
    doc = await repo.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        embedding_client = container.embedding_client
        vectors = await embedding_client.aembed_documents([doc.content])
        vector = vectors[0]
    except Exception as exc:
        raise HTTPException(status_code=503,
                            detail=f"Embedding generation failed: {exc}. Check EMBEDDING_API_KEY.")

    await repo.save_embedding(doc_id, vector)
    await container.refresh_retrievers()
    return JSONResponse(content={"success": True, "doc_id": doc_id,
                                  "embedding_dims": len(vector),
                                  "message": "Embedding generated and stored. Document is now searchable."})


@router.get("/admin/knowledge/{doc_id}", tags=["admin"])
async def get_knowledge_doc(
    doc_id: str,
    repo: FAQDocumentRepository = Depends(_faq_repo),
) -> JSONResponse:
    """Return full doc content + metadata."""
    doc = await repo.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return JSONResponse(content=_doc_to_dict(doc))


@router.post("/admin/knowledge", tags=["admin"])
async def create_knowledge_doc(
    body: KnowledgeDocRequest,
    repo: FAQDocumentRepository = Depends(_faq_repo),
) -> JSONResponse:
    """Create a new FAQ entry. Embedding is NULL until /embed is called."""
    doc = await repo.create(body.content, body.title, body.category)
    return JSONResponse(status_code=201, content={
        **_doc_to_dict(doc),
        "note": "Embedding is NULL. Call POST /admin/knowledge/{doc_id}/embed to enable vector search.",
    })


@router.put("/admin/knowledge/{doc_id}", tags=["admin"])
async def update_knowledge_doc(
    doc_id: str,
    body: KnowledgeDocRequest,
    repo: FAQDocumentRepository = Depends(_faq_repo),
) -> JSONResponse:
    """Update content and metadata. Clears embedding — re-embed to update vector search."""
    doc = await repo.update(doc_id, body.content, body.title, body.category)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return JSONResponse(content={
        **_doc_to_dict(doc),
        "note": "Content updated. Embedding was cleared — call POST /admin/knowledge/{doc_id}/embed to refresh.",
    })


@router.delete("/admin/knowledge/{doc_id}", tags=["admin"])
async def delete_knowledge_doc(
    doc_id: str,
    repo: FAQDocumentRepository = Depends(_faq_repo),
) -> JSONResponse:
    """Hard-delete a FAQ document by doc_id."""
    deleted = await repo.delete(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return JSONResponse(content={"success": True, "doc_id": doc_id})


# ── Agent knowledge search (non-admin, used from AgentWorkspace sidebar) ─────

from ...use_cases.faq_service import FAQService as _FAQService


def _faq_service(container=Depends(get_container)) -> _FAQService:
    return container.faq_service


@router.get("/knowledge/search", tags=["workspace"])
async def agent_knowledge_search(
    q: str = Query(..., min_length=1, max_length=200),
    faq_svc: _FAQService = Depends(_faq_service),
) -> JSONResponse:
    """Full-text + semantic search of the FAQ knowledge base.

    Designed for the AgentWorkspace sidebar — returns up to 5 results with
    title, snippet, knowledge_type. Requires a non-empty query string.
    """
    try:
        docs = await faq_svc.retrieve(q)
    except Exception:
        return JSONResponse(content={"results": []})

    results = []
    for doc in docs[:5]:
        meta = doc.metadata or {}
        results.append({
            "doc_id":         doc.doc_id,
            "title":          meta.get("title", ""),
            "knowledge_type": meta.get("knowledge_type", "industry_knowledge"),
            "snippet":        doc.content[:200],
            "score":          round(float(doc.score or 0), 3) if doc.score is not None else None,
        })
    return JSONResponse(content={"results": results})


# ── Daily digest ──────────────────────────────────────────────────────────────
from ...use_cases.digest_service import DigestService as _DigestService


def _digest_svc(container=Depends(get_container)) -> _DigestService:
    return container.digest_service


@router.get("/admin/digest", tags=["admin"])
async def list_digests(
    days: int = Query(7, ge=1, le=90),
    svc: _DigestService = Depends(_digest_svc),
) -> JSONResponse:
    """List recent daily digests (most recent first)."""
    return JSONResponse(content=await svc.list_recent(days))


@router.get("/admin/digest/{report_date}", tags=["admin"])
async def get_digest(
    report_date: str,
    svc: _DigestService = Depends(_digest_svc),
) -> JSONResponse:
    from datetime import date
    try:
        d = date.fromisoformat(report_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
    result = await svc.get(d)
    if not result:
        raise HTTPException(status_code=404, detail="Digest not found for this date")
    return JSONResponse(content=result)


@router.post("/admin/digest/generate", tags=["admin"])
async def generate_digest(
    report_date: str | None = Query(None, description="YYYY-MM-DD, defaults to yesterday"),
    svc: _DigestService = Depends(_digest_svc),
) -> JSONResponse:
    """Force-generate (or regenerate) the digest for a date."""
    from datetime import date, timedelta
    if report_date:
        try:
            d = date.fromisoformat(report_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
    else:
        d = date.today() - timedelta(days=1)
    metrics = await svc.generate(d)
    return JSONResponse(content={"success": True, "metrics": metrics})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ticket_dict(ticket: Any) -> dict:
    return {
        "ticket_id": ticket.ticket_id,
        "session_id": ticket.session_id,
        "user_id": ticket.user_id,
        "status": ticket.status,
        "category": ticket.category,
        "assigned_agent_id": ticket.assigned_agent_id,
        "tags": ticket.tags,
        "summary": ticket.summary,
        "resolution": ticket.resolution,
        "sentiment": ticket.sentiment,
        "rating": ticket.rating,
        # Structured close-report columns (queryable SQL fields)
        "report_resolution_type": getattr(ticket, "report_resolution_type", None),
        "report_sentiment_start": getattr(ticket, "report_sentiment_start", None),
        "report_key_issues": getattr(ticket, "report_key_issues", []),
        "report_ai_quality": getattr(ticket, "report_ai_quality", None),
        "sla_deadline": ticket.sla_deadline.isoformat() if ticket.sla_deadline else None,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
    }


# ── Product management (admin) ────────────────────────────────────────────────

from ...adapters.repositories.product_repository import ProductRepository as _ProductRepo


def _product_repo(container=Depends(get_container)) -> _ProductRepo:
    return container.product_repo


def _product_to_dict(p: Any) -> dict:
    return {
        "product_id":      p.product_id,
        "name":            p.name,
        "style":           p.style,
        "price":           float(p.price),
        "deposit_rate":    float(p.deposit_rate),
        "production_days": p.production_days,
        "rush_available":  p.rush_available,
        "stock_type":      p.stock_type,
        "colors":          list(p.colors),
        "tags":            list(p.tags),
        "description":     p.description,
        "occasions":       list(p.occasions),
        "active":          p.active,
        "purchase_url":    p.purchase_url,
    }


@router.get("/admin/products", tags=["admin"])
async def list_products_admin(
    repo: _ProductRepo = Depends(_product_repo),
) -> JSONResponse:
    """List all products including inactive (admin view)."""
    products = await repo.list_all_admin()
    return JSONResponse(content=[_product_to_dict(p) for p in products])


class ProductUpdateBody(BaseModel):
    name: str | None = None
    style: str | None = None
    price: float | None = None
    deposit_rate: float | None = None
    production_days: int | None = None
    rush_available: bool | None = None
    stock_type: str | None = None
    colors: list[str] | None = None
    tags: list[str] | None = None
    description: str | None = None
    occasions: list[str] | None = None
    active: bool | None = None
    purchase_url: str | None = None


@router.put("/admin/products/{product_id}", tags=["admin"])
async def update_product(
    product_id: str,
    body: ProductUpdateBody,
    repo: _ProductRepo = Depends(_product_repo),
) -> JSONResponse:
    """Update product fields. Primarily used for setting/updating purchase_url."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = await repo.update_product(product_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Product not found")
    return JSONResponse(content=_product_to_dict(updated))


class ProductCreateBody(BaseModel):
    product_id: str
    name: str
    style: str
    price: float
    deposit_rate: float = 0.30
    production_days: int
    rush_available: bool = False
    stock_type: str = "custom"
    colors: list[str] = []
    tags: list[str] = []
    description: str = ""
    occasions: list[str] = []
    active: bool = True
    purchase_url: str = ""


@router.post("/admin/products", tags=["admin"])
async def create_product(
    body: ProductCreateBody,
    repo: _ProductRepo = Depends(_product_repo),
) -> JSONResponse:
    """Create a new product entry."""
    created = await repo.create_product(body.model_dump())
    return JSONResponse(content=_product_to_dict(created), status_code=201)
