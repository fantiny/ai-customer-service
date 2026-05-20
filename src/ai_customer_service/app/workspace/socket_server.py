"""Socket.io server — real-time bridge between customers, AI, and human agents.

Event flow:
  Customer side
  ─────────────
  join           {session_id?, user_id}       → create/resume session
  user_message   {session_id, content}        → AI processes; emits bot_reply / hitl_pending
  disconnect                                  → mark session inactive

  Agent workspace
  ───────────────
  agent_reply    {session_id, content, agent_id?}  → deliver message to customer socket
  hitl_approve   {session_id, notes?}              → resume LangGraph with approved=True
  hitl_reject    {session_id, notes?}              → resume LangGraph with approved=False
  transfer_to_bot {session_id, agent_id?}          → switch session back to AI mode

  Server → everyone in 'workspace' room
  ──────────────────────────────────────
  queue_updated  [SessionRecord.to_socket_dict(), ...]  → sidebar refresh
  new_message    {session_id, msg: dict}               → append to active session view

Message dict format: {"role": str, "content": str, "timestamp": str (ISO-8601)}
"""
from __future__ import annotations

import asyncio
import collections
import logging
import time as _time
from datetime import datetime, timezone
from typing import Any

import socketio

from .session_manager import WorkspaceSessionManager
from ...use_cases.interfaces import IAgentRepository, ISessionRepository, IStatusEventRepository, ITicketRepository, IWorkspaceService
from ...use_cases.workspace_service import WorkspaceService
from ...infrastructure.auth import AuthUser, AuthError, resolve_identity
from ...infrastructure.config import get_settings

logger = logging.getLogger(__name__)

# ── Shared singletons ─────────────────────────────────────────────────────────

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)

_manager = WorkspaceSessionManager()

# Initialised during app startup via init(); None is safe for import-time.
_workspace_service: IWorkspaceService | None = None
_chat_service: Any = None

# Agent socket tracking: {socket_id → (agent_id, agent_name)}
_agent_sockets: dict[str, tuple[str, str]] = {}

# Verified identities keyed by socket_id — populated in connect(), consumed in join()
_socket_auth: dict[str, AuthUser] = {}

# Per-session rate limiting — {session_id → deque of recent message timestamps}
_rate_windows: dict[str, collections.deque] = {}
_RATE_LIMIT = 5          # max messages
_RATE_WINDOW_SECS = 10   # per sliding window (seconds)


def init(
    chat_service: Any,
    session_repo: ISessionRepository,
    ticket_repo: ITicketRepository,
    event_repo: IStatusEventRepository,
    agent_repo: IAgentRepository | None = None,
    llm: Any = None,
    message_repo: Any = None,
) -> None:
    """Inject dependencies after the DI container has been initialised."""
    global _chat_service, _workspace_service
    _chat_service = chat_service
    _workspace_service = WorkspaceService(
        _manager, session_repo, ticket_repo, event_repo, agent_repo, llm,
        message_repo=message_repo,
    )


def get_workspace_service() -> IWorkspaceService:
    if _workspace_service is None:
        raise RuntimeError("socket_server.init() has not been called yet")
    return _workspace_service


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _broadcast_queue() -> None:
    """Broadcast pending sessions (human/hitl) + all sessions for monitoring."""
    await sio.emit("queue_updated", _manager.agent_queue(), room="workspace")
    await sio.emit("all_sessions_updated", _manager.all_sessions(), room="workspace")


async def broadcast_queue_update() -> None:
    """Public wrapper — call from REST endpoints that mutate session/ticket state."""
    if _workspace_service is None:
        logger.warning("broadcast_queue_update called before socket_server.init()")
        return
    await _broadcast_queue()


def _make_msg(role: str, content: str) -> dict[str, Any]:
    """Create a history-compatible message dict."""
    return {"role": role, "content": content, "timestamp": datetime.now(timezone.utc).isoformat()}


