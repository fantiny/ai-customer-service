#!/usr/bin/env python3
"""缘梦婚纱 · 完整运营数据初始化脚本

覆盖：商品知识库、FAQ 知识库、订单数据（30+）、客服账号
运行方式：
    uv run python scripts/seed_all.py
    uv run python scripts/seed_all.py --clear   # 先清空再写入
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import asyncpg
from ai_customer_service.infrastructure.config import get_settings

now = datetime.utcnow()


# ══════════════════════════════════════════════════════════════════════════════
# 一、商品目录（product_catalog）
# ══════════════════════════════════════════════════════════════════════════════

PRODUCTS = [
    {
        "id": "WD-P001",
        "name": "星河·鱼尾礼服",
        "style": "鱼尾裙",
        "price": 12800,
        "deposit": 3840,
        "production_days": 45,
        "rush_available": True,
        "stock_type": "custom",
        "desc": (
            "本季最受欢迎款式，连续6个月销量第一。"
            "采用法国进口弹力真丝缎，全程贴合身体曲线，膝下展开优雅鱼尾。"
            "胸前手工缝制 2000+ 颗施华洛世奇水晶，灯光下星光闪烁。"
            "可选颜色：象牙白、香槟色。定制周期 45 天。"
            "适合场合：宴会厅、精致小婚礼、晚宴。"
        ),
        "colors": ["象牙白", "香槟色"],
        "tags": ["热销", "鱼尾", "水晶", "贴身", "真丝"],
    },
    {
        "id": "WD-P002",
        "name": "云绒·蓬蓬公主裙",
        "style": "蓬蓬裙",
        "price": 9800,
        "deposit": 2940,
        "production_days": 45,
        "rush_available": True,
        "stock_type": "custom",
        "desc": (
            "梦幻公主系列年度爆款，小红书曝光超50万次。"
            "六层超轻网纱叠加构成夸张裙摆，内置鱼骨支架保持廓形。"
            "胸口蕾丝贴花精致优雅，裙摆直径约3米，非常上镜。"
            "可选颜色：纯白、象牙白、裸粉。定制周期 45 天。"
            "适合场合：教堂婚礼、大型宴会厅、城堡婚礼。"
        ),
        "colors": ["纯白", "象牙白", "裸粉"],
        "tags": ["热销", "公主裙", "蓬蓬", "网纱", "上镜"],
    },
    {
        "id": "WD-P003",
        "name": "初见·简约缎面修身裙",
        "style": "修身款",
        "price": 6800,
        "deposit": 2040,
        "production_days": 30,
        "rush_available": True,
        "stock_type": "custom",
        "desc": (
            "极简主义代表作，深受现代都市新娘喜爱。"
            "100% 真丝欧缎，手感丝滑，光泽自然高级。"
            "V 领拉长颈部线条，后背流线型设计若隐若现。"
            "可选颜色：纯白、香槟、淡蓝。定制周期 30 天。"
            "适合场合：户外草坪婚礼、海岛婚礼、民宿婚礼。"
        ),
        "colors": ["纯白", "香槟", "淡蓝"],
        "tags": ["热销", "简约", "修身", "真丝", "极简"],
    },
    {
        "id": "WD-P004",
        "name": "倾城·蕾丝A型裙",
        "style": "A型裙",
        "price": 8500,
        "deposit": 2550,
        "production_days": 45,
        "rush_available": True,
        "stock_type": "custom",
        "desc": (
            "经典百搭款，适合几乎所有体型。"
            "整件法国蕾丝覆盖，花纹精致立体，腰部收紧突出细腰。"
            "配有 2 米拖尾（可拆卸），梨形、苹果形身材首选。"
            "可选颜色：象牙白、裸粉。定制周期 45 天。"
            "适合场合：教堂、宴会厅、大部分室内婚礼。"
        ),
        "colors": ["象牙白", "裸粉"],
        "tags": ["百搭", "A型", "蕾丝", "拖尾", "显瘦"],
    },
    {
        "id": "WD-P005",
        "name": "锦绣·刺绣秀禾服",
        "style": "中式秀禾服",
        "price": 5800,
        "deposit": 1740,
        "production_days": 30,
        "rush_available": True,
        "stock_type": "custom",
        "desc": (
            "中式系列最畅销款，敬酒服首选。"
            "真丝提花底料，手工金线刺绣牡丹图案，寓意富贵吉祥。"
            "对襟设计搭配马面裙，腰部系带可调节。"
            "可选颜色：大红色、酒红色、金红双色。定制周期 30 天。"
            "适合场合：中式婚礼迎宾、敬酒仪式、回门服。"
        ),
        "colors": ["大红色", "酒红色", "金红双色"],
        "tags": ["热销", "秀禾服", "中式", "刺绣", "敬酒服"],
    },
    {
        "id": "WD-P006",
        "name": "映月·轻纱飘逸长裙",
        "style": "轻纱款",
        "price": 7200,
        "deposit": 2160,
        "production_days": 40,
        "rush_available": True,
        "stock_type": "custom",
        "desc": (
            "户外婚礼神器，飘逸感十足。"
            "双层真丝欧根纱，轻若无物，随风起舞效果绝美。"
            "胸口精心缝制小面积珍珠装饰，自带 2.5 米拖尾。"
            "可选颜色：纯白、薰衣草紫、淡蓝。定制周期 40 天。"
            "适合场合：草坪婚礼、花园婚礼、海滨婚礼、婚纱摄影。"
        ),
        "colors": ["纯白", "薰衣草紫", "淡蓝"],
        "tags": ["飘逸", "户外", "欧根纱", "轻盈", "摄影"],
    },
    {
        "id": "WD-P007",
        "name": "珍珠链·复古赫本款",
        "style": "修身款",
        "price": 11200,
        "deposit": 3360,
        "production_days": 50,
        "rush_available": False,
        "stock_type": "custom",
        "desc": (
            "赫本复古风格，小众但极具气质。限量款，每月仅接20单。"
            "黑白拼色（主体象牙白+腰部黑色缎带），高领优雅端庄，袖口手工珍珠。"
            "定制周期 50 天。"
            "适合场合：时尚婚礼、艺术风婚礼、创意主题婚礼。"
        ),
        "colors": ["象牙白+黑色腰带"],
        "tags": ["复古", "高端", "限量", "赫本", "气质"],
    },
    {
        "id": "WD-P008",
        "name": "晨曦·无袖抹胸拖尾礼服",
        "style": "A型裙",
        "price": 15800,
        "deposit": 4740,
        "production_days": 60,
        "rush_available": False,
        "stock_type": "custom",
        "desc": (
            "高定系列明星款。比利时进口蕾丝+弹力底料双层结构，"
            "抹胸设计搭配 5 米拖尾，隆重大气。"
            "胸口手工 3D 立体花朵，婚礼现场最受瞩目。"
            "可选颜色：纯白、香槟。定制周期 60 天。"
            "适合场合：大型婚礼、教堂婚礼、宴会厅。"
        ),
        "colors": ["纯白", "香槟"],
        "tags": ["高定", "拖尾", "蕾丝", "隆重", "明星同款"],
    },
    {
        "id": "WD-P009",
        "name": "素颜·日系轻婚纱",
        "style": "轻纱款",
        "price": 4200,
        "deposit": 1260,
        "production_days": 25,
        "rush_available": True,
        "stock_type": "stock",
        "desc": (
            "平价高颜值，性价比之王。日式简约风，薄纱+缎面拼接，清新自然。"
            "也是婚纱拍摄热门租用款。现货S/M/L/XL均有库存。"
            "可选颜色：纯白、象牙白。定制周期 25 天。"
            "适合场合：小型亲密婚礼、婚纱照拍摄、证件照。"
        ),
        "colors": ["纯白", "象牙白"],
        "tags": ["平价", "日系", "简约", "拍照", "性价比", "现货"],
    },
    {
        "id": "WD-P010",
        "name": "霞光·渐变彩色礼服",
        "style": "A型裙",
        "price": 13500,
        "deposit": 4050,
        "production_days": 60,
        "rush_available": False,
        "stock_type": "custom",
        "desc": (
            "当季最独特款式，个性新娘必选。"
            "裙摆由象牙白渐变至裸粉/薰衣草/珊瑚色（三选一），手工染色，独一无二。"
            "仅接全定制，需提前 60 天下单。"
            "适合场合：小众创意婚礼、户外婚礼、婚纱摄影大片。"
        ),
        "colors": ["象牙白渐变裸粉", "象牙白渐变薰衣草", "象牙白渐变珊瑚"],
        "tags": ["渐变", "彩色", "个性", "独特", "摄影"],
    },
    {
        "id": "WD-P011",
        "name": "凌波·深V低背礼服",
        "style": "鱼尾裙",
        "price": 10200,
        "deposit": 3060,
        "production_days": 45,
        "rush_available": True,
        "stock_type": "custom",
        "desc": (
            "性感而不失优雅，进阶款首选。前胸深V，后背大幅镂空至腰线。"
            "柔软丝绒面料贴合每一条曲线。"
            "可选颜色：纯白、香槟、黑色（非婚礼专属版）。定制周期 45 天。"
            "适合场合：晚宴、精致小婚礼、蜜月旅行。"
        ),
        "colors": ["纯白", "香槟", "黑色"],
        "tags": ["低背", "性感", "丝绒", "鱼尾", "进阶"],
    },
    {
        "id": "WD-P012",
        "name": "花嫁·全套婚纱套餐",
        "style": "套餐",
        "price": 18800,
        "deposit": 5640,
        "production_days": 60,
        "rush_available": False,
        "stock_type": "custom",
        "desc": (
            "最受欢迎整体方案，省心省力。"
            "包含：主婚纱（A型/鱼尾任选）+ 秀禾服 + 头纱 + 皇冠 + 手套。"
            "专属顾问全程一对一，统一风格搭配，相比单买节省约 4000 元。"
            "定制周期 60 天，同步制作所有单品。"
        ),
        "colors": ["按主婚纱颜色定制"],
        "tags": ["套餐", "热销", "白纱+中式", "省心", "性价比"],
    },
    {
        "id": "WD-P013",
        "name": "澜颐·深海蓝鱼尾礼服",
        "style": "鱼尾裙",
        "price": 11800,
        "deposit": 3540,
        "production_days": 45,
        "rush_available": True,
        "stock_type": "custom",
        "desc": (
            "突破传统白色限制的彩色婚纱代表作。"
            "深海蓝染色真丝缎，腰部镶嵌手工串珠腰带，裙摆及地带轻微拖尾。"
            "适合有个性、想做与众不同的新娘。"
            "颜色：深海蓝（不可更换）。定制周期 45 天。"
            "适合场合：海滨婚礼、蓝色主题婚礼、个性婚礼。"
        ),
        "colors": ["深海蓝"],
        "tags": ["彩色", "鱼尾", "个性", "海滨", "串珠"],
    },
    {
        "id": "WD-P014",
        "name": "仙气·多层蕾丝A型长裙",
        "style": "A型裙",
        "price": 7600,
        "deposit": 2280,
        "production_days": 40,
        "rush_available": True,
        "stock_type": "stock",
        "desc": (
            "现货可售，也支持按尺寸定制。"
            "轻薄多层蕾丝叠加，仙气飘飘，拍照极美。"
            "肩部挑绣同色花纹，在灯光下若隐若现，小清新风格首选。"
            "现货尺码 XS/S/M/L，可选颜色：纯白、淡粉。定制周期 40 天。"
            "适合场合：户外婚礼、花园婚礼、森系婚礼。"
        ),
        "colors": ["纯白", "淡粉"],
        "tags": ["现货", "仙气", "蕾丝", "飘逸", "拍照"],
    },
    {
        "id": "WD-P015",
        "name": "御风·宫廷风泡泡袖礼服",
        "style": "A型裙",
        "price": 8900,
        "deposit": 2670,
        "production_days": 45,
        "rush_available": True,
        "stock_type": "custom",
        "desc": (
            "宫廷复古风格大热款。泡泡袖设计独特，"
            "配合V领和腰部收紧，营造上宽下窄的完美比例。"
            "背部系带设计，腰围可微调，贴合性好。"
            "面料采用奥地利进口丝绒，厚重高级感十足。"
            "可选颜色：象牙白、浅驼色。定制周期 45 天。"
            "适合场合：秋冬婚礼、城堡婚礼、教堂婚礼。"
        ),
        "colors": ["象牙白", "浅驼色"],
        "tags": ["宫廷", "泡泡袖", "复古", "秋冬", "丝绒"],
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# 二、FAQ 知识库（wedding_dress_faq）
# ══════════════════════════════════════════════════════════════════════════════

FAQ_EXTRA = [
    {
        "title": "常见投诉问题处理指南",
        "content": """【常见投诉问题与处理方案】

