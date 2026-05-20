from __future__ import annotations

import json
from datetime import datetime

import asyncpg

from ...domain.entities import Order, OrderItem, WeddingMeta
from ...domain.exceptions import OrderNotFoundError
from ...domain.value_objects import OrderStatus, ProductionStage, RushLevel
from ...use_cases.interfaces import IOrderRepository


class OrderRepository(IOrderRepository):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_by_id(self, order_id: str) -> Order:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM orders WHERE order_id = $1", order_id
            )
        if not row:
            raise OrderNotFoundError(order_id)
        return self._row_to_order(row)

    async def list_by_user(self, user_id: str, limit: int = 10) -> list[Order]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                user_id, limit,
            )
        return [self._row_to_order(r) for r in rows]

    async def update_status(self, order_id: str, status: OrderStatus) -> Order:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE orders SET status = $1, updated_at = NOW()
                WHERE order_id = $2 RETURNING *
                """,
                status.value, order_id,
            )
        if not row:
            raise OrderNotFoundError(order_id)
        return self._row_to_order(row)

    async def create(self, order: Order) -> Order:
        meta = order.wedding_meta
        # Use the domain helper — WeddingMeta already validates the format via
        # field_validator, so this is a safe no-try conversion.
        wedding_date = meta.wedding_date_as_date()

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO orders
                  (order_id, user_id, status, items, total, shipping_address, tracking_number,
                   is_custom, is_rush, production_stage, wedding_date, wedding_metadata,
                   created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                ON CONFLICT (order_id) DO NOTHING
                """,
                order.order_id, order.user_id, order.status.value,
                json.dumps([i.model_dump() for i in order.items]),
                order.total, order.shipping_address, order.tracking_number,
                meta.is_custom, meta.is_rush, meta.production_stage.value,
                wedding_date,
                json.dumps({
                    "dress_style": meta.dress_style,
                    "color": meta.color,
                    "bust": meta.bust, "waist": meta.waist,
                    "hips": meta.hips, "height": meta.height,
                    "rush_level": meta.rush_level.value,
                    "estimated_completion": meta.estimated_completion,
                    "alteration_notes": meta.alteration_notes,
                }),
                order.created_at, order.updated_at,
            )
        return order

    def _row_to_order(self, row: asyncpg.Record) -> Order:
        items_raw = row["items"]
        items_data = json.loads(items_raw) if isinstance(items_raw, str) else items_raw

        # Reconstruct WeddingMeta from columns + JSONB
        w_meta_raw = row.get("wedding_metadata") or "{}"
        w_meta = json.loads(w_meta_raw) if isinstance(w_meta_raw, str) else (w_meta_raw or {})

        stage_val = row.get("production_stage") or "pending"
        try:
            stage = ProductionStage(stage_val)
        except ValueError:
            stage = ProductionStage.PENDING

        wedding_date_col = row.get("wedding_date")
        wedding_date_str = wedding_date_col.isoformat() if wedding_date_col else None

        wedding_meta = WeddingMeta(
            dress_style=w_meta.get("dress_style", ""),
            color=w_meta.get("color", "ivory_white"),
            is_custom=bool(row.get("is_custom", False)),
            bust=w_meta.get("bust"),
            waist=w_meta.get("waist"),
            hips=w_meta.get("hips"),
            height=w_meta.get("height"),
            wedding_date=wedding_date_str or w_meta.get("wedding_date"),
            production_stage=stage,
            is_rush=bool(row.get("is_rush", False)),
            rush_level=RushLevel(w_meta.get("rush_level", "none")),
            estimated_completion=w_meta.get("estimated_completion"),
            alteration_notes=w_meta.get("alteration_notes", ""),
        )

        return Order(
            order_id=row["order_id"],
            user_id=row["user_id"],
            status=OrderStatus(row["status"]),
            items=[OrderItem(**item) for item in items_data],
            total=float(row["total"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            shipping_address=row.get("shipping_address", "") or "",
            tracking_number=row.get("tracking_number", "") or "",
            wedding_meta=wedding_meta,
        )
