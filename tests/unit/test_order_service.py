from __future__ import annotations

from datetime import datetime, timezone, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_customer_service.domain.entities import Order, OrderItem
from ai_customer_service.domain.exceptions import InvalidOrderActionError, OrderAccessDeniedError
from ai_customer_service.domain.value_objects import OrderStatus
from ai_customer_service.use_cases.order_service import OrderService


def _make_order(status: OrderStatus, user_id: str = "user1") -> Order:
    return Order(
        order_id="ORD-001",
        user_id=user_id,
        status=status,
        items=[OrderItem(product_id="p1", name="测试商品", quantity=1, unit_price=99.0)],
        total=99.0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def repo():
    r = MagicMock()
    r.get_by_id = AsyncMock()
    r.update_status = AsyncMock()
    return r


@pytest.fixture
def service(repo):
    return OrderService(repo)


@pytest.mark.asyncio
async def test_get_status_success(service, repo):
    repo.get_by_id.return_value = _make_order(OrderStatus.SHIPPED)
    from ai_customer_service.domain.entities import OrderActionRequest
    result = await service.execute(
        OrderActionRequest(action="get_status", order_id="ORD-001"), user_id="user1"
    )
    assert "运输中" in result.message
    assert result.success is True


@pytest.mark.asyncio
async def test_cancel_pending_order(service, repo):
    order = _make_order(OrderStatus.PENDING)
    cancelled = _make_order(OrderStatus.CANCELLED)
    repo.get_by_id.return_value = order
    repo.update_status.return_value = cancelled
    from ai_customer_service.domain.entities import OrderActionRequest
    result = await service.execute(
        OrderActionRequest(action="cancel_order", order_id="ORD-001"), user_id="user1"
    )
    assert "取消" in result.message
    repo.update_status.assert_awaited_once_with("ORD-001", OrderStatus.CANCELLED)


@pytest.mark.asyncio
async def test_cancel_delivered_order_raises(service, repo):
    repo.get_by_id.return_value = _make_order(OrderStatus.DELIVERED)
    from ai_customer_service.domain.entities import OrderActionRequest
    with pytest.raises(InvalidOrderActionError):
        await service.execute(
            OrderActionRequest(action="cancel_order", order_id="ORD-001"), user_id="user1"
        )


@pytest.mark.asyncio
async def test_access_denied_for_wrong_user(service, repo):
    repo.get_by_id.return_value = _make_order(OrderStatus.PENDING, user_id="other-user")
    from ai_customer_service.domain.entities import OrderActionRequest
    with pytest.raises(OrderAccessDeniedError):
        await service.execute(
            OrderActionRequest(action="get_status", order_id="ORD-001"), user_id="user1"
        )
