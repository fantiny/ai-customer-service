#!/usr/bin/env python3
"""Seed demo wedding dress orders for development and testing.

    python scripts/seed_orders.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_customer_service.adapters.repositories.order_repository import OrderRepository
from ai_customer_service.domain.entities import Order, OrderItem, WeddingMeta
from ai_customer_service.domain.value_objects import OrderStatus, ProductionStage, RushLevel
from ai_customer_service.infrastructure.config import get_settings
from ai_customer_service.infrastructure.database import create_db_pool

now = datetime.utcnow()

DEMO_ORDERS: list[Order] = [
    # ── 1. 定制婚纱 · 缝制阶段 ──────────────────────────────────────────
    Order(
        order_id="WD-20240001",
        user_id="demo_user_1",
        status=OrderStatus.CONFIRMED,
        items=[OrderItem(product_id="P001", name="法式蕾丝鱼尾婚纱（香槟色定制）",
                         quantity=1, unit_price=15800.0)],
        total=15800.0,
        shipping_address="北京市朝阳区XX路XX号",
        created_at=now - timedelta(days=20),
        updated_at=now - timedelta(days=2),
        wedding_meta=WeddingMeta(
            dress_style="mermaid",
            color="champagne",
            is_custom=True,
            bust=86.0, waist=66.0, hips=92.0, height=165.0,
            wedding_date=(now + timedelta(days=45)).strftime("%Y-%m-%d"),
            production_stage=ProductionStage.SEWING,
            is_rush=False,
            rush_level=RushLevel.NONE,
            estimated_completion=(now + timedelta(days=25)).strftime("%Y-%m-%d"),
        ),
    ),

    # ── 2. 定制婚纱 · 面料剪裁阶段 · 用户尝试取消 ──────────────────────
    Order(
        order_id="WD-20240002",
        user_id="demo_user_2",
        status=OrderStatus.CONFIRMED,
        items=[OrderItem(product_id="P002", name="A型公主婚纱（象牙白珠绣）",
                         quantity=1, unit_price=12600.0)],
        total=12600.0,
        shipping_address="上海市静安区XX街XX弄",
        created_at=now - timedelta(days=10),
        updated_at=now - timedelta(days=1),
        wedding_meta=WeddingMeta(
            dress_style="a_line",
            color="ivory_white",
            is_custom=True,
            bust=82.0, waist=62.0, hips=88.0, height=162.0,
            wedding_date=(now + timedelta(days=60)).strftime("%Y-%m-%d"),
            production_stage=ProductionStage.CUTTING,
            is_rush=False,
            rush_level=RushLevel.NONE,
            estimated_completion=(now + timedelta(days=40)).strftime("%Y-%m-%d"),
        ),
    ),

    # ── 3. 现货婚纱 · 已发货 · 查物流 ──────────────────────────────────
    Order(
        order_id="WD-20240003",
        user_id="demo_user_3",
        status=OrderStatus.SHIPPED,
        items=[OrderItem(product_id="P003", name="简约修身缎面婚纱（白色现货M码）",
                         quantity=1, unit_price=5800.0)],
        total=5800.0,
        shipping_address="广州市天河区XX大道XX号",
        tracking_number="SF1234567890123",
        created_at=now - timedelta(days=5),
        updated_at=now - timedelta(days=1),
        wedding_meta=WeddingMeta(
            dress_style="sheath",
            color="white",
            is_custom=False,
            wedding_date=(now + timedelta(days=15)).strftime("%Y-%m-%d"),
            production_stage=ProductionStage.READY,
        ),
    ),

    # ── 4. 定制婚纱 · 待排产 · 申请加急 ────────────────────────────────
    Order(
        order_id="WD-20240004",
        user_id="demo_user_4",
        status=OrderStatus.PENDING,
        items=[OrderItem(product_id="P004", name="蓬蓬裙公主婚纱（纯白定制）",
                         quantity=1, unit_price=18500.0)],
        total=18500.0,
        shipping_address="成都市锦江区XX路XX号",
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
        wedding_meta=WeddingMeta(
            dress_style="ball_gown",
            color="white",
            is_custom=True,
            bust=88.0, waist=68.0, hips=94.0, height=168.0,
            wedding_date=(now + timedelta(days=35)).strftime("%Y-%m-%d"),
            production_stage=ProductionStage.PENDING,
            is_rush=False,
            rush_level=RushLevel.NONE,
            estimated_completion=(now + timedelta(days=50)).strftime("%Y-%m-%d"),
        ),
    ),

    # ── 5. 现货婚纱 · 已送达 · 申请退款 ────────────────────────────────
    Order(
        order_id="WD-20240005",
        user_id="demo_user_5",
        status=OrderStatus.DELIVERED,
        items=[OrderItem(product_id="P005", name="复古蕾丝婚纱（象牙白L码）",
                         quantity=1, unit_price=8900.0)],
        total=8900.0,
        shipping_address="杭州市西湖区XX路XX号",
        tracking_number="EMS9988776655",
        created_at=now - timedelta(days=12),
        updated_at=now - timedelta(days=3),
        wedding_meta=WeddingMeta(
            dress_style="vintage",
            color="ivory_white",
            is_custom=False,
            wedding_date=(now + timedelta(days=20)).strftime("%Y-%m-%d"),
            production_stage=ProductionStage.READY,
        ),
    ),

    # ── 6. 加急定制婚纱 · 珠绣阶段 ─────────────────────────────────────
    Order(
        order_id="WD-20240006",
        user_id="demo_user_6",
        status=OrderStatus.CONFIRMED,
        items=[OrderItem(product_id="P006", name="高定手工珠绣鱼尾婚纱（裸粉定制）",
                         quantity=1, unit_price=32000.0)],
        total=32000.0,
        shipping_address="深圳市南山区XX科技园",
        created_at=now - timedelta(days=15),
        updated_at=now - timedelta(days=1),
        wedding_meta=WeddingMeta(
            dress_style="mermaid",
            color="blush_pink",
            is_custom=True,
            bust=84.0, waist=64.0, hips=90.0, height=170.0,
            wedding_date=(now + timedelta(days=22)).strftime("%Y-%m-%d"),
            production_stage=ProductionStage.BEADING,
            is_rush=True,
            rush_level=RushLevel.STANDARD_RUSH,
            estimated_completion=(now + timedelta(days=12)).strftime("%Y-%m-%d"),
        ),
    ),
]


async def seed_orders() -> None:
    settings = get_settings()
    pool = await create_db_pool(settings)
    repo = OrderRepository(pool)

    print(f"Seeding {len(DEMO_ORDERS)} demo wedding dress orders...")
    for order in DEMO_ORDERS:
        await repo.create(order)
        meta = order.wedding_meta
        stage = meta.production_stage.value if meta.is_custom else "现货"
        print(
            f"  ✓ {order.order_id} | {order.items[0].name[:20]}... | "
            f"用户:{order.user_id} | 状态:{order.status.value} | 阶段:{stage}"
        )

    print(f"\n✓ Seeded {len(DEMO_ORDERS)} orders successfully.")
    print("\n用户-订单对应关系：")
    for o in DEMO_ORDERS:
        print(f"  {o.user_id:15s} → {o.order_id}")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(seed_orders())