**问题1：收到婚纱颜色与照片不符**
原因分析：屏幕色差是最常见原因，真实面料颜色与屏幕显示存在差异。
处理方案：
- 48小时内联系客服并提交照片对比
- 若确实偏差较大（非屏幕色差），我们提供免费重做或退款
- 建议：下单前申请免费色样确认，可规避99%的颜色纠纷

**问题2：尺寸偏差 — 婚纱偏大/偏小**
轻微偏差（腰围±3cm以内）：提供免费修改，7个工作日完成
中等偏差（腰围3-8cm）：提供免费修改，需返厂，10-15天
严重偏差（超8cm，或明显裁剪失误）：全额赔偿或重做

**问题3：蕾丝/珠绣脱落、线头外露**
质量问题全程保修6个月，免费返修。
快递往返费用由我们承担。

**问题4：快递损坏**
请在收货时当场检查，若发现损坏：
1. 拒绝签收并拍照
2. 联系客服，我们处理保价索赔
3. 提供补发或退款

**问题5：婚礼临近但婚纱未到货**
- 立即联系专属顾问查询物流
- 如确属我方延迟，协调加急配送或提供备用方案
- 超出约定交期3天以上，赔偿300元/天延迟金""",
    },
    {
        "title": "婚纱尺码换算与体型建议",
        "content": """【婚纱尺码换算指南】

