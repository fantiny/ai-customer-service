#!/usr/bin/env python3
"""Seed the product catalog into the knowledge base.

    python scripts/seed_products.py

Products are inserted as faq_documents with category='product_catalog'.
BM25 retrieval works without embeddings; vector search will activate
once embedding credits are available.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import asyncpg
from ai_customer_service.infrastructure.config import get_settings

# ── 商品数据 ──────────────────────────────────────────────────────────────────

PRODUCTS = [
    {
        "id": "WD-P001",
        "name": "星河·鱼尾礼服",
        "style": "鱼尾裙",
        "price": 12800,
        "desc": (
            "本季最受欢迎款式，连续6个月销量第一。"
            "采用法国进口弹力真丝缎，全程贴合身体曲线，"
            "膝下展开优雅鱼尾。胸前手工缝制2000+颗施华洛世奇水晶，"
            "在灯光下星光闪烁。适合有一定自信展示曲线的新娘。"
            "可选颜色：象牙白、香槟色。定制周期45天。"
            "适合场合：宴会厅、精致小婚礼、晚宴。"
        ),
        "tags": ["热销", "鱼尾", "水晶", "贴身", "真丝"],
    },
    {
        "id": "WD-P002",
        "name": "云绒·蓬蓬公主裙",
        "style": "蓬蓬裙",
        "price": 9800,
        "desc": (
            "梦幻公主系列年度爆款，小红书曝光超50万次。"
            "六层超轻网纱叠加构成夸张裙摆，内置鱼骨支架保持廓形。"
            "胸口蕾丝贴花精致优雅，自带皇后气场。"
            "裙摆直径约3米，非常上镜。"
            "可选颜色：纯白、象牙白、裸粉。定制周期45天。"
            "适合场合：教堂婚礼、大型宴会厅、城堡婚礼。"
        ),
        "tags": ["热销", "公主裙", "蓬蓬", "网纱", "上镜"],
    },
    {
        "id": "WD-P003",
        "name": "初见·简约缎面修身裙",
        "style": "修身款",
        "price": 6800,
        "desc": (
            "极简主义代表作，深受现代都市新娘喜爱。"
            "100%真丝欧缎面料，手感丝滑，光泽自然高级。"
            "V领设计拉长颈部线条，后背流线型设计若隐若现。"
            "无过多装饰，靠剪裁和面料本身的质感取胜。"
            "可选颜色：纯白、香槟、淡蓝。定制周期30天。"
            "适合场合：户外草坪婚礼、海岛婚礼、民宿婚礼。"
        ),
        "tags": ["热销", "简约", "修身", "真丝", "极简"],
    },
    {
        "id": "WD-P004",
        "name": "倾城·蕾丝A型裙",
        "style": "A型裙",
        "price": 8500,
        "desc": (
            "经典百搭款，适合几乎所有体型。"
            "整件采用法国蕾丝面料覆盖，花纹精致立体，"
            "腰部收紧设计突出细腰，A字裙摆自然展开遮盖臀部曲线。"
            "配有2米拖尾（可拆卸）。梨形、苹果形身材推荐首选。"
            "可选颜色：象牙白、裸粉。定制周期45天。"
            "适合场合：教堂、宴会厅、大部分室内婚礼。"
        ),
        "tags": ["百搭", "A型", "蕾丝", "拖尾", "显瘦"],
    },
    {
        "id": "WD-P005",
        "name": "锦绣·刺绣秀禾服",
        "style": "中式秀禾服",
        "price": 5800,
        "desc": (
            "中式系列最畅销款，敬酒服首选。"
            "真丝提花底料，手工金线刺绣牡丹图案，"
            "寓意富贵吉祥。对襟设计搭配马面裙，"
            "腰部系带可调节松紧，显腰效果极佳。"
            "可选颜色：大红色、酒红色、金红双色。定制周期30天。"
            "适合场合：中式婚礼迎宾、敬酒仪式、回门服。"
        ),
        "tags": ["热销", "秀禾服", "中式", "刺绣", "敬酒服"],
    },
    {
        "id": "WD-P006",
        "name": "映月·轻纱飘逸长裙",
        "style": "轻纱款",
        "price": 7200,
        "desc": (
            "户外婚礼神器，飘逸感十足。"
            "双层真丝欧根纱，轻若无物，随风起舞效果绝美。"
            "胸口精心缝制小面积珍珠装饰，清新不过分华丽。"
            "自带2.5米拖尾，走路时裙摆如云烟。"
            "可选颜色：纯白、薰衣草紫、淡蓝。定制周期40天。"
            "适合场合：草坪婚礼、花园婚礼、海滨婚礼、婚纱摄影。"
        ),
        "tags": ["飘逸", "户外", "欧根纱", "轻盈", "摄影"],
    },
    {
        "id": "WD-P007",
        "name": "珍珠链·复古赫本款",
        "style": "修身款",
        "price": 11200,
        "desc": (
            "赫本复古风格，小众但极具气质。"
            "黑白拼色设计（主体象牙白+腰部黑色缎带），"
            "高领设计优雅端庄，袖口精缝手工珍珠。"
            "裁缝功底深厚，穿上后自带大女主气质。"
            "限量款，每月仅接20单定制。定制周期50天。"
            "适合场合：时尚婚礼、艺术风婚礼、创意主题婚礼。"
        ),
        "tags": ["复古", "高端", "限量", "赫本", "气质"],
    },
    {
        "id": "WD-P008",
        "name": "晨曦·无袖抹胸拖尾礼服",
        "style": "A型裙",
        "price": 15800,
        "desc": (
            "高定系列明星款，多位新娘穿着出圈。"
            "比利时进口蕾丝+国产弹力底料双层结构，"
            "抹胸设计搭配5米拖尾，隆重大气。"
            "胸口手工缝制3D立体花朵装饰，"
            "是婚礼现场最受瞩目的存在。"
            "可选颜色：纯白、香槟。定制周期60天。"
            "适合场合：大型婚礼、教堂婚礼、宴会厅。"
        ),
        "tags": ["高定", "拖尾", "蕾丝", "隆重", "明星同款"],
    },
    {
        "id": "WD-P009",
        "name": "素颜·日系轻婚纱",
        "style": "轻纱款",
        "price": 4200,
        "desc": (
            "平价高颜值，性价比之王。"
            "日式简约风格，薄纱+缎面拼接，清新自然。"
            "适合不想太隆重但又要有婚纱仪式感的新娘。"
            "也是婚纱拍摄的热门租用款。"
            "可选颜色：纯白、象牙白。定制周期25天。"
            "适合场合：小型亲密婚礼、婚纱照拍摄、证件照。"
        ),
        "tags": ["平价", "日系", "简约", "拍照", "性价比"],
    },
    {
        "id": "WD-P010",
        "name": "霞光·渐变彩色礼服",
        "style": "A型裙",
        "price": 13500,
        "desc": (
            "当季最独特款式，个性新娘必选。"
            "裙摆由象牙白渐变至裸粉/薰衣草/珊瑚色（可选），"
            "手工染色工艺，每件颜色细节略有差异，独一无二。"
            "配合光线变化会呈现不同色彩，相机根本停不下来。"
            "仅接全定制，需提前60天下单。"
            "适合场合：小众创意婚礼、户外婚礼、婚纱摄影大片。"
        ),
        "tags": ["渐变", "彩色", "个性", "独特", "摄影"],
    },
    {
        "id": "WD-P011",
        "name": "凌波·深V低背礼服",
        "style": "鱼尾裙",
        "price": 10200,
        "desc": (
            "性感而不失优雅，进阶款首选。"
            "前胸深V设计，后背大幅镂空至腰线，"
            "配合柔软丝绒面料贴合身体每一条曲线。"
            "适合有背部美丽线条、想展示身材的新娘。"
            "可选颜色：纯白、香槟、黑色（非婚礼专属版）。定制周期45天。"
            "适合场合：晚宴、精致小婚礼、蜜月旅行。"
        ),
        "tags": ["低背", "性感", "丝绒", "鱼尾", "进阶"],
    },
    {
        "id": "WD-P012",
        "name": "花嫁·全套婚纱套餐",
        "style": "套餐",
        "price": 18800,
        "desc": (
            "最受欢迎的整体方案，省心省力。"
            "包含：主婚纱（A型/鱼尾任选）+ 秀禾服 + 头纱 + 皇冠 + 手套。"
            "专属顾问全程一对一服务，统一风格搭配。"
            "相比单独购买节省约4000元。"
            "定制周期60天，同步制作所有单品。"
            "适合：希望婚礼当天白纱+中式双穿，又不想分别挑选的新娘。"
        ),
        "tags": ["套餐", "热销", "白纱+中式", "省心", "性价比"],
    },
]


async def seed() -> None:
    settings = get_settings()

    conn: asyncpg.Connection = await asyncpg.connect(
        host="localhost", port=5432,
        user="csuser", password="cspass", database="customer_service",
    )

    inserted = 0
    skipped = 0
    for p in PRODUCTS:
        doc_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"product_{p['id']}"))
        content = (
            f"【商品编号：{p['id']}】{p['name']}\n"
            f"款式：{p['style']} | 参考价格：¥{p['price']:,}\n"
            f"{p['desc']}\n"
            f"标签：{'、'.join(p['tags'])}"
        )
        metadata = {
            "title": p["name"],
            "category": "product_catalog",
            "product_id": p["id"],
            "style": p["style"],
            "price": p["price"],
            "tags": p["tags"],
        }
        try:
            await conn.execute(
                """
                INSERT INTO faq_documents (doc_id, content, metadata)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (doc_id) DO UPDATE
                  SET content = EXCLUDED.content,
                      metadata = EXCLUDED.metadata,
                      updated_at = now()
                """,
                doc_id, content, __import__("json").dumps(metadata, ensure_ascii=False),
            )
            print(f"  ✓ {p['id']}  {p['name']}")
            inserted += 1
        except Exception as e:
            print(f"  ✗ {p['id']}  {p['name']}  — {e}")
            skipped += 1

    await conn.close()
    print(f"\n完成：{inserted} 条商品已写入知识库，{skipped} 条跳过。")
    print("BM25 索引会在下次后端启动时自动重建。")


if __name__ == "__main__":
    asyncio.run(seed())