async def _auto_categorize_ticket(session_id: str, first_user_msg: str) -> None:
    try:
        ws = get_workspace_service()
        await ws.auto_categorize_if_needed(session_id, first_user_msg)
    except Exception:
        logger.debug("Auto-categorize failed for %s", session_id, exc_info=True)


async def _emit_to_customer(session_id: str, event: str, data: Any) -> None:
    sess = _manager.get(session_id)
    if sess and sess.socket_id:
        await sio.emit(event, data, to=sess.socket_id)


def _hitl_hold_message(pending: dict) -> str:
    label = pending.get("action_label", "操作")
    order_id = pending.get("order_id", "")
    return (
        f"您申请的「{label}」（订单 {order_id}）正在审核中，"
        "我们将在 2 分钟内完成处理。感谢您的耐心等待 💕"
    )


# ── Connection lifecycle ──────────────────────────────────────────────────────

@sio.event
async def connect(sid: str, environ: dict, auth: dict | None = None) -> None:
    token: str | None = (auth or {}).get("token") or None
    if not token:
        qs = environ.get("QUERY_STRING", "")
        for part in qs.split("&"):
            if part.startswith("token="):
                token = part[6:] or None
                break

    settings = get_settings()
    try:
        identity = resolve_identity(token, guest_id=f"guest-{sid[:7]}", settings=settings)
    except AuthError as exc:
        logger.warning("Socket auth rejected sid=%s: %s", sid, exc)
        return False

    _socket_auth[sid] = identity
    logger.info(
        "Socket connected: sid=%s user=%s guest=%s",
        sid, identity.user_id, identity.is_guest,
    )


@sio.event
async def disconnect(sid: str) -> None:
    _socket_auth.pop(sid, None)
    sess = _manager.get_by_socket(sid)
    if sess:
        logger.info("Customer disconnected: session=%s", sess.session_id)
        _rate_windows.pop(sess.session_id, None)

    if sid in _agent_sockets:
        agent_id, agent_name = _agent_sockets.pop(sid)
        logger.info("Agent disconnected: %s (%s)", agent_name, agent_id)
        try:
            ws = get_workspace_service()
            await ws.leave_agent(agent_id)
            await sio.emit(
                "agent_left",
                {"agent_id": agent_id, "name": agent_name},
                room="workspace",
            )
        except Exception:
            logger.warning("leave_agent error for %s", agent_id, exc_info=True)


# ── Customer events ───────────────────────────────────────────────────────────

@sio.event
async def join(sid: str, data: dict) -> dict:
    """Customer establishes a chat session.

    data: {session_id?: str}
    Returns: {session_id, thread_id, history, mode, user_id, display_name}
    """
    identity: AuthUser = _socket_auth.get(sid) or AuthUser(user_id="guest-unknown", is_guest=True)
    session_id: str | None = data.get("session_id")

    ws = get_workspace_service()
    record = await ws.join_customer(identity.user_id, sid, session_id)

    logger.info(
        "Session joined: %s user=%s guest=%s",
        record.session_id, identity.user_id, identity.is_guest,
    )
    return {
        "session_id":   record.session_id,
        "thread_id":    record.thread_id,
        "mode":         record.mode,
        "history":      record.history,      # list[dict] — already JSON-serialisable
        "user_id":      identity.user_id,
        "display_name": identity.name or identity.user_id,
        "is_guest":     identity.is_guest,
    }


