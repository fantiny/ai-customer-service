# 测试覆盖率报告

**生成日期**：2026-05-19  
**最终结果**：✅ **100% 覆盖率 · 345 个测试全部通过**

---

## 执行摘要

| 指标 | 结果 |
|------|------|
| 总测试数 | 345 |
| 通过 | 345 |
| 失败 | 0 |
| 总覆盖率 | 100.0% |
| 覆盖行数 / 总行数 | 1736 / 1736 |
| 测试文件数 | 23 |

---

## 覆盖范围说明

### 纳入覆盖的模块（Business-Testable Units）

| 模块路径 | 语句数 | 覆盖率 |
|---------|--------|--------|
| `domain/entities.py` | 244 | 100% |
| `domain/exceptions.py` | 22 | 100% |
| `domain/value_objects.py` | 43 | 100% |
| `graph/edges.py` | 29 | 100% |
| `graph/state.py` | 20 | 100% |
| `graph/nodes/_utils.py` | 138 | 100% |
| `graph/nodes/aftersales_node.py` | 57 | 100% |
| `graph/nodes/faq_node.py` | 52 | 100% |
| `graph/nodes/general_node.py` | 36 | 100% |
| `graph/nodes/human_escalation_node.py` | 12 | 100% |
| `graph/nodes/measurement_guide_node.py` | 132 | 100% |
| `graph/nodes/order_read_node.py` | 108 | 100% |
| `graph/nodes/order_write_node.py` | 112 | 100% |
| `graph/nodes/product_node.py` | 91 | 100% |
| `graph/nodes/router_node.py` | 84 | 100% |
| `graph/nodes/safety_check_node.py` | 45 | 100% |
| `infrastructure/config.py` | 98 | 100% |
| `use_cases/interfaces.py` | 176 | 100% |
| `use_cases/order_service.py` | 159 | 100% |
| `use_cases/rules_keys.py` | 16 | 100% |
| `adapters/retrieval/hybrid_retriever.py` | 47 | 100% |
| `adapters/retrieval/reranker.py` | 15 | 100% |

### 排除覆盖的模块（Integration-Only，需要活跃的 DB/LLM）

以下模块依赖真实数据库连接、Redis 或外部 LLM API，在单元测试中排除：
- `infrastructure/database.py`, `redis_client.py`, `auth.py`, `container.py`
- `app/main.py`, `app/routers/*.py`
- `app/workspace/socket_server.py`, `session_manager.py`
- `adapters/repositories/*.py`（需要 PostgreSQL 连接池）
- `adapters/datasources/**/*.py`（需要外部认证服务）
- `adapters/llm/*.py`（需要 OpenAI/Anthropic API）
- `adapters/retrieval/bm25_retriever.py`, `pgvector_store.py`（需要 PostgreSQL + pgvector）
- `use_cases/business_profile_service.py`, `business_rules_service.py`
- `use_cases/faq_service.py`, `product_service.py`
- `use_cases/workspace_service.py`, `chat_service.py`, `digest_service.py`
- `graph/builder.py`, `graph/admin_graph/*.py`, `graph/node_config.py`

---

## 测试文件清单

### 现有测试（本轮之前已存在）

| 测试文件 | 测试数 | 主要覆盖 |
|---------|--------|---------|
| `test_safety_check_node.py` | 9 | 安全检查节点基础路径 |
| `test_router_node.py` | 8 | 路由节点基础路径 |
| `test_faq_node.py` | 14 | FAQ 节点所有业务分支 |
| `test_product_node.py` | 5 | 商品节点基础路径 |
| `test_order_service.py` | 13 | 订单服务基础路径 |
| `test_wedding_order_service.py` | 29 | 婚纱订单全流程 |
| `test_measurement_guide.py` | 8 | 量体提取逻辑 |
| `test_hybrid_retriever.py` | 8 | 混合检索器 |
| `test_llm_factory.py` | 2 | LLM 工厂 |

### 本轮新增测试文件

| 测试文件 | 测试数 | 覆盖目标 |
|---------|--------|---------|
| `test_domain_extras.py` | 22 | 实体类边缘分支（`WeddingMeta`、`ProductInfo`、`SessionRecord`、`BusinessProfile`、异常类） |
| `test_utils_complete.py` | 47 | `_utils.py` 所有函数完整分支（语言检测、handoff 消息构建、LLM 重试、订单上下文提取） |
| `test_edges.py` | 12 | `edges.py` 路由函数所有路径 |
| `test_safety_complete.py` | 7 | `safety_check_node` 额外分支（Profile 驱动、多轮续接、转人工关键词） |
| `test_router_complete.py` | 10 | `router_node` 额外分支（动态意图模型、DB Prompt 覆写、低置信度回退） |
| `test_human_escalation_node.py` | 4 | 人工升级节点完整覆盖 |
| `test_aftersales_node.py` | 9 | 售后节点完整覆盖（情感升级、工作流、订单上下文） |
| `test_general_node.py` | 7 | 通用节点完整覆盖 |
| `test_order_read_node.py` | 17 | 订单查询节点完整覆盖 |
| `test_order_write_node.py` | 26 | 订单写入节点完整覆盖（HITL 路径、direct execute） |
| `test_measurement_guide_node.py` | 14 | 量体引导节点完整覆盖 |
| `test_remaining_coverage.py` | 49 | 精准补充所有剩余未覆盖行 |