**中国尺码 vs 欧码 vs 美码对照**
XS码：胸围74-78 / 腰围56-60 / 臀围82-86（欧码32-34，美码0-2）
S码：胸围78-82 / 腰围60-64 / 臀围86-90（欧码36，美码4）
M码：胸围83-87 / 腰围65-69 / 臀围91-95（欧码38，美码6）
L码：胸围88-92 / 腰围70-74 / 臀围96-100（欧码40，美码8）
XL码：胸围93-97 / 腰围75-79 / 臀围101-105（欧码42，美码10）
XXL码：胸围98-103 / 腰围80-85 / 臀围106-111（欧码44，美码12）

**特殊体型建议**
- 三围跨两个尺码（如胸M腰S）：强烈建议定制
- 身高150cm以下：建议定制并缩短裙长10-15cm
- 身高175cm以上：建议定制并加长裙摆和拖尾

**怀孕新娘**
- 建议选择腰部有系带调节的款式（如秀禾服）
- 或A型/蓬蓬裙（腰部宽松不贴身）
- 下单时请告知预产期，顾问专项服务

**婚前体重变化应对**
- 减肥计划中：建议选略大1码再修改，而非按目标体重定制
- 孕期：量体后预留放量，后期可收紧""",
    },
    {
        "title": "退款流程与时间说明",
        "content": """【退款操作流程与到账时间】

**申请退款入口**
1. 联系客服（微信/电话/在线）
2. 说明订单号和退款原因
3. 客服确认退款金额（按生产阶段计算）
4. 签署退款协议

**退款到账时间**
- 支付宝/微信支付：1-3个工作日
- 银行卡（原路退回）：3-7个工作日
- 信用卡：7-15个工作日（由发卡行处理）

**定制婚纱退款金额计算规则**
| 生产阶段 | 退款比例 | 说明 |
|---------|---------|------|
| 待排产 | 100% | 全额无损退 |
| 已确认排产 | 90% | 扣除设计费 10% |
| 剪裁中 | 50% | 面料已裁剪无法转售 |
| 缝制中 | 0% | 主体成型无法转售 |
| 珠绣/质检/完成 | 0% | 成品无法转售 |

**特殊情况**
- 质量问题引起的退款：100%退款，额外赔偿运费
- 超期未发货（超出承诺日期3天以上）：可申请全额退款

**退款后婚纱处理**
- 已生产50%以上的婚纱，退款后婚纱归我方所有（用于展示/样品）
- 未生产的订单，无需退还面料""",
    },
    {
        "title": "加急费用详细说明",
        "content": """【加急制作费用与规则】

**加急标准**
| 类型 | 标准周期 | 加急后 | 附加费率 |
|------|---------|--------|---------|
| 标准加急 | 45天 | 30天 | +50% |
| 紧急加急 | 45天 | 20天 | +80% |
| 特急 | 45天 | 15天 | +100% |
| 超特急 | 45天 | 10天 | 面议（需审核产能） |