@sio.event
async def user_message(sid: str, data: dict) -> None:
    """Customer sends a message.

    data: {session_id: str, content: str}
    """
    session_id: str = data["session_id"]
    content: str = data["content"]
    sess = _manager.get(session_id)
    if not sess:
        await sio.emit("error", {"message": "Session not found"}, to=sid)
        return

    # Rate limiting
    now_ts = _time.monotonic()
    window = _rate_windows.setdefault(session_id, collections.deque())
    window.append(now_ts)
    while window and window[0] < now_ts - _RATE_WINDOW_SECS:
        window.popleft()
    if len(window) > _RATE_LIMIT:
        throttle_msg = _make_msg("bot", "您发送消息太频繁，请稍后再试 🙏")
        await sio.emit("bot_reply", throttle_msg, to=sid)
        return

    ws = get_workspace_service()

    # Persist user message (write-through)
    user_result = await ws.handle_user_message(session_id, content)
    if user_result.error:
        logger.warning("handle_user_message error session=%s: %s", session_id, user_result.error)
    user_msg = sess.history[-1] if sess.history else _make_msg("user", content)

    if sess.mode == "human":
        await sio.emit(
            "new_message",
            {"session_id": session_id, "msg": user_msg},
            room="workspace",
        )
        return

    if sess.mode == "hitl_pending":
        hold_msg = _make_msg("bot", "您好，您的申请正在处理中，请稍候片刻 💕")
        sess.add_message("bot", hold_msg["content"])
        await ws.record_bot_message(session_id, hold_msg["content"])
        await sio.emit("bot_reply", hold_msg, to=sid)
        return

    # ── AI mode: run LangGraph ────────────────────────────────────────────────
    if _chat_service is None:
        await sio.emit("bot_reply", _make_msg("bot", "服务暂时不可用，请稍后重试。"), to=sid)
        return

    await sio.emit("bot_typing", {"typing": True}, to=sid)

    # Progress callback — emits bot_progress to the customer socket only
    async def _send_progress(stage: str, text: str) -> None:
        await sio.emit("bot_progress", {"stage": stage, "text": text}, to=sid)

    try:
        result = await _chat_service.send_message(
            sess.thread_id, sess.user_id, content,
            extra_config={"progress_callback": _send_progress},
        )
    except Exception as exc:
        logger.exception("Graph error for session %s", session_id)
        exc_str = str(exc)
        exc_lower = exc_str.lower()
        if "rate_limit" in exc_lower or "429" in exc_lower or "usage limit" in exc_lower or "quota" in exc_lower:
            internal_reason = f"AI 服务限流（429）— 自动转人工｜{exc_str[:120]}"
        else:
            internal_reason = f"AI 服务异常 — 自动转人工｜{exc_str[:120]}"
        await ws.transfer_to_human(session_id, reason=internal_reason)
        await _broadcast_queue()
        return

    if result.status == "interrupted":
        sess.mode = "hitl_pending"
        sess.pending_action = result.pending_action or {}
        sess.hitl_pending_since = datetime.now(timezone.utc)

        hold_content = _hitl_hold_message(result.pending_action or {})
        sess.add_message("bot", hold_content)
        await ws.record_hitl_state(session_id, result.pending_action)
        hold_msg = _make_msg("bot", hold_content)
        await sio.emit("bot_reply", hold_msg, to=sid)

        await sio.emit(
            "hitl_pending",
            {
                "session_id": session_id,
                "pending_action": result.pending_action,
                "session": sess.to_socket_dict(),
            },
            room="workspace",
        )
        await _broadcast_queue()

    else:
        reply_content = result.reply or "收到您的消息，正在处理中。"
        bot_msg = _make_msg("bot", reply_content)
        sess.add_message("bot", reply_content)
        await ws.record_bot_message(session_id, reply_content, node_name=result.intent)

        # Track intent for session card display; broadcast so workspace cards refresh
        if result.intent:
            sess.last_intent = result.intent
            await sio.emit("all_sessions_updated", _manager.all_sessions(), room="workspace")

        # Customer gets reply only (no source citations)
        await sio.emit("bot_reply", bot_msg, to=sid)

        # Background auto-categorization after first exchange
        if result.reply and len(sess.history) <= 3:
            asyncio.create_task(_auto_categorize_ticket(session_id, content))

        # Workspace agents get reply + source citations for manual verification
        workspace_msg = {**bot_msg, "sources": result.reply_sources}
        await sio.emit(
            "new_message",
            {"session_id": session_id, "msg": workspace_msg},
            room="workspace",
        )

        if result.order_context:
            await ws.update_order_context(session_id, result.order_context)
            await sio.emit(
                "order_context_updated",
                {"session_id": session_id, "order_context": result.order_context},
                room="workspace",
            )

        if result.request_human:
            await ws.transfer_to_human(session_id, reason="客户主动请求转接人工")
            await _broadcast_queue()


