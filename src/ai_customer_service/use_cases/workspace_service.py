"""WorkspaceService — business logic layer for the human-agent workspace.

Single representation: sessions are always ``SessionRecord`` objects (domain
entity).  The old ``SessionInfo`` / ``ChatMsg`` dataclasses and the
``_info_to_record`` / ``_record_to_info`` conversion functions have been
removed — the ``ISessionManager`` hot-cache holds ``SessionRecord`` directly.

Ticket lifecycle:
  join_customer()     → Ticket(status=open)
  transfer_to_human() → Ticket → in_progress  + StatusEvent
  handle_user_message (human mode) → keeps Ticket in_progress
  handle_agent_reply  → Ticket → pending_reply + StatusEvent
  resolve_ticket()    → Ticket → resolved      + StatusEvent
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..domain.entities import Agent, SessionMessage, SessionRecord, StatusEvent, Ticket
from .interfaces import (
    IAgentRepository,
    IMessageRepository,
    ISessionManager,
    ISessionRepository,
    IStatusEventRepository,
    ITicketRepository,
    IWorkspaceService,
    UserMessageResult,
)

logger = logging.getLogger(__name__)


class WorkspaceService(IWorkspaceService):
    """Concrete IWorkspaceService with write-through DB persistence and Ticket lifecycle."""

    def __init__(
        self,
        manager: ISessionManager,
        session_repo: ISessionRepository,
        ticket_repo: ITicketRepository,
        event_repo: IStatusEventRepository,
        agent_repo: IAgentRepository | None = None,
        llm: Any = None,
        message_repo: IMessageRepository | None = None,
    ) -> None:
        self._manager = manager
        self._repo = session_repo
        self._tickets = ticket_repo
        self._events = event_repo
        self._agents = agent_repo
        self._llm = llm
        self._messages = message_repo

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _write_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        agent_id: str | None = None,
        node_name: str | None = None,
    ) -> None:
        """Persist a single message to the canonical session_messages table."""
        if not self._messages:
            return
        ticket = await self._get_ticket_or_none(session_id)
        msg = SessionMessage(
            message_id=f"msg-{uuid.uuid4().hex[:14]}",
            session_id=session_id,
            ticket_id=ticket.ticket_id if ticket else None,
            role=role,
            content=content,
            agent_id=agent_id,
            node_name=node_name,
            created_at=datetime.now(timezone.utc),
        )
        await self._messages.save(msg)

    async def _write_event(
        self,
        session_id: str,
        ticket_id: str | None,
        from_status: str,
        to_status: str,
        actor: str,
        note: str | None = None,
    ) -> None:
        event = StatusEvent(
            event_id=f"evt-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            ticket_id=ticket_id,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            note=note,
            occurred_at=datetime.now(timezone.utc),
        )
        try:
            await self._events.record(event)
        except Exception:
            logger.warning(
                "Failed to write status event session=%s %s→%s",
                session_id, from_status, to_status,
                exc_info=True,
            )

    async def _get_ticket_or_none(self, session_id: str) -> Ticket | None:
        try:
            return await self._tickets.get_by_session(session_id)
        except Exception:
            return None

    async def _persist(self, record: SessionRecord) -> None:
        """Write-through: update DB from the current in-memory state."""
        record.updated_at = datetime.now(timezone.utc)
        try:
            await self._repo.save(record)
        except Exception:
            logger.error(
                "Session persistence failed session=%s", record.session_id, exc_info=True
            )

    # ── Startup ───────────────────────────────────────────────────────────────

    async def load_active_sessions(self) -> int:
        """Restore active sessions from DB into the in-memory manager on startup."""
        records = await self._repo.get_active()
        count = 0
        for record in records:
            if self._manager.get(record.session_id) is None:
                self._manager.restore(record)
                count += 1
        if count:
            logger.info("Restored %d active workspace sessions from DB", count)
        return count

    # ── Customer lifecycle ────────────────────────────────────────────────────

    async def join_customer(
        self,
        user_id: str,
        socket_id: str,
        session_id: str | None,
    ) -> SessionRecord:
        """Register or restore a customer session; create Ticket on first join."""
        if session_id:
            # 1. Try hot-cache first
            record = self._manager.get(session_id)
            if record:
                record.socket_id = socket_id
                await self._persist(record)
                return record

            # 2. Try DB (e.g. after restart)
            record = await self._repo.get(session_id)
            if record:
                self._manager.restore(record, socket_id)
                logger.info("Restored session %s from DB user=%s", session_id, user_id)
                return record

        # 3. Brand-new session
        record = self._manager.create(user_id, socket_id)
        await self._persist(record)

        now = datetime.now(timezone.utc)
        ticket = Ticket(
            ticket_id=f"tkt-{uuid.uuid4().hex[:10]}",
            session_id=record.session_id,
            user_id=user_id,
            status="open",
            created_at=now,
            updated_at=now,
        )
        await self._tickets.create(ticket)
        await self._write_event(
            record.session_id, ticket.ticket_id,
            from_status="", to_status="open", actor="system",
            note="客户发起新会话",
        )
        logger.info(
            "Created session=%s ticket=%s user=%s",
            record.session_id, ticket.ticket_id, user_id,
        )
        return record

    # ── Agent lifecycle ───────────────────────────────────────────────────────

    async def join_agent(self, agent_id: str, name: str) -> Agent:
        now = datetime.now(timezone.utc)
        agent = Agent(agent_id=agent_id, name=name, status="online", created_at=now)
        if self._agents:
            await self._agents.save(agent)
        logger.info("join_agent: %s (%s) online", name, agent_id)
        return agent

    async def leave_agent(self, agent_id: str) -> None:
        if self._agents:
            await self._agents.set_status(agent_id, "offline")
        logger.info("leave_agent: %s offline", agent_id)

    async def claim_session(self, session_id: str, agent_id: str) -> Ticket:
        """Assign agent to session ticket (认领); syncs to in-memory record."""
        ticket = await self._get_ticket_or_none(session_id)
        if ticket is None:
            raise ValueError(f"No ticket found for session {session_id!r}")
        if ticket.assigned_agent_id and ticket.assigned_agent_id != agent_id:
            raise ValueError(f"Session already claimed by {ticket.assigned_agent_id}")

        old_status = ticket.status
        ticket.assigned_agent_id = agent_id
        if ticket.status == "open":
            ticket.status = "in_progress"
        ticket.updated_at = datetime.now(timezone.utc)
        await self._tickets.update(ticket)

        # Sync assignment into the in-memory record
        record = self._manager.get(session_id)
        if record:
            record.assigned_agent_id = agent_id
            await self._persist(record)

        await self._write_event(
            session_id, ticket.ticket_id,
            from_status=old_status, to_status=ticket.status,
            actor=agent_id, note=f"顾问 {agent_id} 认领此会话",
        )
        logger.info("claim_session: session=%s agent=%s", session_id, agent_id)
        return ticket

    # ── Message recording ─────────────────────────────────────────────────────

    async def handle_user_message(
        self, session_id: str, content: str
    ) -> UserMessageResult:
        record = self._manager.get(session_id)
        if not record:
            return UserMessageResult(role="user", content=content, error="session_not_found")

        entry = record.add_message("user", content)
        await self._persist(record)
        await self._write_message(session_id, "user", content)

        # In human mode: keep ticket in_progress when customer writes
        if record.mode == "human":
            ticket = await self._get_ticket_or_none(session_id)
            if ticket and ticket.status == "pending_reply":
                old = ticket.status
                ticket.status = "in_progress"
                ticket.updated_at = datetime.now(timezone.utc)
                await self._tickets.update(ticket)
                await self._write_event(
                    session_id, ticket.ticket_id,
                    from_status=old, to_status="in_progress",
                    actor="system", note="客户回复，等待顾问处理",
                )

        return UserMessageResult(
            role="user", content=content,
            timestamp=datetime.fromisoformat(entry["timestamp"]),
        )

    async def handle_agent_reply(
        self, session_id: str, agent_id: str, content: str
    ) -> None:
        record = self._manager.get(session_id)
        if not record:
            logger.warning("handle_agent_reply: session %s not found", session_id)
            return

        record.add_message("agent", content)
        await self._persist(record)
        await self._write_message(session_id, "agent", content, agent_id=agent_id)

        ticket = await self._get_ticket_or_none(session_id)
        if ticket and ticket.status in ("open", "in_progress"):
            old = ticket.status
            ticket.status = "pending_reply"
            ticket.updated_at = datetime.now(timezone.utc)
            await self._tickets.update(ticket)
            await self._write_event(
                session_id, ticket.ticket_id,
                from_status=old, to_status="pending_reply",
                actor=agent_id, note="顾问已回复，等待客户反馈",
            )

    # ── Bot / HITL persistence ────────────────────────────────────────────────

    async def record_bot_message(
        self,
        session_id: str,
        content: str,
        node_name: str | None = None,
        role: str = "bot",
    ) -> None:
        record = self._manager.get(session_id)
        if not record:
            return
        if role == "bot" and record.first_response_at is None:
            record.first_response_at = datetime.now(timezone.utc)
        await self._persist(record)
        if role != "system":
            await self._write_message(session_id, role, content, node_name=node_name)

    async def update_order_context(
        self, session_id: str, order_context: dict
    ) -> None:
        record = self._manager.get(session_id)
        if not record:
            return
        record.order_context = order_context
        await self._persist(record)

    async def record_hitl_state(
        self, session_id: str, pending_action: dict | None
    ) -> None:
        record = self._manager.get(session_id)
        if record:
            await self._persist(record)

    async def record_hitl_decision(
        self, session_id: str, approved: bool, agent_id: str
    ) -> None:
        """Persist a HITL approve/reject event so analytics can count it."""
        note = "hitl_approved" if approved else "hitl_rejected"
        ticket = await self._get_ticket_or_none(session_id)
        await self._write_event(
            session_id,
            ticket.ticket_id if ticket else None,
            from_status="hitl_pending",
            to_status="ai",
            actor=agent_id,
            note=note,
        )

    # ── Mode transitions ──────────────────────────────────────────────────────

    async def transfer_to_human(
        self, session_id: str, reason: str | None
    ) -> SessionRecord:
        record = self._manager.get(session_id)
        if not record:
            raise ValueError(f"Session {session_id!r} not found")

        old_mode = record.mode
        record.mode = "human"
        if reason:
            record.escalation_reason = reason
        await self._persist(record)

        ticket = await self._get_ticket_or_none(session_id)
        if ticket and ticket.status in ("open", "hitl_pending"):
            old_status = ticket.status
            ticket.status = "in_progress"
            ticket.updated_at = datetime.now(timezone.utc)
            await self._tickets.update(ticket)
            await self._write_event(
                session_id, ticket.ticket_id,
                from_status=old_status, to_status="in_progress",
                actor="ai", note=reason or "已转接人工顾问",
            )

        summary = await self._generate_handoff_summary(record.history)
        if summary:
            record.add_message("system", "[AI 接管摘要]\n" + summary)
            if ticket:
                ticket.summary = summary
                await self._tickets.update(ticket)
            await self._persist(record)

        logger.info("transfer_to_human: session=%s reason=%s", session_id, reason)
        return record

    async def transfer_to_ai(
        self, session_id: str, agent_id: str
    ) -> SessionRecord:
        record = self._manager.get(session_id)
        if not record:
            raise ValueError(f"Session {session_id!r} not found")

        old_mode = record.mode
        record.mode = "ai"
        record.pending_action = {}
        record.escalation_reason = None
        await self._persist(record)

        ticket = await self._get_ticket_or_none(session_id)
        await self._write_event(
            session_id, ticket.ticket_id if ticket else None,
            from_status=old_mode, to_status="ai",
            actor=agent_id, note="已交还 AI 顾问处理",
        )

        logger.info("transfer_to_ai: session=%s by_agent=%s", session_id, agent_id)
        return record

    # ── Ticket resolution ─────────────────────────────────────────────────────

    async def resolve_ticket(
        self,
        session_id: str,
        agent_id: str,
        resolution: str | None,
    ) -> Ticket:
        ticket = await self._get_ticket_or_none(session_id)
        now = datetime.now(timezone.utc)

        if ticket is None:
            ticket = Ticket(
                ticket_id=f"tkt-{uuid.uuid4().hex[:10]}",
                session_id=session_id,
                user_id="unknown",
                status="resolved",
                resolution=resolution,
                created_at=now,
                updated_at=now,
                resolved_at=now,
            )
            await self._tickets.create(ticket)
        else:
            old_status = ticket.status
            ticket.status = "resolved"
            ticket.resolution = resolution
            ticket.resolved_at = now
            ticket.updated_at = now
            await self._tickets.update(ticket)
            await self._write_event(
                session_id, ticket.ticket_id,
                from_status=old_status, to_status="resolved",
                actor=agent_id, note=resolution or "顾问已结单",
            )

        record = self._manager.get(session_id)
        if record:
            record.mode = "ai"
            record.resolved_at = now
            await self._persist(record)

        # Auto-categorize if still null
        if ticket.category is None and record and self._llm:
            first_user_msg = next(
                (m["content"] for m in record.history if m["role"] == "user"), ""
            )
            if first_user_msg:
                ticket.category = await self._classify_category(first_user_msg)
                ticket.updated_at = datetime.now(timezone.utc)
                await self._tickets.update(ticket)

        # Async close report (non-blocking)
        if record and self._llm:
            asyncio.create_task(
                self._generate_close_report(ticket, record.history),
                name=f"close_report_{ticket.ticket_id}",
            )

        logger.info(
            "resolve_ticket: session=%s ticket=%s agent=%s",
            session_id, ticket.ticket_id, agent_id,
        )
        return ticket

    async def submit_rating(self, session_id: str, rating: int) -> None:
        if not 1 <= rating <= 5:
            logger.warning("Invalid rating %d for session=%s; ignoring", rating, session_id)
            return
        ticket = await self._get_ticket_or_none(session_id)
        if ticket is None:
            logger.warning("submit_rating: no ticket for session=%s", session_id)
            return
        ticket.rating = rating
        ticket.updated_at = datetime.now(timezone.utc)
        await self._tickets.update(ticket)
        logger.info("CSAT rating=%d stored for ticket=%s", rating, ticket.ticket_id)

    async def auto_categorize_if_needed(
        self, session_id: str, first_message: str
    ) -> None:
        ticket = await self._get_ticket_or_none(session_id)
        if ticket and ticket.category is None and first_message.strip():
            ticket.category = await self._classify_category(first_message)
            ticket.updated_at = datetime.now(timezone.utc)
            await self._tickets.update(ticket)
            logger.info(
                "auto_categorize: ticket=%s category=%s",
                ticket.ticket_id, ticket.category,
            )

    # ── LLM helpers ───────────────────────────────────────────────────────────

    async def _generate_handoff_summary(self, history: list[dict]) -> str:
        if not self._llm or not history:
            return ""
        recent = "\n".join(
            f"[{m['role']}] {m['content']}"
            for m in history[-12:]
            if m["role"] in ("user", "bot")
        )
        prompt = (
            "你是「缘梦婚纱」AI客服助手。请根据以下对话历史生成简洁的人工接管摘要（中文，100字以内）。\n"
            "输出格式：\n"
            "问题类型：xxx\n客户情绪：xxx\n关键信息：xxx\n建议行动：xxx\n\n"
            f"对话历史：\n{recent}"
        )
        try:
            from langchain_core.messages import HumanMessage
            from ..graph.nodes._utils import strip_thinking
            resp = await self._llm.ainvoke([HumanMessage(content=prompt)])
            return strip_thinking(resp.content)
        except Exception:
            logger.warning("Handoff summary generation failed", exc_info=True)
            return ""

    async def _classify_category(self, first_message: str) -> str:
        from langchain_core.messages import SystemMessage as _SM
        categories = ["订单查询", "产品咨询", "质量投诉", "退换货", "加急制作", "价格咨询", "配送问题", "其他"]
        prompt = (
            f"将以下客户消息分类为这些类别之一：{', '.join(categories)}\n"
            f"消息：{first_message[:200]}\n"
            "只输出类别名称，不要其他内容。"
        )
        try:
            resp = await self._llm.ainvoke([_SM(content=prompt)])
            cat = resp.content.strip()
            return cat if cat in categories else "其他"
        except Exception:
            return "其他"

    async def _generate_close_report(
        self, ticket: Ticket, history: list[dict]
    ) -> None:
        if not self._llm:
            return
        recent = "\n".join(
            f"[{m['role']}] {m['content']}"
            for m in history[-20:]
            if m["role"] in ("user", "bot", "agent")
        )
        prompt = (
            "请根据以下客服对话生成结构化结案报告（JSON格式，中文）：\n"
            "{\n"
            '  "category": "问题分类（质量投诉/订单操作/咨询/其他）",\n'
            '  "resolved": true/false,\n'
            '  "resolution_type": "解决方式（退款/取消/信息提供/人工处理/其他）",\n'
            '  "sentiment_start": "negative/neutral/positive",\n'
            '  "sentiment_end": "negative/neutral/positive",\n'
            '  "key_issues": ["问题1", "问题2"],\n'
            '  "ai_handling_quality": "good/fair/poor"\n'
            "}\n\n"
            f"对话历史：\n{recent}\n\n"
            "只输出 JSON，不要其他文字。"
        )
        try:
            import json as _json
            from langchain_core.messages import HumanMessage
            resp = await self._llm.ainvoke([HumanMessage(content=prompt)])
            raw = resp.content.strip().strip("```json").strip("```").strip()
            report = _json.loads(raw)

            ticket.resolution = _json.dumps(report, ensure_ascii=False)
            if not ticket.category:
                ticket.category = report.get("category")
            if not ticket.sentiment:
                ticket.sentiment = report.get("sentiment_end")
            if not ticket.tags:
                ticket.tags = [str(i) for i in report.get("key_issues", [])[:5]]
            ticket.report_resolution_type = report.get("resolution_type")
            ticket.report_sentiment_start = report.get("sentiment_start")
            ticket.report_key_issues = [str(i) for i in report.get("key_issues", [])[:10]]
            ticket.report_ai_quality = report.get("ai_handling_quality")

            await self._tickets.update(ticket)
            logger.info(
                "Close report written ticket=%s category=%s quality=%s",
                ticket.ticket_id, ticket.category, ticket.report_ai_quality,
            )
        except Exception:
            logger.warning(
                "Close report generation failed for ticket=%s", ticket.ticket_id, exc_info=True
            )