**加急费用举例**
- 星河·鱼尾礼服（¥12,800）30天加急 → 总价 ¥19,200（加急费 ¥6,400）
- 初见·简约缎面（¥6,800）20天加急 → 总价 ¥12,240（加急费 ¥5,440）

**加急条件**
1. 非限量/超复杂款（珍珠链赫本款、晨曦拖尾款暂不接加急）
2. 定金支付后3小时内确认排产
3. 尺码/颜色/细节一次性确定，不支持中途修改

**加急申请流程**
1. 联系客服说明婚期
2. 客服确认产能（2小时内）
3. 确认后支付加急费+定金
4. 当日安排优先排产

**提示**：10天以内的超特急订单，如未能按时完成，
承诺全额退还加急费并赔偿延迟金。""",
    },
    {
        "title": "婚纱质量问题判定标准",
        "content": """【质量问题判定与客诉处理标准】

**属于质量问题（由我方负责）**
✓ 蕾丝脱落、线头外露（>3根）
✓ 珠绣脱落（>5颗）
✓ 尺寸偏差超过承诺±2cm范围
✓ 颜色明显偏差（非屏幕色差，与色样相比ΔE>5）
✓ 面料有破损、抽丝、污渍
✓ 拉链损坏、扣子脱落
✓ 交货日期超出承诺日期3天以上

**不属于质量问题**
✗ 照片/屏幕颜色与实物有细微差异（正常色差）
✗ 婚纱体重变化导致不合身（非量体错误）
✗ 个人喜好变化（"觉得穿起来不好看"）
✗ 摄影效果与期望不符
✗ 正常穿着中产生的细微皱褶

**质量投诉提交要求**
1. 48小时内联系客服（过期视为验收合格）
2. 提供订单号 + 清晰照片（至少3张不同角度）
3. 说明问题描述和发现时间

**赔偿标准**
- 轻微问题（修改可解决）：免费返修+200元补偿
- 中等问题（影响穿着效果）：免费返修+500-1000元补偿
- 严重问题（无法修复）：全额退款+500元补偿""",
    },
    {
        "title": "婚纱订单修改规则",
        "content": """【下单后的修改规则】

**可修改内容及截止时间**
| 修改项目 | 截止时间 | 费用 |
|---------|---------|------|
| 颜色更换 | 排产前 | 免费 |
| 尺码调整 | 开始裁剪前 | 免费 |
| 款式变更 | 48小时内 | 面议（可能收取重新设计费） |
| 加急升级 | 开始生产前 | 按加急费率补差价 |
| 收货地址 | 发货前24小时 | 免费 |
| 配件增减（头纱/手套） | 生产完成前 | 按售价结算 |

**无法修改的情况**
- 缝制开始后，尺码/颜色/款式均不可更改
- 特殊面料（手工染色、限量进口）下单后不可更换颜色

**修改申请方式**
直接联系专属顾问，说明订单号和修改内容，
顾问确认后在系统内更新并回复确认消息。

**建议**：下单前务必确认所有细节，
特别是颜色（申请色样）和尺寸（重新量体），
减少后期修改带来的不便。""",
    },
    {
        "title": "门店信息与预约到访",
        "content": """【缘梦婚纱门店信息】

**北京旗舰店**
地址：北京市朝阳区三里屯太古里北区 N4-04
营业时间：周一至周日 10:00-21:00
电话：010-8888-0001
可体验：试穿、量体、定制咨询、VVIP接待室

**上海体验店**
地址：上海市静安区南京西路1788号嘉里中心商场2F
营业时间：周一至周日 10:00-21:00
电话：021-6666-0002
可体验：试穿、量体、定制咨询

**成都概念店**
地址：成都市锦江区红星路三段1号IFS国际金融中心5F
营业时间：周二至周日 11:00-20:00（周一闭店）
电话：028-8899-0003
可体验：试穿、咨询（量体需预约）

**预约到访流程**
1. 联系客服或官网预约系统填写预约
2. 选择门店、日期（需提前1天）
3. 确认时间段（每次90分钟）
4. 门店确认短信提醒

**到店注意事项**
- 建议穿着与婚礼相近的内衣
- 可携带1-2位亲友陪同
- 请准时到达，迟到超15分钟视为自动取消""",
    },
    {
        "title": "伴娘服与配套服装",
        "content": """【伴娘服与婚礼配套服装】

**伴娘服系列**
我们提供与婚纱同系列的伴娘服，风格统一、搭配和谐。

主要款式：
- 抹胸A型长款：价格 980-1580 元/件
- 高腰短款包臀裙：价格 680-980 元/件
- 简约V领中长款：价格 780-1200 元/件

颜色：与主婚纱搭配定制（如主婚纱象牙白，伴娘可选裸粉/薰衣草）

**套购优惠**
- 婚纱 + 3件伴娘服：整单 8.5折
- 婚纱 + 5件及以上伴娘服：整单 8折
- 婚纱 + 秀禾服套餐：8.5折

**花童礼服**
与伴娘服同系列小码，适合 100-150cm 身高儿童。
价格：380-680元/件

**婚庆配套**
- 新郎衬衣/领结：200-580元（与新娘礼服色系搭配）
- 父母礼服推荐款：可提供搭配建议

**批量定制**
婚礼伴娘团5人以上，提供专属顾问一对一量体上门服务（仅北京/上海）。""",
    },
    {
        "title": "婚纱清洗与婚后保养服务",
        "content": """【婚后婚纱清洗与寄存服务】

**婚纱清洗服务**
婚礼结束后，婚纱往往沾有化妆品、泥土、红酒等污迹，
必须专业处理，不可自行水洗或干洗。

我们的专业洗护流程：
1. 全件检查，标记污渍位置
2. 局部针对性处理（化妆品、油脂、红酒专项）
3. 整体蒸汽清洁
4. 重新熨烫定形
5. 无酸盒保存装箱