# ── Agent workspace events ────────────────────────────────────────────────────

@sio.event
async def join_workspace(sid: str, data: dict) -> dict:
    """Agent joins the workspace room.

    data: {agent_id: str, name: str}
    Returns: {queue, agent_id, all_sessions}
    """
    agent_id: str = data.get("agent_id") or f"agent-{sid[:6]}"
    name: str = data.get("name") or agent_id

    await sio.enter_room(sid, "workspace")
    _agent_sockets[sid] = (agent_id, name)

    ws = get_workspace_service()
    await ws.join_agent(agent_id, name)

    await sio.emit(
        "agent_joined",
        {"agent_id": agent_id, "name": name},
        room="workspace",
        skip_sid=sid,
    )

    logger.info("Agent joined workspace: %s (%s)", name, agent_id)
    return {
        "agent_id": agent_id,
        "queue": _manager.agent_queue(),
        "all_sessions": _manager.all_sessions(),
    }


@sio.event
async def claim_session(sid: str, data: dict) -> dict:
    """Agent claims (认领) a session.

    data: {session_id: str, agent_id: str}
    """
    session_id: str = data.get("session_id", "")
    agent_id: str = data.get("agent_id", "")
    if not session_id or not agent_id:
        return {"success": False, "message": "session_id and agent_id required"}

    try:
        ws = get_workspace_service()
        ticket = await ws.claim_session(session_id, agent_id)
        await sio.emit(
            "session_claimed",
            {"session_id": session_id, "ticket_id": ticket.ticket_id, "agent_id": agent_id},
            room="workspace",
        )
        await _broadcast_queue()
        return {"success": True, "ticket_id": ticket.ticket_id, "message": "会话已认领"}
    except ValueError as exc:
        return {"success": False, "message": str(exc)}
    except Exception:
        logger.exception("claim_session error session=%s", session_id)
        return {"success": False, "message": "认领失败，请重试"}


@sio.event
async def get_session(sid: str, data: dict) -> dict | None:
    session_id: str = data.get("session_id", "")
    sess = _manager.get(session_id)
    return sess.to_socket_dict() if sess else None


@sio.event
async def agent_reply(sid: str, data: dict) -> None:
    """Human agent sends a manual reply to a customer.

    data: {session_id: str, content: str, agent_id?: str}
    """
    session_id: str = data["session_id"]
    content: str = data["content"]
    agent_id: str = data.get("agent_id", "unknown_agent")
    sess = _manager.get(session_id)
    if not sess:
        return

    if sess.mode != "human":
        logger.warning(
            "agent_reply ignored: session %s not in human mode (mode=%s)", session_id, sess.mode
        )
        return
    # Guard: only the claiming agent may reply
    if sess.assigned_agent_id and sess.assigned_agent_id != agent_id:
        logger.warning(
            "agent_reply blocked: session %s claimed by %s, rejected from %s",
            session_id, sess.assigned_agent_id, agent_id,
        )
        await sio.emit("error", {"code": "NOT_OWNER", "message": "该会话已由其他客服认领"}, to=sid)
        return

    ws = get_workspace_service()
    await ws.handle_agent_reply(session_id, agent_id, content)
    msg = sess.history[-1]  # dict just appended by handle_agent_reply

    await _emit_to_customer(session_id, "bot_reply", msg)
    await sio.emit("new_message", {"session_id": session_id, "msg": msg}, room="workspace")


