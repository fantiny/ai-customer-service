#!/usr/bin/env python3
"""Database migration script — idempotent, safe to run multiple times.

    python scripts/migrate_db.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import asyncpg

from ai_customer_service.infrastructure.config import get_settings

DDL = """
-- pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ── FAQ knowledge base ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS faq_documents (
    doc_id         TEXT PRIMARY KEY,
    content        TEXT NOT NULL,
    metadata       JSONB DEFAULT '{}',
    -- Knowledge type controls retrieval reliability:
    --   business_policy  = authoritative rules (strict: no LLM fabrication)
    --   industry_knowledge = general knowledge (LLM may supplement)
    knowledge_type TEXT NOT NULL DEFAULT 'industry_knowledge'
                   CHECK (knowledge_type IN ('business_policy', 'industry_knowledge')),
    embedding      vector(1536),
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS faq_documents_embedding_idx
    ON faq_documents USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ── Wedding dress orders ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
    order_id         TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    items            JSONB NOT NULL DEFAULT '[]',
    total            NUMERIC(10, 2) NOT NULL DEFAULT 0,
    shipping_address TEXT DEFAULT '',
    tracking_number  TEXT DEFAULT '',
    -- Wedding-specific columns
    is_custom        BOOLEAN DEFAULT false,
    is_rush          BOOLEAN DEFAULT false,
    production_stage TEXT DEFAULT 'pending',
    wedding_date     DATE,
    wedding_metadata JSONB DEFAULT '{}',
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS orders_user_id_idx ON orders (user_id);
CREATE INDEX IF NOT EXISTS orders_status_idx  ON orders (status);
CREATE INDEX IF NOT EXISTS orders_wedding_date_idx ON orders (wedding_date);

-- ── Workspace / Ticketing tables ─────────────────────────────────────────

-- Persistent workspace session records (replaces in-memory WorkspaceSessionManager)
CREATE TABLE IF NOT EXISTS workspace_sessions (
    session_id          TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    thread_id           TEXT NOT NULL,
    mode                TEXT NOT NULL DEFAULT 'ai',
    escalation_reason   TEXT,
    assigned_agent_id   TEXT,
    pending_action      JSONB DEFAULT '{}',
    order_context       JSONB DEFAULT '{}',
    history             JSONB NOT NULL DEFAULT '[]',
    first_response_at   TIMESTAMPTZ,
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ws_sessions_user_idx ON workspace_sessions (user_id);
CREATE INDEX IF NOT EXISTS ws_sessions_mode_idx ON workspace_sessions (mode);

-- Customer service tickets (1-to-1 with sessions initially)
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id               TEXT PRIMARY KEY,
    session_id              TEXT NOT NULL REFERENCES workspace_sessions(session_id),
    user_id                 TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'open',
    category                TEXT,
    assigned_agent_id       TEXT,
    tags                    TEXT[] DEFAULT '{}',
    summary                 TEXT,
    resolution              TEXT,
    sentiment               TEXT,
    sla_deadline            TIMESTAMPTZ,
    resolved_at             TIMESTAMPTZ,
    -- CSAT rating (1-5)
    rating                  INT CHECK (rating BETWEEN 1 AND 5),
    -- Structured close-report fields (queryable without JSON parsing)
    report_resolution_type  TEXT,
    report_sentiment_start  TEXT,
    report_key_issues       TEXT[] DEFAULT '{}',
    report_ai_quality       TEXT,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS tickets_session_idx ON tickets (session_id);
CREATE INDEX IF NOT EXISTS tickets_status_idx  ON tickets (status);
CREATE INDEX IF NOT EXISTS tickets_agent_idx   ON tickets (assigned_agent_id);

-- Customer service agents
CREATE TABLE IF NOT EXISTS agents (
    agent_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'offline',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Immutable audit log of session/ticket status transitions
CREATE TABLE IF NOT EXISTS status_events (
    event_id    TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    ticket_id   TEXT,
    from_status TEXT NOT NULL,
    to_status   TEXT NOT NULL,
    actor       TEXT NOT NULL,
    note        TEXT,
    occurred_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS status_events_session_idx ON status_events (session_id);
CREATE INDEX IF NOT EXISTS status_events_time_idx    ON status_events (occurred_at);

-- ── Products catalog ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    product_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    style           TEXT NOT NULL,
    price           NUMERIC(10,2) NOT NULL,
    deposit_rate    NUMERIC(4,3) NOT NULL DEFAULT 0.30,
    production_days INTEGER NOT NULL,
    rush_available  BOOLEAN NOT NULL DEFAULT false,
    stock_type      TEXT NOT NULL DEFAULT 'custom',
    colors          TEXT[] NOT NULL DEFAULT '{}',
    tags            TEXT[] NOT NULL DEFAULT '{}',
    description     TEXT NOT NULL DEFAULT '',
    occasions       TEXT[] NOT NULL DEFAULT '{}',
    active          BOOLEAN NOT NULL DEFAULT true,
    purchase_url    TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS products_style_idx ON products(style);
CREATE INDEX IF NOT EXISTS products_price_idx ON products(price);

-- Business rules configuration (dynamic, no code deploy needed)
CREATE TABLE IF NOT EXISTS business_rules (
    rule_key    TEXT PRIMARY KEY,
    rule_value  JSONB NOT NULL,
    description TEXT,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Prompt version management (hot-swap node prompts without redeploy)
CREATE TABLE IF NOT EXISTS node_prompts (
    prompt_id   TEXT PRIMARY KEY,
    node_name   TEXT NOT NULL,
    version     INT NOT NULL DEFAULT 1,
    content     TEXT NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS node_prompts_active_idx
    ON node_prompts (node_name) WHERE active = true;

-- ── Session messages — canonical per-message audit store ─────────────────────
-- Every message (user / bot / agent / system) gets its own row.
-- workspace_sessions.history is the hot-cache; this table is the queryable truth.
CREATE TABLE IF NOT EXISTS session_messages (
    message_id   TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    ticket_id    TEXT,
    role         TEXT NOT NULL,           -- user | bot | agent | system
    content      TEXT NOT NULL,
    agent_id     TEXT,                    -- populated when role = 'agent'
    node_name    TEXT,                    -- LangGraph node that generated this reply
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS sm_session_idx ON session_messages (session_id);
CREATE INDEX IF NOT EXISTS sm_created_idx ON session_messages (created_at DESC);
CREATE INDEX IF NOT EXISTS sm_role_idx    ON session_messages (role);
CREATE INDEX IF NOT EXISTS sm_ticket_idx  ON session_messages (ticket_id);

-- Daily operational digest snapshots
CREATE TABLE IF NOT EXISTS daily_digests (
    digest_id   TEXT PRIMARY KEY,
    report_date DATE NOT NULL UNIQUE,
    metrics     JSONB NOT NULL,
    summary_md  TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS digests_date_idx ON daily_digests (report_date DESC);

-- ── Business profile tables (generic framework) ──────────────────────────────

-- One row per business / tenant
CREATE TABLE IF NOT EXISTS business_profiles (
    business_id         TEXT PRIMARY KEY,
    business_name       TEXT NOT NULL,
    business_type       TEXT NOT NULL DEFAULT 'ecommerce',

    -- Feature flags
    order_enabled       BOOLEAN NOT NULL DEFAULT true,
    product_enabled     BOOLEAN NOT NULL DEFAULT true,
    faq_enabled         BOOLEAN NOT NULL DEFAULT true,
    aftersales_enabled  BOOLEAN NOT NULL DEFAULT true,

    -- Safety config (SafetyConfig serialised as JSONB)
    -- { "escalation_keywords": [...], "max_input_length": 2000,
    --   "escalation_thresholds": {"aftersales": 3, "general": 4},
    --   "urgent_escalation_threshold": 2 }
    safety_config       JSONB NOT NULL DEFAULT '{}',

    -- Urgency config (UrgencyConfig serialised as JSONB)
    -- { "enabled": true, "deadline_field": "wedding_date", "urgent_days_threshold": 14 }
    urgency_config      JSONB NOT NULL DEFAULT '{}',

    -- Contact config (ContactConfig serialised as JSONB)
    -- { "hotline": "400-520-5201", "website": "", "email": "" }
    contact_config      JSONB NOT NULL DEFAULT '{}',

    -- Handoff config (HandoffConfig serialised as JSONB)
    -- { "notify_customer": true, "notification_template": "...", "handoff_language": null }
    handoff_config      JSONB NOT NULL DEFAULT '{}',

    -- Document category tags scoping retrieval to this business's documents
    faq_category             TEXT NOT NULL DEFAULT 'wedding_dress_faq',
    product_catalog_category TEXT NOT NULL DEFAULT 'product_catalog',

    -- Fallback intent id when router confidence is low
    fallback_intent_id  TEXT NOT NULL DEFAULT 'general',

    active              BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- One row per intent per business
CREATE TABLE IF NOT EXISTS business_intents (
    intent_id                TEXT NOT NULL,
    business_id              TEXT NOT NULL REFERENCES business_profiles(business_id) ON DELETE CASCADE,
    display_name             TEXT NOT NULL,
    -- Plain-language description fed to the router LLM to explain when to route here
    description              TEXT NOT NULL DEFAULT '',
    -- Name of the handler node function registered in _BUILTIN_NODE_REGISTRY
    handler_node             TEXT NOT NULL,
    requires_confirmation    BOOLEAN NOT NULL DEFAULT false,
    -- True for multi-turn nodes (order_read/write) so safety_check can bypass router
    is_continuation_node     BOOLEAN NOT NULL DEFAULT false,
    -- Per-intent negative-turn threshold (NULL = use safety_config default)
    negative_turns_threshold INTEGER,
    sort_order               INTEGER NOT NULL DEFAULT 0,
    active                   BOOLEAN NOT NULL DEFAULT true,
    created_at               TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (intent_id, business_id)
);

CREATE INDEX IF NOT EXISTS business_intents_business_idx
    ON business_intents (business_id);
CREATE INDEX IF NOT EXISTS business_intents_active_idx
    ON business_intents (business_id, active);

-- ── Business workflows — structured service flow definitions ─────────────────
-- Each workflow maps to a trigger intent and contains ordered steps.
-- Used by aftersales_node, general_node, and future workflow-aware nodes
-- to guide AI responses with configurable, operator-defined scripts.
CREATE TABLE IF NOT EXISTS business_workflows (
    workflow_id      TEXT NOT NULL,
    business_id      TEXT NOT NULL REFERENCES business_profiles(business_id) ON DELETE CASCADE,
    display_name     TEXT NOT NULL,
    -- Intent that triggers this workflow (matches business_intents.intent_id)
    trigger_intent   TEXT NOT NULL,
    -- Optional keywords for additional matching within the intent
    trigger_keywords TEXT[] NOT NULL DEFAULT '{}',
    -- Ordered steps: [{step: 1, instruction: "...", action: null, condition: null}]
    steps            JSONB NOT NULL DEFAULT '[]',
    is_active        BOOLEAN NOT NULL DEFAULT true,
    sort_order       INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (workflow_id, business_id)
);

CREATE INDEX IF NOT EXISTS business_workflows_business_idx
    ON business_workflows (business_id);
CREATE INDEX IF NOT EXISTS business_workflows_intent_idx
    ON business_workflows (business_id, trigger_intent);
"""

# Tables removed from the schema — drop on migration to keep DB clean
DROP_STMTS = [
    "DROP TABLE IF EXISTS conversations CASCADE",
]

# ALTER statements for columns added after initial table creation.
# All use IF NOT EXISTS semantics — safe to re-run.
ALTER_STMTS = [
    # faq_documents: knowledge_type column (added in Phase 6)
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'faq_documents' AND column_name = 'knowledge_type'
        ) THEN
            ALTER TABLE faq_documents
                ADD COLUMN knowledge_type TEXT NOT NULL DEFAULT 'industry_knowledge'
                CHECK (knowledge_type IN ('business_policy', 'industry_knowledge'));
        END IF;
    END $$;
    """,
    # business_profiles: handoff_config column (added in Phase 6)
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'business_profiles' AND column_name = 'handoff_config'
        ) THEN
            ALTER TABLE business_profiles
                ADD COLUMN handoff_config JSONB NOT NULL DEFAULT '{}';
        END IF;
    END $$;
    """,
    # business_profiles: document category fields (added to support multi-business retrieval)
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'business_profiles' AND column_name = 'faq_category'
        ) THEN
            ALTER TABLE business_profiles
                ADD COLUMN faq_category TEXT NOT NULL DEFAULT 'wedding_dress_faq';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'business_profiles' AND column_name = 'product_catalog_category'
        ) THEN
            ALTER TABLE business_profiles
                ADD COLUMN product_catalog_category TEXT NOT NULL DEFAULT 'product_catalog';
        END IF;
    END $$;
    """,
    # products: purchase_url column (added to store official store link, preventing LLM hallucination)
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'products' AND column_name = 'purchase_url'
        ) THEN
            ALTER TABLE products
                ADD COLUMN purchase_url TEXT NOT NULL DEFAULT '';
        END IF;
    END $$;
    """,
]


DEFAULT_BUSINESS_RULES = [
    ("sla_hitl_minutes",           "2",    "HITL 等待超时提醒（分钟）"),
    ("sla_human_response_minutes", "5",    "人工接管后首次回复超时提醒（分钟）"),
    ("sla_resolve_hours",          "24",   "工单最长未结单超时提醒（小时）"),
    ("refund_rate.pending",        "1.00", "待排产阶段退款比例（下单未开始裁剪：全额退款）"),
    ("refund_rate.confirmed",      "1.00", "已确认阶段退款比例（确认但未开始裁剪：全额退款）"),
    ("refund_rate.cutting",        "0.70", "剪裁阶段退款比例（裁剪中：退70%）"),
    ("refund_rate.sewing",         "0.30", "缝制阶段退款比例（缝制中：退30%）"),
    ("refund_rate.beading",        "0.00", "珠绣阶段退款比例（珠绣/后期：不退款）"),
    ("refund_rate.qc",             "0.00", "质检阶段退款比例（质检中：不退款）"),
    ("refund_rate.ready",          "0.00", "完成阶段退款比例（成品完成：不退款）"),
    ("hitl_required_actions",      '["cancel_order","initiate_refund","exchange_order","request_rush"]', "需要 HITL 审批的操作列表"),
    ("hitl_auto_timeout_minutes",  "10",    "HITL 无响应后自动拒绝超时（分钟）"),
    ("default_language",           '"zh-CN"', "客服默认回复语言（可选值：zh-CN / en / ja / ko / th 等）"),
    ("rush_fee_rate.standard_rush", "0.50",  "加急制作费率（标准）"),
    ("rush_fee_rate.super_rush",    "1.00",  "加急制作费率（特急）"),
    ("rush_days.standard_rush",     "30",    "加急制作天数（标准）"),
    ("rush_days.super_rush",        "15",    "加急制作天数（特急）"),
    # Proactive hints in order_read_node (keyed by production_stage value)
    ("proactive_hint.pending",  '"📌 婚纱还在排产/裁剪阶段，如需加急请告知，可申请加急制作（详情请问客服）。"', "备料/排产阶段的主动建议"),
    ("proactive_hint.cutting",  '"📌 婚纱正在裁剪阶段，如需加急请联系我们申请。"', "裁剪阶段的主动建议"),
    ("proactive_hint.confirmed",'"📌 订单已确认，即将进入生产。如婚期临近可申请加急。"', "已确认阶段的主动建议"),
    # Handoff messages shown to customer when AI cannot reliably answer (Phase 6)
    ("handoff.policy_no_doc",        '"关于这个政策问题，我来帮您连线专属顾问确认，这样给您最准确的答复～"', "无政策文档时转人工话术"),
    ("handoff.product_unavailable",  '"商品查询这块我帮您连线专属顾问，他们能给您最准确的介绍～"', "商品服务不可用时转人工话术"),
    # Handoff suggestions shown to human agent in workspace (Phase 6)
    ("handoff.suggestion.policy_no_doc",       '"请核实相关政策并告知客户具体条款，建议查阅内部政策手册"', "政策无文档交接建议"),
    ("handoff.suggestion.product_unavailable", '"请为客户介绍符合需求的商品，重点了解款式偏好和预算范围"', "商品不可用交接建议"),
]


# ── Wedding-dress business profile seed data ─────────────────────────────────

_WEDDING_DRESS_SAFETY_CONFIG = {
    "escalation_keywords": [
        "转人工", "找人工", "人工客服", "人工服务", "真人客服", "真人",
        "要投诉", "我要投诉", "联系客服",
        "call.*agent", "speak.*human", "talk.*person",
    ],
    "max_input_length": 2000,
    "escalation_thresholds": {"aftersales": 3, "general": 4},
    "urgent_escalation_threshold": 2,
}

_WEDDING_DRESS_URGENCY_CONFIG = {
    "enabled": True,
    "deadline_field": "wedding_date",
    "urgent_days_threshold": 14,
}

_WEDDING_DRESS_CONTACT_CONFIG = {
    "hotline": "400-520-5201",
    "website": "",
    "email": "",
}

_WEDDING_DRESS_HANDOFF_CONFIG = {
    "notify_customer": True,
    "notification_template": "关于这个问题我帮您连线专属顾问，稍等一下～",
    "silent_handoff_message": "",
    "handoff_language": None,
}

_WEDDING_DRESS_WORKFLOWS = [
    # (workflow_id, display_name, trigger_intent, trigger_keywords, steps)
    (
        "return_process",
        "退货流程",
        "aftersales",
        ["退货", "退款申请", "申请退货"],
        [
            {"step": 1, "instruction": "先表达理解和歉意，询问客户订单号和退货原因", "action": None},
            {"step": 2, "instruction": "确认订单状态是否符合退货条件（查询 order_write_node 预验证）", "action": "validate_refund"},
            {"step": 3, "instruction": "告知退款比例和流程，引导客户通过 order_write_node 提交正式申请", "action": None},
        ],
    ),
    (
        "exchange_process",
        "换货流程",
        "aftersales",
        ["换货", "尺寸不合", "颜色不对", "做工问题"],
        [
            {"step": 1, "instruction": "表达理解，请客户描述具体问题（尺寸/颜色/做工），并询问订单号", "action": None},
            {"step": 2, "instruction": "记录问题描述，告知换货标准和审核流程（一般需 3-5 个工作日）", "action": None},
            {"step": 3, "instruction": "为客户创建售后工单，提供工单号，告知专属顾问会主动联系", "action": "create_ticket"},
        ],
    ),
    (
        "complaint_process",
        "投诉处理流程",
        "aftersales",
        ["投诉", "不满意", "差评", "要找老板"],
        [
            {"step": 1, "instruction": "首先真诚道歉，让客户感受到被重视，不要急于解释", "action": None},
            {"step": 2, "instruction": "耐心倾听完整投诉内容，记录关键问题点，不打断", "action": None},
            {"step": 3, "instruction": "告知客户投诉已受理，提供投诉编号，承诺 24 小时内给出处理方案", "action": "create_ticket"},
        ],
    ),
]

_WEDDING_DRESS_INTENTS = [
    # (intent_id, display_name, description, handler_node, requires_confirmation, is_continuation_node, sort_order)
    ("product",     "商品咨询", "用户咨询具体商品或想要推荐婚纱款式、价格、面料、颜色等",                         "product_node",    False, False, 1),
    ("faq",         "政策咨询", "用户咨询通用政策：退换货、量体流程、定制说明、配送物流、门店等",                    "faq_node",        False, False, 2),
    ("order_read",  "订单查询", "用户要查询某笔订单的信息（只读操作，如状态、进度、物流单号）",                       "order_read_node", False, True,  3),
    ("order_write", "订单操作", "用户要对已有订单执行写操作：取消订单、申请退款、申请加急制作",                       "order_write_node",True,  True,  4),
    ("aftersales",         "售后投诉", "用户反映商品质量问题或对服务不满，包括尺寸不符、颜色差异、做工瑕疵等",               "aftersales_node",         False, False, 5),
    ("general",            "通用对话", "问候、感谢、闲聊、超出业务范围的话题，或无法明确归类的消息",                         "general_node",            False, False, 6),
    ("measurement_guide",  "量体引导", "引导客户完成定制婚纱量体数据收集（身高、胸围、腰围、臀围）",                       "measurement_guide_node",  False, True,  7),
]


async def run_migrations() -> None:
    import json

    settings = get_settings()
    dsn = settings.POSTGRES_URL.replace("postgresql+asyncpg://", "postgresql://")
    print(f"Connecting to: {dsn.split('@')[-1]}")

    conn = await asyncpg.connect(dsn=dsn)
    try:
        # Drop obsolete tables first (idempotent)
        for stmt in DROP_STMTS:
            await conn.execute(stmt)

        await conn.execute(DDL)

        # Apply column additions for existing tables (idempotent)
        for stmt in ALTER_STMTS:
            await conn.execute(stmt)

        # ── Seed default business rules ───────────────────────────────────
        for key, value, description in DEFAULT_BUSINESS_RULES:
            await conn.execute(
                """
                INSERT INTO business_rules (rule_key, rule_value, description)
                VALUES ($1, $2::jsonb, $3)
                ON CONFLICT (rule_key) DO NOTHING
                """,
                key, value, description,
            )

        # ── Seed wedding-dress business profile ───────────────────────────
        await conn.execute(
            """
            INSERT INTO business_profiles
                (business_id, business_name, business_type,
                 safety_config, urgency_config, contact_config, handoff_config,
                 fallback_intent_id)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7::jsonb, $8)
            ON CONFLICT (business_id) DO UPDATE
                SET handoff_config = EXCLUDED.handoff_config,
                    updated_at = NOW()
            """,
            "wedding_dress",
            "缘梦婚纱",
            "ecommerce",
            json.dumps(_WEDDING_DRESS_SAFETY_CONFIG, ensure_ascii=False),
            json.dumps(_WEDDING_DRESS_URGENCY_CONFIG, ensure_ascii=False),
            json.dumps(_WEDDING_DRESS_CONTACT_CONFIG, ensure_ascii=False),
            json.dumps(_WEDDING_DRESS_HANDOFF_CONFIG, ensure_ascii=False),
            "general",
        )

        for (intent_id, display_name, description, handler_node,
             requires_confirmation, is_continuation_node, sort_order) in _WEDDING_DRESS_INTENTS:
            await conn.execute(
                """
                INSERT INTO business_intents
                    (intent_id, business_id, display_name, description, handler_node,
                     requires_confirmation, is_continuation_node, sort_order)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (intent_id, business_id) DO NOTHING
                """,
                intent_id, "wedding_dress", display_name, description, handler_node,
                requires_confirmation, is_continuation_node, sort_order,
            )

        # ── Seed wedding-dress workflows ───────────────────────────────────
        for (wf_id, wf_name, trigger_intent, keywords, steps) in _WEDDING_DRESS_WORKFLOWS:
            await conn.execute(
                """
                INSERT INTO business_workflows
                    (workflow_id, business_id, display_name, trigger_intent,
                     trigger_keywords, steps)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                ON CONFLICT (workflow_id, business_id) DO NOTHING
                """,
                wf_id, "wedding_dress", wf_name, trigger_intent,
                keywords,
                json.dumps(steps, ensure_ascii=False),
            )

        # ── Seed business_policy FAQ documents ────────────────────────────────
        # These documents trigger strict mode in faq_node: LLM must answer ONLY
        # from the document text, no supplementing allowed.
        _POLICY_DOCS = [
            (
                "定制婚纱取消与退款政策",
                "wedding_dress_faq",
                # Single canonical policy replacing the two contradictory docs.
                # Refund rates must EXACTLY match the refund_rate.* business rules in DB.
                "定制婚纱取消与退款规则（按制作阶段）：\n"
                "- 待排产 / 已确认（裁剪未开始）：全额退款（100%）\n"
                "- 裁剪阶段（裁剪已开始）：退款70%（面料已裁剪，扣除材料及开料费）\n"
                "- 缝制阶段（缝制进行中）：退款30%（人工成本已发生）\n"
                "- 珠绣 / 质检 / 成品完成阶段：不予退款\n"
                "- 已发货或签收后：不予退款\n\n"
                "非定制成衣退货：签收后7天内可申请退货，须保持原标签和包装完好、无穿着痕迹，退全款。\n\n"
                "质量问题：因我方质量问题（破损、做工瑕疵、与描述不符）退货，全额退款，运费由我方承担。\n\n"
                "退款到账：确认退款后3-5个工作日原路退回，节假日顺延。\n\n"
                "申请方式：联系专属顾问或拨打热线400-520-5201。",
            ),
            (
                "换货政策",
                "wedding_dress_faq",
                "换货条件：收货7天内发现以下情况可申请换货：尺码与订单不符、面料/款式与订单描述不一致、存在做工瑕疵（线头、破损、污渍）。\n"
                "换货流程：联系客服说明问题并上传照片→客服审核（1个工作日）→审核通过后寄回→收到退回件后7日内发出换货商品。\n"
                "注意：定制婚纱因客户个人原因不支持换货（尺码按客户提供数据制作，误差±2cm属正常范围）。\n"
                "运费：质量/发错问题换货运费由我方承担；客户个人原因换货（如改变心意）运费自理。",
            ),
            (
                "质量保障条款",
                "wedding_dress_faq",
                "做工保障：所有婚纱出厂前经过三道质检。保障范围：线迹均匀无跳针、拉链顺滑无卡顿、无明显色差（同一批次）、装饰品（珠片/蕾丝）粘接牢固。\n"
                "质保期限：签收后30天内发现质量问题（非人为损坏）免费修复或换货。\n"
                "修复服务：签收30天后、180天内发现问题可申请付费修复，工本费根据问题类型报价。\n"
                "不在质保范围：人为撕裂、烧焦、洗涤不当导致变形、穿着磨损。",
            ),
            (
                "发货与交货期保障",
                "wedding_dress_faq",
                "标准交期：现货商品3个工作日内发货；定制婚纱标准交期45-60天（自确认订单、收到首付款之日起）。\n"
                "加急交期：标准加急30天交货（+50%加急费）；特急加急15天交货（+100%加急费），需提前确认可行性。\n"
                "延误赔偿：因我方原因导致超出承诺交货日，每延误1天赔偿订单金额0.5%，最高赔付5%。客户原因（如尺寸信息延迟提供）导致延误不赔偿。\n"
                "物流：默认顺丰快递，签收后请当面验货并拍照存证。",
            ),
        ]
        # Build embedding client (same config as the main application).
        # Embeddings are a hard requirement for business_policy docs —
        # without them, vector search cannot find them and retrieval silently
        # degrades. We fail fast here rather than leaving docs without embeddings.
        settings = get_settings()
        from ai_customer_service.adapters.llm.factory import LLMFactory
        from ai_customer_service.adapters.llm.embedding_client import LangChainEmbeddingClient
        embedding_client = LangChainEmbeddingClient(LLMFactory.build_embedding_client(settings))

        inserted = 0
        for title, category, content in _POLICY_DOCS:
            # Idempotent: skip if a business_policy doc with the same title already exists
            existing = await conn.fetchval(
                "SELECT 1 FROM faq_documents WHERE knowledge_type='business_policy' AND metadata->>'title'=$1",
                title,
            )
            if existing:
                print(f"  · '{title}' already exists, skipping.")
                continue

            # Generate embedding BEFORE inserting — fail fast if API is unavailable.
            # business_policy docs without embeddings are invisible to vector search.
            try:
                vector = await embedding_client.aembed_query(content)
            except Exception as exc:
                raise RuntimeError(
                    f"Cannot generate embedding for '{title}': {exc}\n"
                    "business_policy documents require embeddings to be discoverable. "
                    "Ensure the embedding API is reachable and has sufficient balance."
                ) from exc

            vector_str = "[" + ",".join(str(v) for v in vector) + "]"
            metadata = json.dumps({"title": title, "category": category}, ensure_ascii=False)
            await conn.execute(
                """
                INSERT INTO faq_documents
                    (doc_id, content, metadata, knowledge_type, embedding, created_at, updated_at)
                VALUES (gen_random_uuid()::text, $1, $2::jsonb, 'business_policy', $3::vector, NOW(), NOW())
                """,
                content,
                metadata,
                vector_str,
            )
            inserted += 1
            print(f"  ✓ Inserted '{title}' with embedding.")

        if inserted == 0 and len(_POLICY_DOCS) > 0:
            print("  · All business_policy FAQ documents already present.")

        print("✓ Migrations applied successfully.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
