"""Unit tests for wedding dress OrderService business logic.

All tests use InMemoryOrderRepository (no I/O) and exercise every business rule:
- Stage-based cancellation refund rates
- Rush order surcharge calculation
- Production progress display
- Tracking / refund initiation guards
- Access control
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from ai_customer_service.domain.entities import (
    Order,
    OrderActionRequest,
    OrderItem,
    WeddingMeta,
)
from ai_customer_service.domain.exceptions import (
    InvalidOrderActionError,
    OrderAccessDeniedError,
    OrderNotFoundError,
)
from ai_customer_service.domain.value_objects import (
    OrderStatus,
    ProductionStage,
    RushLevel,
)
from ai_customer_service.use_cases.order_service import OrderService


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_order(
    *,
    order_id: str = "WD-TEST-001",
    user_id: str = "user1",
    status: OrderStatus = OrderStatus.CONFIRMED,
    total: float = 10000.0,
    is_custom: bool = True,
    stage: ProductionStage = ProductionStage.PENDING,
    is_rush: bool = False,
    rush_level: RushLevel = RushLevel.NONE,
    wedding_date: Optional[str] = None,
    tracking_number: str = "",
) -> Order:
    return Order(
        order_id=order_id,
        user_id=user_id,
        status=status,
        items=[OrderItem(product_id="P001", name="法式蕾丝鱼尾婚纱", quantity=1, unit_price=total)],
        total=total,
        shipping_address="北京市",
        tracking_number=tracking_number,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        wedding_meta=WeddingMeta(
            dress_style="mermaid",
            color="ivory_white",
            is_custom=is_custom,
            production_stage=stage,
            is_rush=is_rush,
            rush_level=rush_level,
            wedding_date=wedding_date,
        ),
    )


class InMemoryOrderRepository:
    """Minimal in-memory repo for unit tests."""

    def __init__(self, orders: list[Order]) -> None:
        self._store: dict[str, Order] = {o.order_id: o for o in orders}

    async def get_by_id(self, order_id: str) -> Order:
        if order_id not in self._store:
            raise OrderNotFoundError(order_id)
        return self._store[order_id]

    async def get_by_user(self, user_id: str, limit: int = 10) -> list[Order]:
        return [o for o in self._store.values() if o.user_id == user_id][:limit]

    async def update_status(self, order_id: str, status: OrderStatus) -> Order:
        order = await self.get_by_id(order_id)
        updated = order.model_copy(update={"status": status})
        self._store[order_id] = updated
        return updated


def _service(*orders: Order) -> OrderService:
    return OrderService(InMemoryOrderRepository(list(orders)))


def _req(action: str, order_id: str = "WD-TEST-001", extra: dict | None = None) -> OrderActionRequest:
    return OrderActionRequest(action=action, order_id=order_id, extra=extra or {})


# ── get_status ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_status_custom_order():
    order = _make_order(status=OrderStatus.CONFIRMED, is_custom=True, stage=ProductionStage.SEWING)
    svc = _service(order)
    result = await svc.execute(_req("get_status"), user_id="user1")
    assert result.success
    assert "WD-TEST-001" in result.message
    assert "已确认" in result.message


@pytest.mark.asyncio
async def test_get_status_non_custom_order():
    order = _make_order(status=OrderStatus.SHIPPED, is_custom=False, stage=ProductionStage.READY)
    svc = _service(order)
    result = await svc.execute(_req("get_status"), user_id="user1")
    assert result.success
    assert "运输中" in result.message


# ── get_production_progress ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_production_progress_custom_sewing():
    order = _make_order(is_custom=True, stage=ProductionStage.SEWING)
    svc = _service(order)
    result = await svc.execute(_req("get_production_progress"), user_id="user1")
    assert result.success
    assert "缝制" in result.message
    assert "sewing" in result.message  # shown in progress bar


@pytest.mark.asyncio
async def test_production_progress_non_custom_returns_status():
    order = _make_order(is_custom=False, status=OrderStatus.SHIPPED, stage=ProductionStage.READY)
    svc = _service(order)
    result = await svc.execute(_req("get_production_progress"), user_id="user1")
    assert result.success
    assert "现货" in result.message


@pytest.mark.asyncio
async def test_production_progress_shows_estimated_completion():
    completion = (datetime.now(timezone.utc) + timedelta(days=20)).strftime("%Y-%m-%d")
    order = _make_order(is_custom=True, stage=ProductionStage.CUTTING)
    order = order.model_copy(
        update={"wedding_meta": order.wedding_meta.model_copy(
            update={"estimated_completion": completion}
        )}
    )
    svc = _service(order)
    result = await svc.execute(_req("get_production_progress"), user_id="user1")
    assert completion in result.message


# ── cancel_order — custom, stage-based refund rates ─────────────────────────

@pytest.mark.asyncio
async def test_cancel_custom_pending_full_refund():
    order = _make_order(is_custom=True, stage=ProductionStage.PENDING, total=10000.0)
    svc = _service(order)
    result = await svc.execute(_req("cancel_order"), user_id="user1")
    assert result.success
    assert "100%" in result.message
    assert "10,000.00" in result.message


@pytest.mark.asyncio
async def test_cancel_custom_confirmed_full_refund():
    # CONFIRMED stage = pre-cutting → 100% refund (policy updated 2026-05)
    order = _make_order(is_custom=True, stage=ProductionStage.CONFIRMED, total=10000.0)
    svc = _service(order)
    result = await svc.execute(_req("cancel_order"), user_id="user1")
    assert result.success
    assert "100%" in result.message
    assert "10,000.00" in result.message


@pytest.mark.asyncio
async def test_cancel_custom_cutting_70_percent():
    # CUTTING stage → 70% refund (policy updated 2026-05)
    order = _make_order(is_custom=True, stage=ProductionStage.CUTTING, total=10000.0)
    svc = _service(order)
    result = await svc.execute(_req("cancel_order"), user_id="user1")
    assert result.success
    assert "70%" in result.message
    assert "7,000.00" in result.message


@pytest.mark.asyncio
async def test_cancel_custom_sewing_30_percent():
    # SEWING stage → 30% refund (policy updated 2026-05; was incorrectly 0%)
    order = _make_order(is_custom=True, stage=ProductionStage.SEWING, total=10000.0)
    svc = _service(order)
    result = await svc.execute(_req("cancel_order"), user_id="user1")
    assert result.success
    assert "30%" in result.message
    assert "3,000.00" in result.message


@pytest.mark.asyncio
async def test_cancel_custom_beading_raises_no_refund():
    order = _make_order(is_custom=True, stage=ProductionStage.BEADING)
    svc = _service(order)
    with pytest.raises(InvalidOrderActionError):
        await svc.execute(_req("cancel_order"), user_id="user1")


@pytest.mark.asyncio
async def test_cancel_non_custom_full_refund():
    order = _make_order(is_custom=False, status=OrderStatus.PENDING, total=5800.0)
    svc = _service(order)
    result = await svc.execute(_req("cancel_order"), user_id="user1")
    assert result.success
    assert "5,800.00" in result.message


@pytest.mark.asyncio
async def test_cancel_delivered_order_raises():
    order = _make_order(status=OrderStatus.DELIVERED)
    svc = _service(order)
    with pytest.raises(InvalidOrderActionError):
        await svc.execute(_req("cancel_order"), user_id="user1")


# ── initiate_refund ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_initiate_refund_delivered():
    order = _make_order(status=OrderStatus.DELIVERED, is_custom=False, total=8900.0)
    svc = _service(order)
    result = await svc.execute(_req("initiate_refund"), user_id="user1")
    assert result.success
    assert "8,900.00" in result.message
    assert result.order.status == OrderStatus.REFUND_PENDING


@pytest.mark.asyncio
async def test_initiate_refund_shipped_raises():
    order = _make_order(status=OrderStatus.SHIPPED, is_custom=False)
    svc = _service(order)
    with pytest.raises(InvalidOrderActionError):
        await svc.execute(_req("initiate_refund"), user_id="user1")


# ── get_tracking ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_tracking_shipped():
    order = _make_order(
        status=OrderStatus.SHIPPED,
        is_custom=False,
        tracking_number="SF1234567890",
    )
    svc = _service(order)
    result = await svc.execute(_req("get_tracking"), user_id="user1")
    assert result.success
    assert "SF1234567890" in result.message


@pytest.mark.asyncio
async def test_get_tracking_not_shipped():
    order = _make_order(status=OrderStatus.CONFIRMED, is_custom=True, stage=ProductionStage.SEWING)
    svc = _service(order)
    result = await svc.execute(_req("get_tracking"), user_id="user1")
    assert result.success
    assert "尚未发货" in result.message


# ── request_rush ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_request_rush_standard_calculates_surcharge():
    order = _make_order(is_custom=True, stage=ProductionStage.CUTTING, total=10000.0)
    svc = _service(order)
    result = await svc.execute(
        _req("request_rush", extra={"rush_level": RushLevel.STANDARD_RUSH}),
        user_id="user1",
    )
    assert result.success
    assert "5,000.00" in result.message  # 50% surcharge
    assert "30" in result.message        # 30-day delivery


@pytest.mark.asyncio
async def test_request_super_rush_calculates_surcharge():
    order = _make_order(is_custom=True, stage=ProductionStage.PENDING, total=10000.0)
    svc = _service(order)
    result = await svc.execute(
        _req("request_rush", extra={"rush_level": RushLevel.SUPER_RUSH}),
        user_id="user1",
    )
    assert result.success
    assert "10,000.00" in result.message  # 100% surcharge
    assert "15" in result.message         # 15-day delivery


@pytest.mark.asyncio
async def test_request_rush_with_wedding_date_shows_countdown():
    wedding = (datetime.now(timezone.utc) + timedelta(days=40)).strftime("%Y-%m-%d")
    order = _make_order(
        is_custom=True, stage=ProductionStage.CUTTING,
        wedding_date=wedding, total=10000.0,
    )
    svc = _service(order)
    result = await svc.execute(
        _req("request_rush", extra={"rush_level": RushLevel.STANDARD_RUSH}),
        user_id="user1",
    )
    assert result.success
    # Should mention remaining days
    assert "天" in result.message


@pytest.mark.asyncio
async def test_request_rush_beading_stage_raises():
    order = _make_order(is_custom=True, stage=ProductionStage.BEADING)
    svc = _service(order)
    with pytest.raises(InvalidOrderActionError):
        await svc.execute(
            _req("request_rush", extra={"rush_level": RushLevel.STANDARD_RUSH}),
            user_id="user1",
        )


@pytest.mark.asyncio
async def test_request_rush_delivered_raises():
    order = _make_order(status=OrderStatus.DELIVERED, is_custom=False)
    svc = _service(order)
    with pytest.raises(InvalidOrderActionError):
        await svc.execute(
            _req("request_rush", extra={"rush_level": RushLevel.STANDARD_RUSH}),
            user_id="user1",
        )


# ── Access control ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wrong_user_denied_get_status():
    order = _make_order(user_id="alice")
    svc = _service(order)
    with pytest.raises(OrderAccessDeniedError):
        await svc.execute(_req("get_status"), user_id="bob")


@pytest.mark.asyncio
async def test_wrong_user_denied_cancel():
    order = _make_order(user_id="alice", stage=ProductionStage.PENDING)
    svc = _service(order)
    with pytest.raises(OrderAccessDeniedError):
        await svc.execute(_req("cancel_order"), user_id="bob")


# ── OrderNotFoundError ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_order_not_found():
    svc = _service()  # empty repo
    with pytest.raises(OrderNotFoundError):
        await svc.execute(_req("get_status", order_id="WD-NONEXISTENT"), user_id="user1")


# ── Unknown action ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_action_raises():
    order = _make_order()
    svc = _service(order)
    with pytest.raises(InvalidOrderActionError):
        await svc.execute(_req("teleport_order"), user_id="user1")


# ── validate() pre-HITL guards — must match execute() exactly ────────────────
# These tests prevent the HITL "approve → execute fails" breakage (B2/B3 fix).

@pytest.mark.asyncio
async def test_validate_exchange_pending_raises_before_hitl():
    """B3: EXCHANGE_PENDING must be blocked at validate() time, not only in execute()."""
    order = _make_order(status=OrderStatus.EXCHANGE_PENDING)
    svc = _service(order)
    from ai_customer_service.domain.entities import OrderActionRequest
    req = OrderActionRequest(action="cancel_order", order_id="WD-TEST-001", extra={})
    with pytest.raises(InvalidOrderActionError):
        await svc.validate(req, user_id="user1")


@pytest.mark.asyncio
async def test_validate_beading_raises_before_hitl():
    """B2: BEADING stage (zero-refund) must be blocked at validate() time."""
    order = _make_order(is_custom=True, stage=ProductionStage.BEADING, status=OrderStatus.CONFIRMED)
    svc = _service(order)
    from ai_customer_service.domain.entities import OrderActionRequest
    req = OrderActionRequest(action="cancel_order", order_id="WD-TEST-001", extra={})
    with pytest.raises(InvalidOrderActionError):
        await svc.validate(req, user_id="user1")


@pytest.mark.asyncio
async def test_validate_qc_stage_raises_before_hitl():
    """B2: QC stage (zero-refund) must be blocked at validate() time."""
    order = _make_order(is_custom=True, stage=ProductionStage.QC, status=OrderStatus.CONFIRMED)
    svc = _service(order)
    from ai_customer_service.domain.entities import OrderActionRequest
    req = OrderActionRequest(action="cancel_order", order_id="WD-TEST-001", extra={})
    with pytest.raises(InvalidOrderActionError):
        await svc.validate(req, user_id="user1")


@pytest.mark.asyncio
async def test_validate_pending_stage_passes():
    """validate() must NOT block PENDING stage (full refund allowed)."""
    order = _make_order(is_custom=True, stage=ProductionStage.PENDING, status=OrderStatus.CONFIRMED)
    svc = _service(order)
    from ai_customer_service.domain.entities import OrderActionRequest
    req = OrderActionRequest(action="cancel_order", order_id="WD-TEST-001", extra={})
    # Should not raise
    await svc.validate(req, user_id="user1")


@pytest.mark.asyncio
async def test_validate_cutting_stage_passes():
    """validate() must NOT block CUTTING stage (70% refund allowed)."""
    order = _make_order(is_custom=True, stage=ProductionStage.CUTTING, status=OrderStatus.CONFIRMED)
    svc = _service(order)
    from ai_customer_service.domain.entities import OrderActionRequest
    req = OrderActionRequest(action="cancel_order", order_id="WD-TEST-001", extra={})
    await svc.validate(req, user_id="user1")
