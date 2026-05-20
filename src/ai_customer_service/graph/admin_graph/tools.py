"""Admin tools for the AI-Native configuration agent.

Each tool is a closure that captures repository dependencies injected at
startup. Tools are designed for safe idempotent operations — admin can call
them freely without risk of data corruption.

Available tools:
  list_current_config    — read all rules + profile summary + node prompt list
  upsert_business_rule   — set a business_rules key/value pair
  delete_business_rule   — remove a rule key
  list_faq_documents     — list knowledge-base documents (optionally filtered)
  create_faq_document    — add a new FAQ/policy document (no embedding — use embed-all API)
  update_faq_document    — update content of an existing document (clears embedding)
  preview_prompt         — show the current active prompt for a graph node
  publish_prompt         — publish a new prompt version for a node
  get_system_metrics     — counts + health snapshot of the system data
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.tools import tool


def build_admin_tools(
    rules_repo: Any,
    faq_doc_repo: Any,
    prompt_repo: Any,
    db_pool: Any,
    business_profile: Any,
) -> list:
    """Return a list of LangChain tools bound to the given repositories."""

    # ── Config reads ──────────────────────────────────────────────────────────

    @tool
    async def list_current_config() -> str:
        """列出系统当前所有配置：业务规则（business rules）、商户档案摘要、节点提示词列表。

        适合在开始配置前了解系统现状，或向管理员展示当前生效的设置。
        """
        rules = await rules_repo.get_all()
        nodes_with_prompts = await prompt_repo.list_nodes()
        profile_summary = {
            "business_id": getattr(business_profile, "business_id", "unknown"),
            "business_name": getattr(business_profile, "business_name", "unknown"),
            "intents": [
                getattr(i, "intent_id", str(i))
                for i in getattr(business_profile, "intents", [])
            ],
        }
        result = {
            "business_profile": profile_summary,
            "business_rules": rules,
            "nodes_with_custom_prompts": nodes_with_prompts,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ── Business rules ────────────────────────────────────────────────────────

    @tool
    async def upsert_business_rule(key: str, value: str, description: str = "") -> str:
        """设置或更新一条业务规则（business_rules 表）。

        Args:
            key: 规则键名，例如 "handoff.policy_no_doc" 或 "sla.hitl_minutes"
            value: 规则值（字符串）。数字类型请传字符串，例如 "10"
            description: 可选，规则说明（方便人工理解该规则用途）

        规则键命名约定：
          handoff.*     — 转人工相关话术/行为
          sla.*         — SLA 阈值（分钟/小时）
          proactive_hint.* — 主动提示文案（按状态）
          default_language  — 默认对话语言 (zh / en)
        """
        await rules_repo.set(key, value, description or None)
        return f"规则已更新：{key} = {value!r}"

    @tool
    async def delete_business_rule(key: str) -> str:
        """删除一条业务规则。删除后系统将使用代码中的默认值。

        Args:
            key: 要删除的规则键名
        """
        # Check existence first
        current = await rules_repo.get(key)
        if current is None:
            return f"规则 '{key}' 不存在"
        await rules_repo.delete(key)  # also writes audit log + invalidates cache
        return f"规则 '{key}' 已删除"

    # ── Knowledge base ────────────────────────────────────────────────────────

    @tool
    async def list_faq_documents(knowledge_type: str = "all") -> str:
        """列出知识库中的文档。

        Args:
            knowledge_type: 筛选类型。"all"（全部）、"business_policy"（业务政策）、
                            "industry_knowledge"（行业知识）
        """
        docs = await faq_doc_repo.list_all()
        if knowledge_type != "all":
            docs = [d for d in docs if d.knowledge_type == knowledge_type]
        result = [
            {
                "doc_id": d.doc_id,
                "title": d.title,
                "category": d.category,
                "knowledge_type": d.knowledge_type,
                "has_embedding": d.has_embedding,
                "preview": d.content[:80] + "…" if len(d.content) > 80 else d.content,
            }
            for d in docs
        ]
        total = len(result)
        return json.dumps({"total": total, "documents": result}, ensure_ascii=False, indent=2)

    @tool
    async def create_faq_document(
        title: str,
        content: str,
        knowledge_type: str = "industry_knowledge",
        category: str = "wedding_dress_faq",
    ) -> str:
        """在知识库中创建一篇新文档。

        创建后文档没有向量嵌入（embedding）。要让它被检索系统发现，需要之后调用
        embed-all API（POST /api/workspace/admin/knowledge/embed-all）生成嵌入。

        Args:
            title: 文档标题，例如 "退货政策"
            content: 文档正文（支持多段落，建议包含具体条款和数字）
            knowledge_type: "industry_knowledge"（行业通用知识，LLM 可补充）或
                            "business_policy"（业务政策，严格基于文档，不允许 LLM 补充）
            category: 检索类别，默认 "wedding_dress_faq"（婚纱 FAQ 检索池）
        """
        if knowledge_type not in ("industry_knowledge", "business_policy"):
            return f"错误：knowledge_type 必须是 'industry_knowledge' 或 'business_policy'，收到 '{knowledge_type}'"

        doc = await faq_doc_repo.create(content=content, title=title, category=category)
        # Also write knowledge_type (create() doesn't expose it yet)
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE faq_documents SET knowledge_type = $1 WHERE doc_id = $2",
                knowledge_type, doc.doc_id,
            )
        return (
            f"文档已创建：doc_id={doc.doc_id}，标题={title!r}，"
            f"类型={knowledge_type}，类别={category}。\n"
            "注意：尚未生成向量嵌入，请调用 embed-all API 使其可被检索。"
        )

    @tool
    async def update_faq_document(doc_id: str, title: str, content: str) -> str:
        """更新一篇现有知识库文档的标题和内容。

        更新后原来的向量嵌入会被清除，需要重新调用 embed-all API 生成嵌入。

        Args:
            doc_id: 文档 ID（可通过 list_faq_documents 查询）
            title: 新标题
            content: 新正文
        """
        doc = await faq_doc_repo.get(doc_id)
        if not doc:
            return f"错误：文档 {doc_id!r} 不存在"
        updated = await faq_doc_repo.update(doc_id=doc_id, content=content, title=title, category=doc.category)
        if not updated:
            return f"更新失败：文档 {doc_id!r} 不存在或已被删除"
        return (
            f"文档已更新：doc_id={doc_id}，标题={title!r}。\n"
            "向量嵌入已清除，请调用 embed-all API 重新生成。"
        )

    # ── Prompts ───────────────────────────────────────────────────────────────

    @tool
    async def preview_prompt(node_name: str) -> str:
        """查看某个图节点当前生效的自定义提示词（prompt）。

        如果该节点没有自定义提示词，返回"使用代码默认提示词"。

        Args:
            node_name: 节点名称，例如 "faq_node"、"router_node"、"product_node"

        常用节点：
          faq_node       — FAQ 回答节点（支持 knowledge_type 分级）
          router_node    — 意图分类节点
          product_node   — 商品推荐节点
          aftersales_node — 售后处理节点
          general_node   — 通用对话节点
        """
        content = await prompt_repo.get_active_prompt(node_name)
        if content is None:
            return f"节点 '{node_name}' 没有自定义提示词，当前使用代码中的默认提示词。"
        history = await prompt_repo.get_history(node_name)
        version = next((h["version"] for h in history if h["active"]), "?")
        return f"节点 '{node_name}' 当前提示词（版本 {version}）：\n\n{content}"

    @tool
    async def publish_prompt(node_name: str, prompt_text: str) -> str:
        """为某个图节点发布新的提示词，立即生效（旧版本自动设为非活跃）。

        使用场景：
          - 调整 AI 回答风格（更正式/更口语）
          - 增加特定业务限制指令
          - 修复节点行为问题

        Args:
            node_name: 节点名称（见 preview_prompt 的说明）
            prompt_text: 新的提示词全文。注意保留必要的占位符如 {context}、{lang_rule} 等

        占位符说明（faq_node 必须保留）：
          {context}           — 检索到的知识库内容
          {order_context_hint} — 已知订单信息（自动注入）
          {strict_instruction} — 严格/宽松模式指令（自动注入）
          {lang_rule}         — 语言规则（自动注入）
          {business_name}     — 商户名称（自动注入）
        """
        prompt_id = await prompt_repo.publish_prompt(node_name, prompt_text)
        return f"提示词已发布：节点={node_name}，prompt_id={prompt_id}，立即生效。"

    # ── System metrics ────────────────────────────────────────────────────────

    @tool
    async def get_system_metrics() -> str:
        """获取系统当前数据指标快照，包括知识库文档数、嵌入覆盖率、规则数等。

        适合向管理员报告系统健康状态，或在配置前了解数据现状。
        """
        async with db_pool.acquire() as conn:
            doc_total = await conn.fetchval("SELECT COUNT(*) FROM faq_documents")
            doc_with_embedding = await conn.fetchval(
                "SELECT COUNT(*) FROM faq_documents WHERE embedding IS NOT NULL"
            )
            policy_docs = await conn.fetchval(
                "SELECT COUNT(*) FROM faq_documents WHERE knowledge_type = 'business_policy'"
            )
            industry_docs = await conn.fetchval(
                "SELECT COUNT(*) FROM faq_documents WHERE knowledge_type = 'industry_knowledge'"
            )
            rule_count = await conn.fetchval("SELECT COUNT(*) FROM business_rules")
            product_count = await conn.fetchval("SELECT COUNT(*) FROM products")
            session_count = await conn.fetchval(
                "SELECT COUNT(*) FROM workspace_sessions WHERE resolved_at IS NULL"
            )

        embedding_pct = (
            round(doc_with_embedding / doc_total * 100, 1) if doc_total else 0
        )
        metrics = {
            "knowledge_base": {
                "total_documents": doc_total,
                "with_embedding": doc_with_embedding,
                "embedding_coverage": f"{embedding_pct}%",
                "business_policy_docs": policy_docs,
                "industry_knowledge_docs": industry_docs,
            },
            "configuration": {
                "business_rules_count": rule_count,
                "products_count": product_count,
            },
            "operations": {
                "active_sessions": session_count,
            },
        }
        return json.dumps(metrics, ensure_ascii=False, indent=2)

    return [
        list_current_config,
        upsert_business_rule,
        delete_business_rule,
        list_faq_documents,
        create_faq_document,
        update_faq_document,
        preview_prompt,
        publish_prompt,
        get_system_metrics,
    ]