**清洗费用**
- 简单款（无拖尾、少装饰）：200-350元
- 标准款（有拖尾或蕾丝）：350-600元
- 复杂款（多层拖尾+手工珠绣）：600-1200元

**婚纱寄存服务**
洗护完成后可委托我们保管：
- 恒温恒湿专业库房存放
- 年费：380元/年（含一次免费检查）
- 随时可取回，提前3天通知即可

**婚纱改造**
婚纱可改造为：
- 晚宴长礼服（去掉拖尾、改为正装裙）
- 写真礼服（精简版）
- 亲子同款（用原款面料制作儿童礼服）
报价需实物评估，一般500-2000元不等。""",
    },
    {
        "title": "海外购买与国际配送说明",
        "content": """【海外客户购买指南】

**支持购买的地区**
港澳台、亚洲地区（日本、韩国、新加坡、马来西亚等）、
欧美地区（美国、加拿大、英国、澳大利亚等）

**国际配送信息**
| 地区 | 物流方式 | 时效 | 运费 |
|------|---------|------|------|
| 港澳台 | 顺丰国际 | 3-5天 | 80元 |
| 亚洲 | DHL/EMS | 5-10天 | 300-600元 |
| 欧洲/北美 | DHL优先 | 7-14天 | 600-1200元 |
| 其他地区 | EMS | 10-20天 | 400-800元 |

**海外客户注意事项**
1. 关税：进口关税由买方承担，我们提供正规发票
2. 颜色确认：强烈建议申请色样（寄样费50元，购买后抵扣）
3. 量体：推荐到当地裁缝店量体，或按我们的视频指导自行量体
4. 退换货：国际退货运费由买方承担，仅支持质量问题退款

**美国/加拿大客户专项**
与洛杉矶/纽约华人婚纱工作室合作，
可提供本地试穿（需提前预约），修改也可本地处理。
联系我们获取合作工作室名单。