@sio.event
async def hitl_approve(sid: str, data: dict) -> None:
    """Agent approves a high-risk order action."""
    session_id: str = data["session_id"]
    sess = _manager.get(session_id)
    if not sess or sess.mode != "hitl_pending":
        return
    if _chat_service is None:
        return

    try:
        result = await _chat_service.resume_hitl(
            sess.thread_id, sess.user_id,
            {"approved": True, "notes": data.get("notes", "")},
        )
    except Exception:
        logger.exception("HITL resume error session=%s", session_id)
        return

    ws = get_workspace_service()
    await ws.record_hitl_decision(session_id, approved=True, agent_id=sid)
    await ws.transfer_to_ai(session_id, agent_id=sid)

    reply = result.reply or "操作已完成。"
    bot_msg = _make_msg("bot", reply)
    sess.add_message("bot", reply)
    await ws.record_bot_message(session_id, reply)

    await _emit_to_customer(session_id, "bot_reply", bot_msg)
    await sio.emit("new_message", {"session_id": session_id, "msg": bot_msg}, room="workspace")
    await _broadcast_queue()


@sio.event
async def hitl_reject(sid: str, data: dict) -> None:
    """Agent rejects a high-risk order action."""
    session_id: str = data["session_id"]
    sess = _manager.get(session_id)
    if not sess or sess.mode != "hitl_pending":
        return
    if _chat_service is None:
        return

    try:
        result = await _chat_service.resume_hitl(
            sess.thread_id, sess.user_id,
            {"approved": False, "notes": data.get("notes", "")},
        )
    except Exception:
        logger.exception("HITL reject error session=%s", session_id)
        return

    ws = get_workspace_service()
    await ws.record_hitl_decision(session_id, approved=False, agent_id=sid)
    await ws.transfer_to_ai(session_id, agent_id=sid)

    reply = result.reply or "操作已取消。"
    bot_msg = _make_msg("bot", reply)
    sess.add_message("bot", reply)
    await ws.record_bot_message(session_id, reply)

    await _emit_to_customer(session_id, "bot_reply", bot_msg)
    await sio.emit("new_message", {"session_id": session_id, "msg": bot_msg}, room="workspace")
    await _broadcast_queue()


@sio.event
async def transfer_to_agent(sid: str, data: dict) -> None:
    session_id: str = data["session_id"]
    if not _manager.get(session_id):
        return
    ws = get_workspace_service()
    await ws.transfer_to_human(session_id, reason=None)
    await _broadcast_queue()


@sio.event
async def transfer_to_bot(sid: str, data: dict) -> None:
    session_id: str = data["session_id"]
    agent_id: str = data.get("agent_id", "unknown_agent")
    sess = _manager.get(session_id)
    if not sess:
        return

    ws = get_workspace_service()
    await ws.transfer_to_ai(session_id, agent_id)

    internal_msg = _make_msg("system", "[ 内部 ] AI 顾问已接管此会话")
    sess.add_message("system", internal_msg["content"])
    await ws.record_bot_message(session_id, internal_msg["content"], role="system")
    await sio.emit(
        "new_message", {"session_id": session_id, "msg": internal_msg}, room="workspace"
    )
    await _broadcast_queue()


@sio.event
async def agent_typing(sid: str, data: dict) -> None:
    session_id: str = data.get("session_id", "")
    typing: bool = bool(data.get("typing", True))
    await _emit_to_customer(session_id, "agent_typing", {"typing": typing})


@sio.event
async def customer_typing(sid: str, data: dict) -> None:
    session_id: str = data.get("session_id", "")
    typing: bool = bool(data.get("typing", True))
    await sio.emit(
        "customer_typing",
        {"session_id": session_id, "typing": typing},
        room="workspace",
    )


