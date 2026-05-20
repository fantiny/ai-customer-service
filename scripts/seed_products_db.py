#!/usr/bin/env python3
"""Seed the structured products table from parsed product data.

    python scripts/seed_products_db.py

All 15 products (WD-P001 to WD-P015) are upserted into the `products` table.
This ensures the AI never hallucinates product names or prices.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import asyncpg
from ai_customer_service.infrastructure.config import get_settings

# ── 完整商品数据 ──────────────────────────────────────────────────────────────

PRODUCTS = [
    {
        "product_id": "WD-P001",
        "name": "星河·鱼尾礼服",
        "style": "鱼尾裙",
        "price": 12800.00,
        "deposit_rate": 0.300,
        "production_days": 45,
        "rush_available": True,
        "stock_type": "custom",
        "colors": ["象牙白", "香槟色"],
        "tags": ["热销", "鱼尾", "水晶", "贴身", "真丝"],
        "description": "法国进口弹力真丝缎，全程贴合身体曲线，膝下展开优雅鱼尾。胸前手工缝制2000+颗施华洛世奇水晶，灯光下星光闪烁",
        "occasions": ["宴会厅", "精致小婚礼", "晚宴"],
    },
    {
        "product_id": "WD-P002",
        "name": "云绒·蓬蓬公主裙",
        "style": "蓬蓬裙",
        "price": 9800.00,
        "deposit_rate": 0.300,
        "production_days": 45,
        "rush_available": True,
        "stock_type": "custom",
        "colors": ["纯白", "象牙白", "裸粉"],
        "tags": ["热销", "公主裙", "蓬蓬", "网纱", "上镜"],
        "description": "六层超轻网纱叠加构成夸张裙摆，内置鱼骨支架保持廓形，胸口蕾丝贴花精致优雅，裙摆直径约3米",
        "occasions": ["教堂婚礼", "大型宴会厅", "城堡婚礼"],
    },
    {
        "product_id": "WD-P003",
        "name": "初见·简约缎面修身裙",
        "style": "修身款",
        "price": 6800.00,
        "deposit_rate": 0.300,
        "production_days": 30,
        "rush_available": True,
        "stock_type": "custom",
        "colors": ["纯白", "香槟", "淡蓝"],
        "tags": ["热销", "简约", "修身", "真丝", "极简"],
        "description": "100%真丝欧缎，手感丝滑，V领拉长颈部线条，后背流线型设计若隐若现",
        "occasions": ["户外草坪婚礼", "海岛婚礼", "民宿婚礼"],
    },
    {
        "product_id": "WD-P004",
        "name": "倾城·蕾丝A型裙",
        "style": "A型裙",
        "price": 8500.00,
        "deposit_rate": 0.300,
        "production_days": 45,
        "rush_available": True,
        "stock_type": "custom",
        "colors": ["象牙白", "裸粉"],
        "tags": ["百搭", "A型", "蕾丝", "拖尾", "显瘦"],
        "description": "整件法国蕾丝覆盖，花纹精致立体，腰部收紧突出细腰，配有2米拖尾可拆卸",
        "occasions": ["教堂", "宴会厅", "室内婚礼"],
    },
    {
        "product_id": "WD-P005",
        "name": "锦绣·刺绣秀禾服",
        "style": "中式秀禾服",
        "price": 5800.00,
        "deposit_rate": 0.300,
        "production_days": 30,
        "rush_available": True,
        "stock_type": "custom",
        "colors": ["大红色", "酒红色", "金红双色"],
        "tags": ["热销", "秀禾服", "中式", "刺绣", "敬酒服"],
        "description": "真丝提花底料，手工金线刺绣牡丹图案，对襟设计搭配马面裙",
        "occasions": ["中式婚礼迎宾", "敬酒仪式", "回门服"],
    },
    {
        "product_id": "WD-P006",
        "name": "映月·轻纱飘逸长裙",
        "style": "轻纱款",
        "price": 7200.00,
        "deposit_rate": 0.300,
        "production_days": 40,
        "rush_available": True,
        "stock_type": "custom",
        "colors": ["纯白", "薰衣草紫", "淡蓝"],
        "tags": ["飘逸", "户外", "欧根纱", "轻盈", "摄影"],
        "description": "双层真丝欧根纱，轻若无物，随风起舞效果绝美，胸口精心缝制小面积珍珠装饰，自带2.5米拖尾",
        "occasions": ["草坪婚礼", "花园婚礼", "海滨婚礼", "婚纱摄影"],
    },
    {
        "product_id": "WD-P007",
        "name": "珍珠链·复古赫本款",
        "style": "修身款",
        "price": 11200.00,
        "deposit_rate": 0.300,
        "production_days": 50,
        "rush_available": False,
        "stock_type": "custom",
        "colors": ["象牙白+黑色腰带"],
        "tags": ["复古", "高端", "限量", "赫本", "气质"],
        "description": "赫本复古风格，限量款每月仅接20单，黑白拼色（主体象牙白+腰部黑色缎带），高领优雅端庄",
        "occasions": ["时尚婚礼", "艺术风婚礼", "创意主题婚礼"],
    },
    {
        "product_id": "WD-P008",
        "name": "晨曦·无袖抹胸拖尾礼服",
        "style": "A型裙",
        "price": 15800.00,
        "deposit_rate": 0.300,
        "production_days": 60,
        "rush_available": False,
        "stock_type": "custom",
        "colors": ["纯白", "香槟"],
        "tags": ["高定", "拖尾", "蕾丝", "隆重", "明星同款"],
        "description": "比利时进口蕾丝+弹力底料双层结构，抹胸设计搭配5米拖尾，胸口手工3D立体花朵",
        "occasions": ["大型婚礼", "教堂婚礼", "宴会厅"],
    },
    {
        "product_id": "WD-P009",
        "name": "素颜·日系轻婚纱",
        "style": "轻纱款",
        "price": 4200.00,
        "deposit_rate": 0.300,
        "production_days": 25,
        "rush_available": True,
        "stock_type": "ready",
        "colors": ["纯白", "象牙白"],
        "tags": ["平价", "日系", "简约", "拍照", "性价比", "现货"],
        "description": "日式简约风，薄纱+缎面拼接，清新自然，现货S/M/L/XL均有库存",
        "occasions": ["小型亲密婚礼", "婚纱照拍摄", "证件照"],
    },
    {
        "product_id": "WD-P010",
        "name": "霞光·渐变彩色礼服",
        "style": "A型裙",
        "price": 13500.00,
        "deposit_rate": 0.300,
        "production_days": 60,
        "rush_available": False,
        "stock_type": "custom",
        "colors": ["象牙白渐变裸粉", "象牙白渐变薰衣草", "象牙白渐变珊瑚"],
        "tags": ["渐变", "彩色", "个性", "独特", "摄影"],
        "description": "裙摆由象牙白渐变至裸粉/薰衣草/珊瑚色，手工染色独一无二，仅接全定制需提前60天下单",
        "occasions": ["小众创意婚礼", "户外婚礼", "婚纱摄影"],
    },
    {
        "product_id": "WD-P011",
        "name": "凌波·深V低背礼服",
        "style": "鱼尾裙",
        "price": 10200.00,
        "deposit_rate": 0.300,
        "production_days": 45,
        "rush_available": True,
        "stock_type": "custom",
        "colors": ["纯白", "香槟", "黑色"],
        "tags": ["低背", "性感", "丝绒", "鱼尾", "进阶"],
        "description": "前胸深V，后背大幅镂空至腰线，柔软丝绒面料贴合每一条曲线",
        "occasions": ["晚宴", "精致小婚礼", "蜜月旅行"],
    },
    {
        "product_id": "WD-P012",
        "name": "花嫁·全套婚纱套餐",
        "style": "套餐",
        "price": 18800.00,
        "deposit_rate": 0.300,
        "production_days": 60,
        "rush_available": False,
        "stock_type": "custom",
        "colors": ["按主婚纱颜色定制"],
        "tags": ["套餐", "热销", "白纱+中式", "省心", "性价比"],
        "description": "包含主婚纱(A型/鱼尾任选)+秀禾服+头纱+皇冠+手套，专属顾问全程一对一，相比单买节省约4000元",
        "occasions": ["全场景"],
    },
    {
        "product_id": "WD-P013",
        "name": "澜颐·深海蓝鱼尾礼服",
        "style": "鱼尾裙",
        "price": 11800.00,
        "deposit_rate": 0.300,
        "production_days": 45,
        "rush_available": True,
        "stock_type": "custom",
        "colors": ["深海蓝"],
        "tags": ["彩色", "鱼尾", "个性", "海滨", "串珠"],
        "description": "深海蓝染色真丝缎，腰部镶嵌手工串珠腰带，裙摆及地带轻微拖尾，适合有个性的新娘",
        "occasions": ["海滨婚礼", "蓝色主题婚礼", "个性婚礼"],
    },
    {
        "product_id": "WD-P014",
        "name": "仙气·多层蕾丝A型长裙",
        "style": "A型裙",
        "price": 7600.00,
        "deposit_rate": 0.300,
        "production_days": 40,
        "rush_available": True,
        "stock_type": "ready",
        "colors": ["纯白", "淡粉"],
        "tags": ["现货", "仙气", "蕾丝", "飘逸", "拍照"],
        "description": "轻薄多层蕾丝叠加，仙气飘飘，肩部挑绣同色花纹，现货尺码XS/S/M/L",
        "occasions": ["户外婚礼", "花园婚礼", "森系婚礼"],
    },
    {
        "product_id": "WD-P015",
        "name": "御风·宫廷风泡泡袖礼服",
        "style": "A型裙",
        "price": 8900.00,
        "deposit_rate": 0.300,
        "production_days": 45,
        "rush_available": True,
        "stock_type": "custom",
        "colors": ["象牙白", "浅驼色"],
        "tags": ["宫廷", "泡泡袖", "复古", "秋冬", "丝绒"],
        "description": "泡泡袖设计，V领和腰部收紧，奥地利进口丝绒，背部系带设计腰围可微调",
        "occasions": ["秋冬婚礼", "城堡婚礼", "教堂婚礼"],
    },
]


async def seed() -> None:
    settings = get_settings()
    dsn = settings.POSTGRES_URL.replace("postgresql+asyncpg://", "postgresql://")
    print(f"Connecting to: {dsn.split('@')[-1]}")

    conn: asyncpg.Connection = await asyncpg.connect(dsn=dsn)

    inserted = 0
    skipped = 0
    try:
        for p in PRODUCTS:
            try:
                await conn.execute(
                    """
                    INSERT INTO products (
                        product_id, name, style, price, deposit_rate,
                        production_days, rush_available, stock_type,
                        colors, tags, description, occasions, active
                    ) VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8,
                        $9, $10, $11, $12, true
                    )
                    ON CONFLICT (product_id) DO UPDATE SET
                        name            = EXCLUDED.name,
                        style           = EXCLUDED.style,
                        price           = EXCLUDED.price,
                        deposit_rate    = EXCLUDED.deposit_rate,
                        production_days = EXCLUDED.production_days,
                        rush_available  = EXCLUDED.rush_available,
                        stock_type      = EXCLUDED.stock_type,
                        colors          = EXCLUDED.colors,
                        tags            = EXCLUDED.tags,
                        description     = EXCLUDED.description,
                        occasions       = EXCLUDED.occasions,
                        active          = EXCLUDED.active
                    """,
                    p["product_id"],
                    p["name"],
                    p["style"],
                    p["price"],
                    p["deposit_rate"],
                    p["production_days"],
                    p["rush_available"],
                    p["stock_type"],
                    p["colors"],
                    p["tags"],
                    p["description"],
                    p["occasions"],
                )
                print(f"  ✓ {p['product_id']}  {p['name']}  ¥{p['price']:,.0f}")
                inserted += 1
            except Exception as e:
                print(f"  ✗ {p['product_id']}  {p['name']}  — {e}")
                skipped += 1
    finally:
        await conn.close()

    print(f"\n完成：{inserted} 条商品已写入 products 表，{skipped} 条失败。")


if __name__ == "__main__":
    asyncio.run(seed())