**支付方式**
- 国际信用卡（Visa/Mastercard/Amex）
- PayPal
- 支付宝（境外版）""",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# 三、订单数据（30 条覆盖全场景）
# ══════════════════════════════════════════════════════════════════════════════

def _d(delta_days: int) -> datetime:
    return now - timedelta(days=delta_days)


def _dd(delta_days: int) -> str:
    return (now + timedelta(days=delta_days)).strftime("%Y-%m-%d")


# (order_id, user_id, status, production_stage, is_custom, is_rush,
#  name, product_id, price, shipping_addr, tracking_no,
#  bust, waist, hips, height, color, wedding_date_days,
#  created_days_ago, updated_days_ago, estimated_days)
ORDERS = [
    # ── 正常进行中 · 各生产阶段 ──────────────────────────────────────────────
    ("WD-2025-0001", "user_chen_fang",      "confirmed", "sewing",   True,  False,
     "星河·鱼尾礼服（香槟色定制）",    "WD-P001", 12800.0,
     "北京市朝阳区建国路88号SOHO现代城",  "",
     86.0, 66.0, 92.0, 165.0, "香槟色", 40, 22, 2, 18),

    ("WD-2025-0002", "user_liu_xin",        "confirmed", "cutting",  True,  False,
     "倾城·蕾丝A型裙（象牙白）",       "WD-P004", 8500.0,
     "上海市静安区南京西路100号",        "",
     82.0, 62.0, 88.0, 162.0, "象牙白", 55, 12, 1, 33),

    ("WD-2025-0003", "user_zhang_hui",      "confirmed", "beading",  True,  True,
     "晨曦·无袖抹胸拖尾礼服（纯白）",  "WD-P008", 23700.0,
     "深圳市南山区科技园南区",           "",
     84.0, 64.0, 90.0, 170.0, "纯白", 25, 18, 3, 7),

    ("WD-2025-0004", "user_wang_min",       "confirmed", "qc",       True,  False,
     "云绒·蓬蓬公主裙（裸粉定制）",    "WD-P002", 9800.0,
     "广州市天河区体育西路68号",         "",
     80.0, 60.0, 86.0, 158.0, "裸粉", 12, 50, 1, 3),

    ("WD-2025-0005", "user_zhao_lei",       "confirmed", "ready",    True,  False,
     "映月·轻纱飘逸长裙（薰衣草紫）",  "WD-P006", 7200.0,
     "成都市武侯区天府大道100号",        "",
     83.0, 63.0, 89.0, 163.0, "薰衣草紫", 8, 45, 0, 0),

    # ── 已发货/物流在途 ────────────────────────────────────────────────────
    ("WD-2025-0006", "user_li_mei",         "shipped",   "ready",    False, False,
     "素颜·日系轻婚纱（纯白M码现货）", "WD-P009", 4200.0,
     "杭州市西湖区文三路498号",          "SF7890001234567",
     0.0, 0.0, 0.0, 163.0, "纯白", 10, 7, 1, 0),

    ("WD-2025-0007", "user_huang_ting",     "shipped",   "ready",    True,  False,
     "锦绣·刺绣秀禾服（大红色定制）",  "WD-P005", 5800.0,
     "西安市雁塔区小寨路58号",          "YT9988776655441",
     78.0, 60.0, 84.0, 158.0, "大红色", 6, 35, 0, 0),

    ("WD-2025-0008", "user_sun_jing",       "shipped",   "ready",    True,  True,
     "初见·简约缎面修身（香槟加急）",  "WD-P003", 10200.0,
     "南京市鼓楼区中山路1号",           "SF7001122334455",
     76.0, 56.0, 82.0, 160.0, "香槟", 3, 18, 0, 0),

    # ── 已签收/已交付 ──────────────────────────────────────────────────────
    ("WD-2025-0009", "user_chen_rong",      "delivered", "ready",    False, False,
     "仙气·多层蕾丝A型（纯白S码）",    "WD-P014", 7600.0,
     "武汉市武昌区中南路9号",            "EMS1122334455667",
     0.0, 0.0, 0.0, 160.0, "纯白", 15, 14, 5, 0),

    ("WD-2025-0010", "user_zhou_yan",       "delivered", "ready",    True,  False,
     "星河·鱼尾礼服（象牙白定制）",    "WD-P001", 12800.0,
     "天津市南开区鞍山西道99号",         "SF6677889900112",
     88.0, 68.0, 94.0, 167.0, "象牙白", 20, 30, 8, 0),

    # ── 质检完成·等待客户确认发货 ──────────────────────────────────────────
    ("WD-2025-0011", "user_wu_yue",         "confirmed", "ready",    True,  False,
     "凌波·深V低背礼服（香槟定制）",   "WD-P011", 10200.0,
     "重庆市渝中区解放碑步行街1号",      "",
     80.0, 60.0, 86.0, 165.0, "香槟", 18, 48, 0, 0),

    ("WD-2025-0012", "user_xu_pei",         "confirmed", "ready",    True,  True,
     "御风·宫廷风泡泡袖（象牙白加急）","WD-P015", 13350.0,
     "长沙市岳麓区麓山南路2号",          "",
     84.0, 65.0, 90.0, 162.0, "象牙白", 6, 22, 1, 0),

    # ── 待排产 · 刚下单 ───────────────────────────────────────────────────
    ("WD-2025-0013", "user_gao_lu",         "pending",   "pending",  True,  False,
     "霞光·渐变彩色礼服（裸粉渐变）",  "WD-P010", 13500.0,
     "北京市海淀区中关村大街1号",        "",
     79.0, 59.0, 85.0, 160.0, "象牙白渐变裸粉", 65, 1, 1, 62),

    ("WD-2025-0014", "user_lin_xia",        "pending",   "pending",  True,  False,
     "花嫁·全套婚纱套餐",              "WD-P012", 18800.0,
     "上海市浦东新区陆家嘴环路1000号",  "",
     85.0, 65.0, 91.0, 166.0, "按主婚纱颜色定制", 70, 2, 2, 62),

    ("WD-2025-0015", "user_ma_fei",         "pending",   "pending",  False, False,
     "素颜·日系轻婚纱（象牙白L码）",   "WD-P009", 4200.0,
     "厦门市思明区中山路1号",            "",
     0.0, 0.0, 0.0, 165.0, "象牙白", 30, 1, 1, 3),

    # ── 已取消 ────────────────────────────────────────────────────────────
    ("WD-2025-0016", "user_he_xin",         "cancelled", "pending",  True,  False,
     "云绒·蓬蓬公主裙（纯白定制）",    "WD-P002", 9800.0,
     "济南市历城区工业南路55号",         "",
     81.0, 61.0, 87.0, 161.0, "纯白", 0, 8, 3, 0),

    ("WD-2025-0017", "user_song_mei",       "cancelled", "cutting",  True,  False,
     "倾城·蕾丝A型裙（象牙白）",       "WD-P004", 8500.0,
     "沈阳市和平区中街路1号",            "",
     83.0, 63.0, 89.0, 163.0, "象牙白", 0, 15, 5, 0),

    # ── 已完成/历史订单 ───────────────────────────────────────────────────
    ("WD-2025-0018", "user_chen_fang",      "completed", "ready",    True,  False,
     "锦绣·刺绣秀禾服（酒红色）",      "WD-P005", 5800.0,
     "北京市朝阳区建国路88号SOHO现代城",  "SF5544332211007",
     86.0, 66.0, 92.0, 165.0, "酒红色", -30, 70, 25, 0),

    ("WD-2025-0019", "user_tang_wei",       "completed", "ready",    True,  False,
     "星河·鱼尾礼服（象牙白定制）",    "WD-P001", 12800.0,
     "北京市西城区金融街15号",           "SF9988001122334",
     82.0, 62.0, 88.0, 164.0, "象牙白", -45, 90, 40, 0),

    ("WD-2025-0020", "user_cao_ying",       "completed", "ready",    False, False,
     "素颜·日系轻婚纱（纯白M码）",     "WD-P009", 4200.0,
     "青岛市市南区香港路20号",           "YT1122003344556",
     0.0, 0.0, 0.0, 162.0, "纯白", -20, 40, 35, 0),

    # ── 加急场景 ─────────────────────────────────────────────────────────
    ("WD-2025-0021", "user_ding_chen",      "confirmed", "sewing",   True,  True,
     "初见·简约缎面修身（淡蓝加急）",  "WD-P003", 10200.0,
     "北京市朝阳区望京SOHO",            "",
     74.0, 54.0, 80.0, 158.0, "淡蓝", 18, 10, 2, 8),

    ("WD-2025-0022", "user_jiang_xia",      "confirmed", "cutting",  True,  True,
     "映月·轻纱飘逸（纯白超加急）",    "WD-P006", 14400.0,
     "上海市徐汇区漕溪北路395号",       "",
     80.0, 61.0, 86.0, 162.0, "纯白", 12, 5, 1, 10),

    # ── 退款处理中 ────────────────────────────────────────────────────────
    ("WD-2025-0023", "user_wei_qing",       "refund_processing", "sewing", True, False,
     "云绒·蓬蓬公主裙（象牙白定制）",  "WD-P002", 0.0,
     "郑州市金水区花园路1号",            "",
     82.0, 62.0, 88.0, 160.0, "象牙白", 0, 16, 1, 0),

    # ── 质量问题反馈中 ────────────────────────────────────────────────────
    ("WD-2025-0024", "user_luo_jia",        "delivered", "ready",    True,  False,
     "倾城·蕾丝A型裙（裸粉定制）",     "WD-P004", 8500.0,
     "福州市鼓楼区五四路1号",            "SF3344556677889",
     84.0, 64.0, 90.0, 164.0, "裸粉", 10, 20, 2, 0),

    ("WD-2025-0025", "user_xiong_yun",      "delivered", "ready",    False, False,
     "仙气·多层蕾丝A型（淡粉M码）",    "WD-P014", 7600.0,
     "昆明市盘龙区北京路1号",            "EMS8877665544330",
     0.0, 0.0, 0.0, 161.0, "淡粉", 14, 18, 1, 0),

    # ── 新婚纱产品线 · 试销期 ─────────────────────────────────────────────
    ("WD-2025-0026", "user_pan_ling",       "confirmed", "sewing",   True,  False,
     "珍珠链·复古赫本款（限量）",       "WD-P007", 11200.0,
     "苏州市工业园区苏州大道东1号",      "",
     78.0, 58.0, 84.0, 160.0, "象牙白+黑色腰带", 48, 25, 3, 25),

    ("WD-2025-0027", "user_feng_xiu",       "confirmed", "cutting",  True,  False,
     "澜颐·深海蓝鱼尾礼服",            "WD-P013", 11800.0,
     "宁波市鄞州区天一广场",             "",
     79.0, 59.0, 85.0, 163.0, "深海蓝", 38, 8, 2, 30),

    ("WD-2025-0028", "user_meng_juan",      "confirmed", "pending",  True,  False,
     "御风·宫廷风泡泡袖（浅驼色）",    "WD-P015", 8900.0,
     "合肥市包河区包河大道100号",        "",
     81.0, 61.0, 87.0, 160.0, "浅驼色", 58, 4, 4, 45),

    # ── 套餐订单 ─────────────────────────────────────────────────────────
    ("WD-2025-0029", "user_zhu_fang",       "confirmed", "beading",  True,  False,
     "花嫁·全套婚纱套餐（A型+秀禾）",  "WD-P012", 18800.0,
     "大连市中山区人民路1号",            "",
     85.0, 65.0, 91.0, 165.0, "象牙白主纱+大红秀禾", 30, 42, 2, 10),

    ("WD-2025-0030", "user_qian_xia",       "confirmed", "sewing",   True,  True,
     "花嫁·全套婚纱套餐（鱼尾+秀禾）","WD-P012", 28200.0,
     "青岛市崂山区海尔路1号",            "",
     83.0, 63.0, 89.0, 164.0, "香槟主纱+金红秀禾", 22, 30, 4, 12),
]

# ══════════════════════════════════════════════════════════════════════════════
# 四、客服账号（agents）
# ══════════════════════════════════════════════════════════════════════════════

AGENTS = [
    {
        "agent_id": "agent_xiaomei",
        "name": "小美",
        "status": "online",
        "role": "高级顾问",
        "specialty": "定制咨询、款式搭配",
        "note": "入职3年，擅长体型分析和个性化推荐，客户好评率98%",
    },
    {
        "agent_id": "agent_xiaoyu",
        "name": "小雨",
        "status": "online",
        "role": "售后专员",
        "specialty": "退款、质量投诉、订单修改",
        "note": "售后专员，处理投诉经验丰富，平均解决时长15分钟",
    },
    {
        "agent_id": "agent_xiaofeng",
        "name": "小峰",
        "status": "online",
        "role": "加急协调员",
        "specialty": "加急订单、生产进度、物流跟踪",
        "note": "负责加急订单协调，了解每条产线实时产能",
    },
    {
        "agent_id": "agent_supervisor",
        "name": "李主管",
        "status": "online",
        "role": "客服主管",
        "specialty": "投诉升级处理、特殊赔偿审批",
        "note": "处理一线无法解决的特殊情况，具备赔偿审批权限",
    },
    {
        "agent_id": "agent_night",
        "name": "晓璐",
        "status": "offline",
        "role": "夜班顾问",
        "specialty": "海外客户、深夜咨询",
        "note": "负责22:00-08:00值班，海外客户专项服务",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════════════════════

async def seed(clear: bool = False) -> None:
    settings = get_settings()
    dsn = settings.POSTGRES_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn=dsn)

    try:
        if clear:
            print("⚠  清空现有数据...")
            await conn.execute("DELETE FROM orders WHERE order_id LIKE 'WD-2025-%'")
            await conn.execute("DELETE FROM faq_documents WHERE metadata->>'category' IN ('product_catalog','wedding_dress_faq')")
            await conn.execute("DELETE FROM agents WHERE agent_id LIKE 'agent_%'")
            print("   完成。\n")

        # ── 1. 商品目录 ─────────────────────────────────────────────────────
        print(f"📦 写入商品目录（{len(PRODUCTS)} 条）...")
        for p in PRODUCTS:
            doc_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"product_{p['id']}"))
            content = (
                f"【商品编号：{p['id']}】{p['name']}\n"
                f"款式：{p['style']} | 参考价格：¥{p['price']:,} | 定金：¥{p['deposit']:,}\n"
                f"生产周期：{p['production_days']}天 | 加急服务：{'支持' if p['rush_available'] else '不支持'}\n"
                f"库存类型：{'现货' if p['stock_type']=='stock' else '定制'}\n"
                f"{p['desc']}\n"
                f"可选颜色：{'、'.join(p['colors'])}\n"
                f"标签：{'、'.join(p['tags'])}"
            )
            metadata = {
                "title": p["name"],
                "category": "product_catalog",
                "product_id": p["id"],
                "style": p["style"],
                "price": p["price"],
                "production_days": p["production_days"],
                "rush_available": p["rush_available"],
                "stock_type": p["stock_type"],
                "colors": p["colors"],
                "tags": p["tags"],
            }
            await conn.execute(
                """
                INSERT INTO faq_documents (doc_id, content, metadata)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (doc_id) DO UPDATE
                  SET content = EXCLUDED.content,
                      metadata = EXCLUDED.metadata,
                      updated_at = now()
                """,
                doc_id, content, json.dumps(metadata, ensure_ascii=False),
            )
            print(f"   ✓ {p['id']}  {p['name']}  ¥{p['price']:,}")

        # ── 2. FAQ 知识库（追加新条目）────────────────────────────────────
        print(f"\n📚 追加 FAQ 知识库（{len(FAQ_EXTRA)} 条）...")
        for doc in FAQ_EXTRA:
            doc_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"wedding_faq_{doc['title']}"))
            metadata = {"title": doc["title"], "category": "wedding_dress_faq"}
            await conn.execute(
                """
                INSERT INTO faq_documents (doc_id, content, metadata)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (doc_id) DO UPDATE
                  SET content = EXCLUDED.content,
                      metadata = EXCLUDED.metadata,
                      updated_at = now()
                """,
                doc_id, doc["content"], json.dumps(metadata, ensure_ascii=False),
            )
            print(f"   ✓ {doc['title']}")

        # ── 3. 订单数据 ────────────────────────────────────────────────────
        print(f"\n🛒 写入订单（{len(ORDERS)} 条）...")
        for o in ORDERS:
            (oid, uid, status, stage, is_custom, is_rush,
             item_name, product_id, price,
             addr, tracking,
             bust, waist, hips, height, color, wedding_days,
             created_ago, updated_ago, estimated_days) = o

            wedding_date = (now + timedelta(days=wedding_days)).date() if wedding_days > -200 else None
            estimated = (now + timedelta(days=estimated_days)).date() if estimated_days > 0 else None
            items_json = json.dumps([{
                "product_id": product_id,
                "name": item_name,
                "quantity": 1,
                "unit_price": price,
            }], ensure_ascii=False)
            meta_json = json.dumps({
                "dress_style": product_id,
                "color": color,
                "is_custom": is_custom,
                "bust": bust if bust else None,
                "waist": waist if waist else None,
                "hips": hips if hips else None,
                "height": height,
                "wedding_date": wedding_date.isoformat() if wedding_date else None,
                "production_stage": stage,
                "is_rush": is_rush,
                "rush_level": "standard_rush" if is_rush else "none",
                "estimated_completion": estimated.isoformat() if estimated else None,
                "alteration_notes": "",
            }, ensure_ascii=False)

            await conn.execute(
                """
                INSERT INTO orders (
                    order_id, user_id, status, items, total,
                    shipping_address, tracking_number,
                    is_custom, is_rush, production_stage,
                    wedding_date, wedding_metadata,
                    created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4::jsonb, $5,
                    $6, $7,
                    $8, $9, $10,
                    $11, $12::jsonb,
                    $13, $14
                )
                ON CONFLICT (order_id) DO UPDATE
                  SET status = EXCLUDED.status,
                      production_stage = EXCLUDED.production_stage,
                      wedding_metadata = EXCLUDED.wedding_metadata,
                      updated_at = EXCLUDED.updated_at
                """,
                oid, uid, status, items_json, price,
                addr, tracking,
                is_custom, is_rush, stage,
                wedding_date, meta_json,
                _d(created_ago), _d(updated_ago),
            )
            print(f"   ✓ {oid} | {uid:20s} | {status:22s} | {stage:10s} | {item_name[:22]}...")

        # ── 4. 客服账号 ────────────────────────────────────────────────────
        print(f"\n👤 写入客服账号（{len(AGENTS)} 条）...")
        for a in AGENTS:
            await conn.execute(
                """
                INSERT INTO agents (agent_id, name, status, created_at, updated_at)
                VALUES ($1, $2, $3, NOW(), NOW())
                ON CONFLICT (agent_id) DO UPDATE
                  SET name = EXCLUDED.name,
                      status = EXCLUDED.status,
                      updated_at = NOW()
                """,
                a["agent_id"], a["name"], a["status"],
            )
            print(f"   ✓ {a['agent_id']:20s} | {a['name']:6s} | {a['status']:8s} | {a['role']}")

        # ── 汇总 ────────────────────────────────────────────────────────────
        total_docs = await conn.fetchval("SELECT COUNT(*) FROM faq_documents")
        total_orders = await conn.fetchval("SELECT COUNT(*) FROM orders")
        total_agents = await conn.fetchval("SELECT COUNT(*) FROM agents")

        print(f"""
╔══════════════════════════════════════════════════════╗
║          缘梦婚纱 · 运营数据初始化完成               ║
╠══════════════════════════════════════════════════════╣
║  知识库文档（含商品+FAQ）：{total_docs:>4} 条              ║
║  订单数据：                {total_orders:>4} 条              ║
║  客服账号：                {total_agents:>4} 条              ║
╠══════════════════════════════════════════════════════╣
║  测试用户-订单速查表：                               ║
║  user_chen_fang   → WD-2025-0001（缝制中）           ║
║  user_liu_xin     → WD-2025-0002（剪裁中）           ║
║  user_zhang_hui   → WD-2025-0003（珠绣·加急）        ║
║  user_wang_min    → WD-2025-0004（质检中）           ║
║  user_zhao_lei    → WD-2025-0005（制作完成待发）      ║
║  user_li_mei      → WD-2025-0006（已发货）           ║
║  user_luo_jia     → WD-2025-0024（质量投诉中）       ║
║  user_wei_qing    → WD-2025-0023（退款处理中）       ║
╚══════════════════════════════════════════════════════╝
""")

    finally:
        await conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true", help="先清空现有数据再写入")
    args = parser.parse_args()
    asyncio.run(seed(clear=args.clear))