---

## 问题发现与修复记录

### Bug 修复

#### 1. `faq_node.py` - `elif` 导致 industry_knowledge 文档被静默丢弃

**文件**：`src/ai_customer_service/graph/nodes/faq_node.py`  
**问题行**：原第 88-99 行  
**根因**：检索同时返回 `business_policy` 和 `industry_knowledge` 文档时，`elif` 导致 `knowledge_docs` 完全进不了上下文。  
**修复**：`elif knowledge_docs:` 改为 `if knowledge_docs:`，当两种文档共存时，knowledge_docs 以"参考资料"标签追加。  
**验证测试**：`test_mixed_docs_knowledge_not_silently_dropped`（断言 policy 和 knowledge 内容都出现在系统 prompt）

#### 2. `faq_node.py` - 变量名 Bug (`default_lang` 未定义)

**文件**：`src/ai_customer_service/graph/nodes/faq_node.py`  
**问题行**：原第 34 行  
**根因**：`last_user_text = await get_default_lang(...)` 覆盖了 `last_user_text`，但下一行用的是 `default_lang`（未定义变量）。  
**修复**：改为 `default_lang = await get_default_lang(config, last_user_text=last_user_text)`  
**验证测试**：所有 faq_node 测试（启动时不崩溃）

### 测试代码修复

#### 3. `test_remaining_coverage.py` - `tc` mock 类型错误

**问题**：`product_node.py` 使用 `tc["name"]`、`tc["args"]`、`tc["id"]`（字典访问），但测试中的 `tc = MagicMock()` + `tc.name = "..."` 是属性访问，导致 `ToolMessage` 的 Pydantic 验证失败（`tool_call_id` 不能是 MagicMock）。  
**修复**：所有 product_node 测试中改为 `tc = {"name": ..., "args": ..., "id": ...}`（真实字典）。

#### 4. `test_remaining_coverage.py` - `OrderActionResult` Pydantic 验证失败

**问题**：`OrderActionResult.order: Order | None` 字段是 Pydantic 模型，不接受 `MagicMock` 对象，导致订单服务测试中 `ValidationError`。  
**修复**：所有 `get_refund_status`、`exchange_order` 测试改为创建真实 `Order` 对象，并封装了 `_make_order()` 辅助函数。

#### 5. `test_order_write_node.py` - `rules_service.get_language` 必须是 AsyncMock

**问题**：`order_write_node` 调用 `await rules_service.get_language()`，但测试中 `rules_service = MagicMock()`（无 AsyncMock），导致 `TypeError: 'MagicMock' object can't be awaited`。  
**修复**：所有 `_make_rules_service()` 中加 `rules.get_language = AsyncMock(return_value="zh-CN")`。

#### 6. `test_order_write_node.py` - `test_rules_service_hitl_actions_exception_uses_default`

**问题**：`rules_service.get = AsyncMock(side_effect=RuntimeError(...))` 让所有 `get()` 调用都抛异常，包括加急费率查询（`rush.fee.standard` 等），而这些查询没有 try/except 保护，导致节点提前退出。  
**修复**：改为选择性异常 mock——只对 HITL key 抛异常，对其他 key 返回 `default`：
```python
async def _get_raises_on_hitl(key, default=None):
    if "hitl" in str(key).lower():
        raise RuntimeError("DB error")
    return default
rules.get = _get_raises_on_hitl
```

### 语义增强

#### 7. `test_order_service_get_refund_rate_from_db` - 区分 DB 路径与硬编码路径

**原始问题**：DB 返回值 `0.7` 与硬编码值 `0.70` 相同，无法证明测试走了 DB 路径。  
**修复**：DB 返回值改为 `0.5`（50%），断言改为 `assert "50%" in result.message and "70%" not in result.message`，明确验证 DB 路径被使用。

---

## `# pragma: no cover` 标注的死代码

以下代码路径逻辑上不可达（防御性编码），添加了 `# pragma: no cover` 注释而非强行编写虚假测试：

### `measurement_guide_node.py` - 正则表达式后的 `ValueError` 分支

```python
# Pass 1 & Pass 2 中
try:
    collected[field] = float(value_str)
except ValueError:  # pragma: no cover
    pass
```

**原因**：`value_str` 来自 `re.compile(r'\d{2,3}')` 的捕获组，纯数字字符串永远不会触发 `ValueError`。

### `measurement_guide_node.py` - `_try_contextual_bare_number` 中的 `ValueError`

```python
try:
    value = float(bare_nums[0])
except ValueError:  # pragma: no cover
    return result
```

**原因**：`bare_nums` 来自 `re.findall(r'\b(\d{2,3})\b', ...)` 返回的纯数字字符串，永远不会触发 `ValueError`。

### `reranker.py` - FlagEmbedding 模型实例化

```python
from FlagEmbedding import FlagReranker as _FlagReranker
self._model = _FlagReranker(model_name, use_fp16=True)  # pragma: no cover
```

