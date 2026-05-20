from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..infrastructure.config import get_settings
from ..infrastructure.container import Container
from .routers import auth as auth_router, chat, health, workspace as workspace_router
from .routers import admin_chat as admin_chat_router
from .routers import upload as upload_router
from .workspace.socket_server import (
    sio,
    init as init_socket,
    get_workspace_service,
    get_agent_queue,
    get_all_sessions,
    hitl_timeout_watcher,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    container = Container(settings)
    logger.info("Initializing application container...")
    await container.initialize()
    app.state.container = container

    # Wire ChatService + repositories into the Socket.io handler
    init_socket(
        container.chat_service,
        container.session_repo,
        container.ticket_repo,
        container.event_repo,
        container.agent_repo,
        container.llm,
        message_repo=container.message_repo,
    )

    # Validate that all required graph node dependencies are present.
    # This surfaces misconfigured DI containers at startup rather than on the
    # first customer message (which would be a much harder bug to diagnose).
    from ..graph.node_config import validate_node_config
    _probe_config = container._make_graph_config("__probe__", "__probe__", None)
    validate_node_config(_probe_config["configurable"])
    logger.info("NodeConfig validation passed.")

    # Warm startup: restore active workspace sessions from DB into memory
    ws_service = get_workspace_service()
    restored = await ws_service.load_active_sessions()
    logger.info("Container ready. Restored %d active sessions. Application started.", restored)

    # Phase 5: SLA background watcher
    sla_task = asyncio.create_task(
        _sla_watcher(container, sio),
        name="sla_watcher",
    )
    # HITL auto-timeout watcher (10 min default, configurable via rules_repo)
    from ..use_cases.rules_keys import RulesKey
    hitl_timeout_min = float(await container.rules_repo.get(RulesKey.HITL_AUTO_TIMEOUT_MINUTES, 10))
    hitl_task = asyncio.create_task(
        hitl_timeout_watcher(timeout_minutes=hitl_timeout_min),
        name="hitl_timeout_watcher",
    )
    digest_task = asyncio.create_task(
        _daily_digest_scheduler(container, settings),
        name="daily_digest_scheduler",
    )

    yield

    for task in (sla_task, hitl_task, digest_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("Shutting down...")
    await container.close()


async def _sla_watcher(container: Any, sio_server: Any) -> None:
    """Check SLA thresholds every 60 s and emit warnings to the workspace room."""
    while True:
        await asyncio.sleep(60)
        try:
            rules = container.rules_repo
            from ..use_cases.rules_keys import RulesKey
            hitl_min     = float(await rules.get(RulesKey.SLA_HITL_MINUTES, 2))
            human_min    = float(await rules.get(RulesKey.SLA_HUMAN_RESPONSE_MINUTES, 5))
            resolve_hrs  = float(await rules.get(RulesKey.SLA_RESOLVE_HOURS, 24))

            now = datetime.now(timezone.utc)

            # ── Session-level SLA (HITL wait + human response time) ──────────
            sessions = await container.session_repo.get_active()
            for sess in sessions:
                age_min = (now - sess.updated_at.replace(tzinfo=None)).total_seconds() / 60
                warning = None
                if sess.mode == "hitl_pending" and age_min > hitl_min:
                    warning = {
                        "session_id": sess.session_id,
                        "type": "hitl_timeout",
                        "message": f"HITL 等待已超 {hitl_min:.0f} 分钟，请尽快处理",
                    }
                elif sess.mode == "human" and age_min > human_min:
                    warning = {
                        "session_id": sess.session_id,
                        "type": "response_timeout",
                        "message": f"人工接管已超 {human_min:.0f} 分钟无回复",
                    }
                if warning:
                    await sio_server.emit("sla_warning", warning, room="workspace")

            # ── Ticket-level SLA (resolve deadline) ──────────────────────────
            open_tickets = await container.ticket_repo.list_open()
            for ticket in open_tickets:
                if not ticket.created_at:
                    continue
                age_hrs = (now - ticket.created_at.replace(tzinfo=None)).total_seconds() / 3600
                if age_hrs > resolve_hrs:
                    await sio_server.emit(
                        "sla_warning",
                        {
                            "session_id": ticket.session_id,
                            "ticket_id": ticket.ticket_id,
                            "type": "resolve_deadline",
                            "message": f"工单已超 {resolve_hrs:.0f} 小时未结单，请跟进",
                        },
                        room="workspace",
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("SLA watcher error", exc_info=True)


async def _daily_digest_scheduler(container: Any, settings: Any) -> None:
    """Fire once per day at DIGEST_HOUR (default 08:00 local time) to generate the digest."""
    import json
    import urllib.request
    from datetime import date

    svc = container.digest_service

    while True:
        now = datetime.now()
        target_hour = getattr(settings, "DIGEST_HOUR", 8)
        next_run = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        wait_seconds = (next_run - now).total_seconds()
        logger.info("Daily digest scheduler: next run at %s (%.0f s away)", next_run, wait_seconds)
        await asyncio.sleep(wait_seconds)

        try:
            yesterday = date.today() - timedelta(days=1)
            metrics = await svc.generate(yesterday)
            logger.info("Daily digest generated for %s", yesterday)

            # Optional webhook delivery
            webhook_url = getattr(settings, "DIGEST_WEBHOOK_URL", None)
            if webhook_url:
                payload = json.dumps({"event": "daily_digest", "metrics": metrics}).encode()
                req = urllib.request.Request(
                    webhook_url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        logger.info("Digest webhook delivered: status=%d", resp.status)
                except Exception as exc:
                    logger.warning("Digest webhook failed: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily digest generation failed")


def create_app() -> socketio.ASGIApp:
    """Build the full ASGI application: FastAPI REST + Socket.io WebSocket.

    This is the factory used by uvicorn (``uvicorn main:create_app --factory``).
    Returning the socketio.ASGIApp wrapper ensures WebSocket upgrade requests
    are handled by python-socketio rather than rejected by FastAPI.
    """
    fastapi_app = FastAPI(
        title="缘梦婚纱 AI 客服",
        description="LangGraph-based wedding dress customer service with Intelligent Workbench",
        version="0.2.0",
        lifespan=lifespan,
    )

    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    fastapi_app.include_router(health.router)
    fastapi_app.include_router(auth_router.router)
    fastapi_app.include_router(chat.router)
    fastapi_app.include_router(workspace_router.router)
    fastapi_app.include_router(admin_chat_router.router)
    fastapi_app.include_router(upload_router.router)

    # ── Serve uploaded files ──────────────────────────────────────────────────
    from .routers.upload import UPLOAD_DIR
    fastapi_app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

    # ── Workspace in-memory helpers (backed by socket_server manager) ────────
    @fastapi_app.get("/api/workspace/queue", tags=["workspace"])
    async def workspace_queue():
        return JSONResponse(content=get_agent_queue())

    @fastapi_app.get("/api/workspace/sessions", tags=["workspace"])
    async def workspace_sessions():
        return JSONResponse(content=get_all_sessions())

    # Wrap FastAPI inside Socket.io so WebSocket upgrade requests are handled first
    return socketio.ASGIApp(sio, other_asgi_app=fastapi_app)


# Module-level app for direct ``uvicorn main:app`` usage
app = create_app()
