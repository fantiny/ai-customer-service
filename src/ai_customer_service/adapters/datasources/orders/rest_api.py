"""External REST API implementation of IOrderRepository.

Maps a generic JSON order API to the internal Order domain entity.
The API contract expected from the remote system:

    GET  {base_url}/orders/{order_id}
         → OrderPayload (see _parse_order)

    GET  {base_url}/orders?user_id={user_id}&limit={limit}
         → list[OrderPayload] or {"data": [OrderPayload], ...}

    PATCH {base_url}/orders/{order_id}
         → { "status": "<new_status>", ... }
         ← OrderPayload

If the upstream API has a different schema, subclass and override _parse_order.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ....domain.entities import Order, OrderItem, WeddingMeta
from ....domain.exceptions import OrderNotFoundError
from ....domain.value_objects import OrderStatus, ProductionStage, RushLevel
from ....use_cases.interfaces import IOrderRepository
from ..auth.providers import IAuthProvider
from ..http_client import AuthedHTTPClient

logger = logging.getLogger(__name__)


class RESTAPIOrderRepository(IOrderRepository):
    """IOrderRepository backed by an external REST API.

    Delegates authentication entirely to the injected IAuthProvider,
    so the same repository works with any upstream OMS / ERP regardless
    of whether it uses API keys, Bearer tokens, OAuth2, or Basic auth.
    """

    def __init__(
        self,
        base_url: str,
        auth_provider: IAuthProvider,
        timeout: float = 30.0,
    ) -> None:
        self._client = AuthedHTTPClient(
            base_url=base_url,
            auth_provider=auth_provider,
            timeout=timeout,
        )
        logger.info(
            "RESTAPIOrderRepository initialised (base_url=%s, auth=%s)",
            base_url,
            auth_provider.describe(),
        )

    # ── IOrderRepository ──────────────────────────────────────────────────────

    async def get_by_id(self, order_id: str) -> Order:
        data = await self._client.get(f"/orders/{order_id}")
        if data is None:
            raise OrderNotFoundError(order_id)
        return self._parse_order(data)

    async def list_by_user(self, user_id: str, limit: int = 10) -> list[Order]:
        data = await self._client.get(
            "/orders", params={"user_id": user_id, "limit": limit}
        )
        if data is None:
            return []
        # Support both { "data": [...] } envelope and bare list
        rows = data.get("data", data) if isinstance(data, dict) else data
        return [self._parse_order(r) for r in rows]

    async def update_status(self, order_id: str, status: OrderStatus) -> Order:
        data = await self._client.patch(
            f"/orders/{order_id}", json={"status": status.value}
        )
        if data is None:
            raise OrderNotFoundError(order_id)
        return self._parse_order(data)

    async def create(self, order: Order) -> Order:
        payload = self._order_to_payload(order)
        data = await self._client.post("/orders", json=payload)
        if data is None:
            raise RuntimeError("External API returned empty response on order creation")
        return self._parse_order(data)

    # ── Mapping helpers ───────────────────────────────────────────────────────

    def _parse_order(self, raw: dict[str, Any]) -> Order:
        """Map a raw API response dict to the internal Order entity.

        Override this method if the upstream API uses a different field naming
        convention (e.g. snake_case vs camelCase, or a nested `attributes` key).
        """
        # Flexible status parsing — tolerate uppercase and aliases
        raw_status = str(raw.get("status", "pending")).lower()
        try:
            status = OrderStatus(raw_status)
        except ValueError:
            status = OrderStatus.PENDING

        # Items — accept list[dict] or empty
        items_raw: list[dict] = raw.get("items", raw.get("line_items", []))
        items = [
            OrderItem(
                product_id=str(item.get("product_id", item.get("sku", ""))),
                name=str(item.get("name", item.get("title", ""))),
                quantity=int(item.get("quantity", 1)),
                unit_price=float(item.get("unit_price", item.get("price", 0.0))),
            )
            for item in items_raw
        ]

        # Timestamps — accept ISO strings or None
        created_at = self._parse_datetime(raw.get("created_at"))
        updated_at = self._parse_datetime(raw.get("updated_at")) or created_at

        # Wedding-dress metadata (optional — may not exist in generic OMSs)
        meta_raw: dict = raw.get("wedding_meta", raw.get("metadata", {})) or {}
        stage_val = meta_raw.get("production_stage", "pending")
        try:
            stage = ProductionStage(stage_val)
        except ValueError:
            stage = ProductionStage.PENDING

        rush_val = meta_raw.get("rush_level", "none")
        try:
            rush = RushLevel(rush_val)
        except ValueError:
            rush = RushLevel.NONE

        wedding_meta = WeddingMeta(
            dress_style=meta_raw.get("dress_style", ""),
            color=meta_raw.get("color", "ivory_white"),
            is_custom=bool(meta_raw.get("is_custom", False)),
            bust=meta_raw.get("bust"),
            waist=meta_raw.get("waist"),
            hips=meta_raw.get("hips"),
            height=meta_raw.get("height"),
            wedding_date=meta_raw.get("wedding_date"),
            production_stage=stage,
            is_rush=bool(meta_raw.get("is_rush", False)),
            rush_level=rush,
            estimated_completion=meta_raw.get("estimated_completion"),
            alteration_notes=meta_raw.get("alteration_notes", ""),
        )

        return Order(
            order_id=str(raw.get("order_id", raw.get("id", ""))),
            user_id=str(raw.get("user_id", raw.get("customer_id", ""))),
            status=status,
            items=items,
            total=float(raw.get("total", raw.get("total_price", 0.0))),
            created_at=created_at or datetime.now(timezone.utc),
            updated_at=updated_at or datetime.now(timezone.utc),
            shipping_address=str(raw.get("shipping_address", "")),
            tracking_number=str(raw.get("tracking_number", raw.get("fulfillment_tracking", ""))),
            wedding_meta=wedding_meta,
        )

    @staticmethod
    def _order_to_payload(order: Order) -> dict[str, Any]:
        """Serialise an Order to the API's expected create payload."""
        meta = order.wedding_meta
        return {
            "order_id": order.order_id,
            "user_id": order.user_id,
            "status": order.status.value,
            "items": [item.model_dump() for item in order.items],
            "total": order.total,
            "shipping_address": order.shipping_address,
            "tracking_number": order.tracking_number,
            "wedding_meta": {
                "dress_style": meta.dress_style,
                "color": meta.color,
                "is_custom": meta.is_custom,
                "bust": meta.bust,
                "waist": meta.waist,
                "hips": meta.hips,
                "height": meta.height,
                "wedding_date": meta.wedding_date,
                "production_stage": meta.production_stage.value,
                "is_rush": meta.is_rush,
                "rush_level": meta.rush_level.value,
                "estimated_completion": meta.estimated_completion,
                "alteration_notes": meta.alteration_notes,
            },
        }

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            # Handle both "2024-01-15T10:30:00Z" and "2024-01-15 10:30:00"
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