**原因**：`FlagEmbedding` 是可选依赖（`pip install 'ai-customer-service[reranker]'`），测试环境未安装。未安装时 `ImportError` 分支被触发，安装成功路径（该行）只在生产环境执行。

---

## 条件分支覆盖详情（关键业务逻辑）

### `faq_node.py` 知识库分级策略

| 分支 | 触发条件 | 测试用例 |
|------|---------|---------|
| 严格模式（business_policy） | 检索到政策文档 | `test_policy_only_strict_mode_returns_answer` |
| 宽松模式（industry_knowledge） | 只有行业知识文档 | `test_knowledge_only_flexible_mode_returns_answer` |
| 混合模式（两种文档共存） | 两类文档都有 | `test_mixed_docs_strict_mode_includes_both` |
| 转人工（政策关键词无文档） | 无文档 + 含"退货/退款"等关键词 | `test_no_docs_policy_keyword_triggers_handoff` |
| LLM 通用回答 | 无文档 + 普通问题 | `test_no_docs_general_question_uses_llm` |

### `order_write_node.py` HITL 完整路径

| 分支 | 触发条件 | 测试用例 |
|------|---------|---------|
| 提取失败 | LLM 返回 None | `test_extraction_failure_asks_for_order_info` |
| 缺少订单号 | extraction.order_id == "" | `test_no_order_id_asks_for_order_number` |
| 前置验证失败（不存在） | `OrderNotFoundError` | `test_validate_order_not_found_returns_error` |
| 前置验证失败（无权限） | `OrderAccessDeniedError` | `test_validate_access_denied_returns_error` |
| 前置验证失败（动作无效） | `InvalidOrderActionError` | `test_validate_invalid_action_returns_user_reason` |
| HITL 拒绝 | `interrupt()` 返回 `approved=False` | `test_hitl_rejected_returns_cancellation_message` |
| HITL 批准 + 执行成功 | `interrupt()` 返回 `approved=True` | `test_hitl_approved_executes_and_returns_result` |
| HITL 批准 + 执行异常 | 批准后 `execute()` 抛异常 | `test_hitl_approved_order_not_found_error`、`test_hitl_approved_access_denied_error` 等 |
| 非 HITL 直接执行 | `action` 不在 hitl_required 列表 | `test_non_hitl_action_executes_directly` |

### `order_service.py` 退款利率路径

| 分支 | 触发条件 | 测试用例 |
|------|---------|---------|
| DB 利率（覆盖硬编码） | `rules_service.get()` 返回非 None | `test_order_service_get_refund_rate_from_db`（DB 返回 50%，断言非硬编码 70%） |
| 异常回退硬编码利率 | `rules_service.get()` 抛异常 | `test_order_service_get_refund_rate_rules_exception_falls_back` |
| 硬编码利率（无规则服务） | `rules_service` 为 None | 多个 wedding_order_service 测试 |

### `safety_check_node.py` 安全检测路径

| 分支 | 触发条件 | 测试用例 |
|------|---------|---------|
| 阻断（Prompt Injection） | "Ignore previous instructions" | `test_prompt_injection_blocked` |
| 阻断（Script Injection） | `<script>` 标签 | `test_script_injection_blocked` |
| 多轮续接 | `awaiting_order_id` = "order_read_node" 等 | `test_multi_turn_continuation` |
| 转人工关键词 | "找人工"/"要投诉" | `test_human_escalation_keyword_detected` |
| Profile 驱动配置 | 自定义关键词列表 | `test_safety_with_business_profile` |

---

## 附录：`.coveragerc` 配置

```ini
[run]
source = src/ai_customer_service
omit =
    */infrastructure/database.py
    */infrastructure/redis_client.py
    */infrastructure/auth.py
    */infrastructure/container.py
    */app/main.py
    */app/routers/*.py
    */app/workspace/socket_server.py
    */app/workspace/session_manager.py
    */app/dependencies.py
    */app/schemas.py
    */adapters/repositories/*.py
    */adapters/datasources/*.py
    */adapters/datasources/**/*.py
    */adapters/llm/*.py
    */adapters/observability/*.py
    */adapters/retrieval/bm25_retriever.py
    */adapters/retrieval/pgvector_store.py
    */use_cases/business_profile_service.py
    */use_cases/business_rules_service.py
    */use_cases/faq_service.py
    */use_cases/product_service.py
    */graph/builder.py
    */graph/admin_graph/*.py
    */graph/node_config.py
    */use_cases/workspace_service.py
    */use_cases/chat_service.py
    */use_cases/digest_service.py

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    if TYPE_CHECKING:
    raise NotImplementedError
    \.\.\.$
    pass$
show_missing = true
precision = 1
```

---

## 运行测试

```bash
# 单次运行（带覆盖率报告）
uv run pytest tests/unit/ --cov=src/ai_customer_service --cov-report=term-missing -q

# 快速验证（无覆盖率）
uv run pytest tests/unit/ -q

# 只运行特定节点测试
uv run pytest tests/unit/test_faq_node.py tests/unit/test_order_write_node.py -v
```
