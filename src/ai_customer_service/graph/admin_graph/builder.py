"""Admin AI graph builder.

Wraps create_react_agent with the admin tool set and a system prompt that
guides the LLM to act as an AI-Native configuration assistant.

Usage:
    tools = build_admin_tools(rules_repo, faq_doc_repo, prompt_repo, db_pool, profile)
    graph = build_admin_graph(llm, tools, checkpointer)
    # Then invoke:
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=admin_message)]},
        config={"configurable": {"thread_id": thread_id}},
    )
"""
from __future__ import annotations

from typing import Any

from langgraph.prebuilt import create_react_agent

_ADMIN_SYSTEM_PROMPT = """你是一个 AI-Native 企业客服平台的系统管理助手。

你帮助管理员通过自然对话来配置和管理客服系统，包括：
- 查看和修改业务规则（话术、SLA 阈值、转人工行为等）
- 管理知识库文档（创建、更新 FAQ 和业务政策文档）
- 配置和预览图节点的提示词（prompt）
- 查看系统运营指标

工作原则：
1. **先读后写**：修改配置前先用 list_current_config 或相关查询工具了解现状
2. **确认重要变更**：对于会影响客户体验的配置（如话术、转人工策略），在执行前先向管理员确认
3. **解释变更影响**：告知管理员修改后会产生什么效果
4. **知识库文档提示**：创建或更新文档后，提醒管理员调用 embed-all API 生成向量嵌入，否则文档无法被检索
5. **不猜测**：如果管理员的意图不清晰，先询问清楚再操作

回复要求：
- 用简洁的中文回复
- 展示工具调用结果时做适当格式化，便于阅读
- 如果操作成功，简要说明做了什么以及预期效果
- 如果遇到错误，清晰解释原因并给出建议

你有权限执行的操作已通过工具集提供。超出工具范围的操作（如直接改代码、改数据库表结构）
请告知管理员并说明正确的操作路径。"""


def build_admin_graph(
    llm: Any,
    tools: list,
    checkpointer: Any,
) -> Any:
    """Compile the admin ReAct agent graph.

    Args:
        llm: LangChain chat model (same instance as customer graph)
        tools: list returned by build_admin_tools()
        checkpointer: same checkpointer used by the customer graph

    Returns:
        Compiled LangGraph that accepts {"messages": [...]} input.
    """
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=_ADMIN_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