@sio.event
async def submit_rating(sid: str, data: dict) -> dict:
    session_id: str = data.get("session_id", "")
    try:
        rating = int(data.get("rating", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "无效评分"}

    if not session_id or not 1 <= rating <= 5:
        return {"success": False, "message": "session_id 和 1–5 的评分均为必填"}

    try:
        ws = get_workspace_service()
        await ws.submit_rating(session_id, rating)
        await sio.emit(
            "rating_received",
            {"session_id": session_id, "rating": rating},
            room="workspace",
        )
        return {"success": True, "message": "感谢您的评价！"}
    except Exception:
        logger.exception("submit_rating error session=%s", session_id)
        return {"success": False, "message": "评分提交失败，请重试"}


@sio.event
async def resolve_session(sid: str, data: dict) -> dict:
    session_id: str = data.get("session_id", "")
    agent_id: str = data.get("agent_id", "unknown_agent")
    resolution: str | None = data.get("resolution")

    if not session_id:
        return {"success": False, "message": "session_id required"}

    try:
        ws = get_workspace_service()
        ticket = await ws.resolve_ticket(session_id, agent_id, resolution)

        sess = _manager.get(session_id)
        if sess:
            internal_msg = _make_msg("system", "[ 内部 ] 此工单已由顾问结单")
            sess.add_message("system", internal_msg["content"])
            await ws.record_bot_message(session_id, internal_msg["content"], role="system")
            await sio.emit(
                "new_message",
                {"session_id": session_id, "msg": internal_msg},
                room="workspace",
            )

        await sio.emit(
            "ticket_resolved",
            {"session_id": session_id, "ticket_id": ticket.ticket_id},
            room="workspace",
        )
        await _broadcast_queue()
        await _emit_to_customer(
            session_id,
            "request_rating",
            {"session_id": session_id, "message": "您好，本次服务已结束，请问您对本次服务满意吗？"},
        )
        return {"success": True, "ticket_id": ticket.ticket_id, "message": "工单已结单"}
    except Exception:
        logger.exception("resolve_session error session=%s", session_id)
        return {"success": False, "message": "结单失败，请重试"}


# ── REST-compatible query helpers ─────────────────────────────────────────────

def get_agent_queue() -> list[dict]:
    return _manager.agent_queue()


def get_all_sessions() -> list[dict]:
    return _manager.all_sessions()


# ── HITL auto-timeout background task ────────────────────────────────────────

async def hitl_timeout_watcher(timeout_minutes: float = 10.0) -> None:
    """Periodically auto-reject HITL sessions that have been pending too long."""
    while True:
        await asyncio.sleep(30)

        # Rate-window GC: evict stale entries for sessions no longer in memory
        stale = [sid for sid in list(_rate_windows) if not _manager.get(sid)]
        for sid in stale:
            _rate_windows.pop(sid, None)
        if stale:
            logger.debug("rate_windows GC: evicted %d stale entries", len(stale))

        if _chat_service is None:
            continue
        ws = get_workspace_service()
        now = datetime.now(timezone.utc)
        for sess in list(_manager._sessions.values()):
            if sess.mode != "hitl_pending":
                continue
            since = sess.hitl_pending_since
            if since is None:
                continue
            age_min = (now - since).total_seconds() / 60
            if age_min < timeout_minutes:
                continue

            logger.info("HITL auto-timeout: session=%s age_min=%.1f", sess.session_id, age_min)
            try:
                result = await _chat_service.resume_hitl(
                    sess.thread_id, sess.user_id,
                    {"approved": False, "notes": "system:timeout"},
                )
                await ws.record_hitl_decision(sess.session_id, approved=False, agent_id="system:timeout")
                await ws.transfer_to_ai(sess.session_id, agent_id="system")
                reply = (
                    result.reply
                    or "非常抱歉，您的操作申请因超时已自动取消。如需帮助，请重新发起操作。"
                )
                bot_msg = _make_msg("bot", reply)
                sess.add_message("bot", reply)
                await ws.record_bot_message(sess.session_id, reply)
                await _emit_to_customer(sess.session_id, "bot_reply", bot_msg)
                await sio.emit(
                    "new_message",
                    {"session_id": sess.session_id, "msg": bot_msg},
                    room="workspace",
                )
                await _broadcast_queue()
            except Exception:
                logger.exception("HITL auto-timeout error session=%s", sess.session_id)
