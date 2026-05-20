# 缘梦婚纱 · AI 智能客服系统

> 婚纱电商生产级 AI 客服，基于 **LangGraph + Clean Architecture** 构建。  
> 七意图路由 · 混合 RAG · HITL 人工审批 · 实时工作台 · 多语言支持 · 全链路持久化

---

## 目录

1. [系统架构](#系统架构)
2. [功能总览](#功能总览)
3. [快速启动](#快速启动)
4. [目录结构](#目录结构)
5. [核心流程](#核心流程)
6. [配置说明](#配置说明)
7. [API 参考](#api-参考)
8. [开发路线图](#开发路线图)

---

## 系统架构

```
客户端（React + Vite）          后端（FastAPI + Socket.io）           存储层
───────────────────────         ───────────────────────────────────   ──────────────
CustomerPortal                  app/main.py (socketio.ASGIApp)        PostgreSQL
  ↕ Socket.io             ←──→   socket_server.py                      ├─ workspace_sessions
AgentWorkspace                     WorkspaceService                    ├─ tickets
  ↕ REST API                         ↕                                 ├─ status_events
                                   ChatService                         ├─ agents
                                     ↕                                 ├─ session_messages
                                   LangGraph StateGraph                ├─ conversations
                                     ├─ safety_check_node              ├─ orders
                                     ├─ router_node                    ├─ faq_documents
                                     ├─ product_node                   ├─ business_rules
                                     ├─ faq_node                       └─ node_prompts
                                     ├─ order_read_node
                                     ├─ order_write_node (HITL)       Redis
                                     ├─ aftersales_node                └─ LangGraph checkpoint
                                     ├─ human_escalation_node
                                     └─ general_node
```

### 核心设计原则

| 原则 | 说明 |
|---|---|
| **整洁架构** | `domain → use_cases → adapters → infrastructure`，各层只依赖内层接口 |
| **写透持久化** | 内存热缓存 + PostgreSQL 双写，重启无数据丢失 |
| **接口优先** | 所有仓库通过 ABC 接口注入，业务逻辑零框架依赖 |
| **可替换数据源** | 订单/商品/FAQ 可从内部 DB 切换到外部 REST API，对对话链路透明 |
| **多语言** | 检测客户消息语言自动回复；默认语言可实时通过 Admin API 变更 |

---

## 功能总览

### AI 对话引擎

| 意图 | 节点 | 说明 |
|---|---|---|
| `product` | `product_node` | 混合检索推荐婚纱（BM25 + pgvector RRF rerank） |
| `faq` | `faq_node` | FAQ / 政策 / 工艺问答（RAG + 向量召回） |
| `order_read` | `order_read_node` | 查订单状态、生产进度、物流（多轮澄清） |
| `order_write` | `order_write_node` | 取消 / 退款 / 加急，全部挂起等待 HITL 审批 |
| `aftersales` | `aftersales_node` | 质量投诉、售后处理、情绪安抚 |
| `general` | `general_node` | 兜底闲聊、情绪安抚 |
| `transfer_to_human` | `human_escalation_node` | 关键词快速路由（无需 LLM），暖转接人工 |

### HITL 人工审批

- 高风险操作（取消订单 / 申请退款 / 加急）触发 `interrupt()` 挂起 LangGraph
- 工作台实时弹出审批卡片，显示操作类型、订单号、加急等级、AI 协同建议
- 批准 → AI 继续执行；拒绝 → 告知客户并清理状态
- 防重复点击：按钮点击后显示"处理中…"直到后端响应

### 实时工作台（AgentWorkspace）

| 功能 | 说明 |
|---|---|
| 三列布局 | 会话列表 / 对话面板 / 上下文面板，各列独立滚动 |
| 会话队列 | 仅显示 `hitl_pending` / `human` 模式会话 |
| AI 接管摘要 | 转人工时 LLM 自动生成摘要，置顶显示于对话框内（可滚动，不遮挡） |
| 认领会话 | 点击"认领此会话"立即打开对话面板（乐观更新），HITL 批准/拒绝后面板正确清空 |
| 订单上下文 | 侧边栏实时显示婚礼日期、订单金额、生产阶段 |
| SLA 提醒 | 超时自动标红（后端定时检查，前端 5min 自动清除） |
| 打字指示器 | 双向：客服看到客户在输入，客户看到客服在输入 |
| 客服身份 | 登录后头部显示姓名 + ID；对话框消息标签显示真实客户 ID |
| 结单 | 弹窗填写解决方案 → 工单状态 → resolved |

### 客户对话框（CustomerPortal）

- 连接状态 + 客户 ID 实时显示于头部
- 支持快捷提问按钮（了解定制流程 / 查询订单 / 加急 / 退换货）
- AI / 人工模式自动切换，人工接管时显示"专属顾问接待中"
- CSAT 评分（1~5 星，结单后弹出）
- 打字指示器（bot / agent 回复前的动画）

### 多语言支持

- 检测客户最后一条消息语言，自动用对应语言回复
- 中文客户 + 中文默认语言 → 零 LLM 翻译调用（快速通道）
- 日文假名 / 韩文字母排除，避免被误判为中文
- `<think>` 推理块自动清除，不暴露给客户
- 默认语言：`.env DEFAULT_LANGUAGE` → 后台 API 实时变更（60s 缓存）

### 持久化 & 可观测性

- 会话（workspace_sessions）+ 工单（tickets）+ 消息（session_messages）全量入库
- 状态变更审计（status_events）
- 业务规则动态配置（business_rules 表，60s 缓存）
- Prompt 版本管理（node_prompts 表，可通过 API 热更新）
- Langfuse 可观测性（可选，`LANGFUSE_ENABLED=true`）

---

## 快速启动

### 前置依赖

```bash
# 运行时
Python 3.11+   uv   Node 18+   PostgreSQL 15+（含 pgvector）   Redis 7+

# 检查
python3 --version && uv --version && node --version
psql --version && redis-cli --version
```

### 一键启动（开发模式）

```bash
# 1. 克隆 & 安装依赖
git clone <repo>
cd ai_customer_service
uv sync
cd workspace && npm install && cd ..

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY、POSTGRES_URL 等

# 3. 初始化数据库（含种子数据）
./dev.sh --seed

# 4. 启动
./dev.sh
```

### dev.sh 命令

| 命令 | 说明 |
|---|---|
| `./dev.sh` | 启动后端（:8000）+ 前端（:3000） |
| `./dev.sh --seed` | 迁移数据库 + 写入种子数据后启动 |
| `./dev.sh --stop` | 停止所有后台进程 |
| `./dev.sh --logs` | 实时查看合并日志（Ctrl-C 不影响服务） |
| `./dev.sh --status` | 显示各服务进程状态 |

### 访问地址

| 地址 | 说明 |
|---|---|
| http://localhost:3000 | 客户对话框（需 `?token=` 或 `?user=` 参数） |
| http://localhost:3000/?view=agent | 客服工作台 |
| http://localhost:3000/test.html | 测试控制台（可一键打开各角色） |
| http://localhost:8000/docs | FastAPI Swagger 文档 |
| http://localhost:8000/health | 健康检查 |

---

## 目录结构

```
ai_customer_service/
├── src/ai_customer_service/
│   ├── domain/                     # 领域实体 & 值对象（无框架依赖）
│   │   ├── entities.py             # Order, Ticket, SessionRecord, Agent ...
│   │   ├── value_objects.py        # ProductionStage, OrderStatus, RushLevel ...
│   │   └── exceptions.py
│   ├── use_cases/                  # 业务逻辑层
│   │   ├── interfaces.py           # ABC 接口（IOrderRepository, ITicketRepository ...）
│   │   ├── chat_service.py         # 消息路由 & LangGraph 调用
│   │   ├── workspace_service.py    # 工作台核心：会话/工单/摘要/SLA
│   │   ├── order_service.py        # 订单操作（退款率从业务规则表读取）
│   │   └── faq_service.py          # FAQ 导入 & 向量化
│   ├── graph/                      # LangGraph 状态图
│   │   ├── builder.py              # 图拓扑定义
│   │   ├── state.py                # CustomerServiceState
│   │   ├── edges.py                # 路由逻辑
│   │   └── nodes/
│   │       ├── _utils.py           # 多语言工具（make_lang_rule / lang_format / strip_thinking）
│   │       ├── router_node.py      # 意图分类
│   │       ├── safety_check_node.py
│   │       ├── product_node.py
│   │       ├── faq_node.py
│   │       ├── order_read_node.py
│   │       ├── order_write_node.py # HITL interrupt()
│   │       ├── aftersales_node.py
│   │       ├── general_node.py
│   │       └── human_escalation_node.py
│   ├── adapters/                   # 基础设施适配器
│   │   ├── repositories/           # PG 仓库实现
│   │   │   ├── session_repository.py
│   │   │   ├── ticket_repository.py
│   │   │   ├── agent_repository.py
│   │   │   ├── business_rules_repository.py  # 60s 缓存
│   │   │   ├── prompt_repository.py           # Prompt 版本管理
│   │   │   ├── message_repository.py
│   │   │   ├── order_repository.py
│   │   │   └── conversation_repository.py
│   │   ├── retrieval/              # RAG 检索
│   │   │   ├── pgvector_store.py   # 向量检索
│   │   │   ├── bm25_retriever.py   # 关键词检索
│   │   │   ├── hybrid_retriever.py # RRF 融合
│   │   │   └── reranker.py         # 可选 rerank（bge-reranker）
│   │   ├── llm/                    # LLM 工厂（OpenAI 兼容接口）
│   │   └── datasources/            # 订单/商品/Auth 数据源（可切 REST API）
│   ├── app/                        # FastAPI 应用层
│   │   ├── main.py                 # 返回 socketio.ASGIApp（WebSocket 关键）
│   │   ├── routers/
│   │   │   ├── auth.py             # JWT 签发 & 验证
│   │   │   ├── chat.py             # REST 聊天接口
│   │   │   ├── workspace.py        # 工单/指标/规则/Prompt API
│   │   │   └── health.py
│   │   └── workspace/
│   │       ├── socket_server.py    # Socket.io 事件处理（14 个事件）
│   │       └── session_manager.py  # 内存热缓存（write-through 到 PG）
│   └── infrastructure/
│       ├── config.py               # Pydantic Settings（.env 读取）
│       ├── container.py            # 依赖注入容器
│       ├── auth.py                 # JWT HS256 / JWKS 验证
│       ├── database.py             # asyncpg 连接池
│       └── redis_client.py
├── workspace/                      # React 前端
│   ├── src/
│   │   ├── App.tsx                 # 路由：customer / agent 视图切换
│   │   ├── components/
│   │   │   ├── CustomerPortal.tsx  # 客户对话框
│   │   │   └── AgentWorkspace.tsx  # 客服工作台（SessionList / ConversationPanel / ContextPanel）
│   │   ├── lib/
│   │   │   ├── socket.ts           # Socket.io 客户端单例
│   │   │   └── auth.ts             # token / guest 身份解析
│   │   └── types.ts                # SessionInfo, Ticket, ChatMsg ...
│   └── public/
│       └── test.html               # 测试控制台
├── scripts/
│   ├── migrate_db.py               # DDL 幂等迁移 + 默认业务规则写入
│   └── seed_data.py                # 种子订单 & FAQ 数据
├── dev.sh                          # 一键开发启动脚本
├── .env                            # 本地环境变量
└── pyproject.toml
```

---

## 核心流程

### 客户发消息 → AI 回复

```
CustomerPortal
  → socket: user_message {session_id, content}
  → socket_server.user_message()
  → ChatService.send_message()
  → LangGraph.ainvoke()
      → safety_check_node    （屏蔽词 / 人工关键词检测）
      → router_node          （意图分类：7 类）
      → <intent>_node        （业务处理 + 多语言格式化）
  → socket: bot_reply → CustomerPortal
  → socket: new_message → AgentWorkspace（room: workspace）
```

### 高风险操作 → HITL 审批

```
order_write_node
  → interrupt(pending_action)    # LangGraph 挂起
  → socket: hitl_pending → AgentWorkspace
  → 客服点击"批准"
  → socket: hitl_approve
  → ChatService.resume_hitl({approved: true})
  → LangGraph 从 interrupt 处恢复
  → 执行 OrderService.execute()
  → socket: bot_reply → CustomerPortal
  → 会话 mode → ai → queue_updated → 工作台面板清空
```

### 转人工 → 会话接管

```
human_escalation_node / aftersales_node（情绪触发）
  → session.mode = 'hitl_pending' → 'human'
  → WorkspaceService._generate_handoff_summary()   # LLM 生成摘要
  → socket: hitl_pending / queue_updated → AgentWorkspace 左侧出现会话
  → 客服点击"认领此会话" → 乐观打开对话面板
  → 客服发送 agent_reply
  → socket: bot_reply（以 bot 推送） → CustomerPortal
  → 客服点击"结单" → Ticket.status = resolved → 会话从队列移除
```

---

## 配置说明

### .env 关键字段

```bash
# LLM（OpenAI 兼容接口，支持 MiniMax / DeepSeek / vLLM 等）
LLM_PROVIDER=openai_compat
LLM_MODEL=MiniMax-M2.7
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.minimaxi.com/v1

# 向量化
EMBEDDING_MODEL=embo-01        # 留空复用 LLM_API_KEY / LLM_BASE_URL

# 数据库
POSTGRES_URL=postgresql+asyncpg://user:pass@localhost:5432/customer_service
REDIS_URL=redis://localhost:6379/0

# 默认语言（可通过 Admin API 实时修改，60s 生效）
DEFAULT_LANGUAGE=zh-CN         # zh-CN | en | ja | ko | th

# JWT 认证
JWT_SECRET=<随机长字符串>
JWT_REQUIRED=false             # true = 强制 JWT，false = 允许 ?user= 访客

# 可选：RAG reranker
RERANKER_ENABLED=false
RERANKER_MODEL=BAAI/bge-reranker-base

# 可选：Langfuse 可观测性
LANGFUSE_ENABLED=false
```

### 业务规则（Admin API 实时变更）

| 规则键 | 默认值 | 说明 |
|---|---|---|
| `refund_rate.pending` | 1.00 | 待排产退款比例 |
| `refund_rate.confirmed` | 0.90 | 已确认退款比例 |
| `refund_rate.cutting` | 0.50 | 剪裁阶段退款比例 |
| `refund_rate.sewing` | 0.00 | 缝制阶段退款比例 |
| `refund_rate.beading` | 0.00 | 珠绣阶段退款比例 |
| `refund_rate.qc` | 0.00 | 质检阶段退款比例 |
| `refund_rate.ready` | 0.00 | 完成阶段退款比例 |
| `sla_hitl_minutes` | 2 | HITL 超时提醒（分钟） |
| `sla_human_response_minutes` | 5 | 人工首次回复超时（分钟） |
| `sla_resolve_hours` | 24 | 工单最长未结单超时（小时） |
| `hitl_required_actions` | `["cancel_order","initiate_refund","request_rush"]` | 需要 HITL 的操作 |
| `default_language` | `"zh-CN"` | 默认回复语言 |

---

## API 参考

### 认证

```
POST /api/auth/token          签发测试 JWT（需配置 JWT_SECRET）
GET  /api/auth/me             验证当前 token

body: { user_id, name, email?, expires_in? }
```

### 工单 & 会话

```
GET  /api/workspace/tickets                     所有工单（可选 ?status=open|resolved）
GET  /api/workspace/tickets/{ticket_id}         单个工单详情
POST /api/workspace/tickets/{ticket_id}/resolve 结单
GET  /api/workspace/tickets/{ticket_id}/events  状态时间线
GET  /api/workspace/sessions/{session_id}/messages  消息审计记录
GET  /api/workspace/agents                      在线客服列表
```

### 指标 & 分析

```
GET  /api/workspace/metrics/today               今日 KPI（会话数 / AI 解决率 / 平均响应时长）
GET  /api/workspace/analytics?days=7            业务分析报告（7/30 天可选）
```

### 管理配置（Admin）

```
GET  /api/workspace/admin/rules                 业务规则列表
PUT  /api/workspace/admin/rules/{key}           修改业务规则（立即生效，60s 缓存）
GET  /api/workspace/admin/prompts               Prompt 节点列表
GET  /api/workspace/admin/prompts/{node}        历史版本
POST /api/workspace/admin/prompts/{node}        发布新 Prompt（热更新，无需重启）
```

### Socket.io 事件

**客户端 → 服务端**

| 事件 | 数据 | 说明 |
|---|---|---|
| `join` | `{user_id, session_id?}` | 客户加入 |
| `user_message` | `{session_id, content}` | 发送消息 |
| `join_workspace` | `{agent_id, name}` | 客服加入工作台 |
| `claim_session` | `{session_id, agent_id}` | 认领会话 |
| `agent_reply` | `{session_id, content, agent_id}` | 客服回复 |
| `hitl_approve` | `{session_id, notes?}` | 批准高风险操作 |
| `hitl_reject` | `{session_id, notes?}` | 拒绝高风险操作 |
| `transfer_to_agent` | `{session_id}` | 强制转人工 |
| `transfer_to_bot` | `{session_id}` | 回交 AI |
| `agent_typing` | `{session_id, typing}` | 客服打字状态 |
| `customer_typing` | `{session_id, typing}` | 客户打字状态 |

**服务端 → 客户端**

| 事件 | 接收方 | 说明 |
|---|---|---|
| `bot_reply` | 客户 | AI / 客服回复 |
| `queue_updated` | 工作台 | 会话队列刷新 |
| `hitl_pending` | 工作台 | 新 HITL 审批请求 |
| `new_message` | 工作台 | 新消息（用于实时同步） |
| `session_claimed` | 工作台 | 会话被认领 |
| `ticket_resolved` | 工作台 | 工单结单 |
| `sla_warning` | 工作台 | SLA 超时提醒 |
| `order_context_updated` | 工作台 | 订单上下文更新 |
| `bot_typing` | 客户 | AI 正在思考 |
| `agent_typing` | 客户 | 客服正在输入 |
| `customer_typing` | 工作台 | 客户正在输入 |

---

## 开发路线图

> 按业务优先级排序。带 ✅ 的已实现。

### ✅ 已完成

**核心功能**
- [x] LangGraph 七意图路由（safety → router → 7 节点）
- [x] 混合 RAG（BM25 + pgvector + RRF rerank）
- [x] HITL 人工审批（interrupt / resume 全流程）
- [x] 实时工作台（Socket.io 双向，三列布局）
- [x] 全量持久化（会话 / 工单 / 消息 / 状态事件）
- [x] 工单生命周期管理（open → in_progress → resolved）
- [x] 会话认领（乐观更新，防竞态）
- [x] AI 接管摘要（转人工时自动生成，`<think>` 块清除）
- [x] SLA 超时提醒（后端定时任务 + 前端标红）
- [x] 多语言自动切换（中/英/日/韩等，快速通道优化）
- [x] 默认语言 Admin API 实时配置（60s 缓存）
- [x] 业务规则外置（退款率/SLA/HITL 触发条件，API 热更新）
- [x] Prompt 版本管理（node_prompts 表，API 热发布）
- [x] JWT 认证（HS256 / JWKS 双模式，`JWT_REQUIRED` 开关）
- [x] Langfuse 可观测性集成（可选）
- [x] 一键开发启动脚本（dev.sh，含健康检查 & 种子数据）
- [x] 测试控制台（test.html，10 个测试角色，7 个测试场景）
- [x] CSAT 客户满意度评分（结单后弹出 1~5 星）
- [x] 打字指示器（双向）
- [x] 未读消息计数

**P1 — 运营效率**
- [x] **结案报告自动生成**：工单结单后 LLM 异步分析对话，生成问题分类/情绪变化/AI质量评级
- [x] **历史工单面板**：工作台新增"历史"标签，支持状态/日期/关键词筛选，点击查看完整对话回放
- [x] **多会话只读保护**：`agent_reply` 校验认领归属，非认领客服回复被拒绝；前端已认领会话显示只读横幅
- [x] **订单上下文填充**：`order_read_node` 查询成功后 emit `order_context_updated`，工作台实时显示订单卡片

**P2 — 智能路由与分析**
- [x] **运营数据大盘**：`/api/workspace/analytics` 提供意图分布/解决率/趋势等，前端新增"数据"面板（进度条/柱状图）
- [x] **情绪升级转人工**：`aftersales_node`（阈值3轮）/`general_node`（阈值4轮）累计负面关键词自动触发转人工
- [x] **婚期紧急度路由**：`router_node` 检测 `order_context.wedding_date`，距今 ≤ 14 天时注入 `is_urgent=True`；会话队列紧急会话置顶
- [x] **多轮订单查询**：`order_read_node` 无订单号时先列举用户所有订单（最多5条），引导确认具体订单

**Tech 债务清理**
- [x] **HITL 自动超时**：`hitl_timeout_watcher` 后台任务（每30s检查），超时（默认10min）自动拒绝并通知客户
- [x] **删除废弃文件**：`_order_node_archived.py` 已删除
- [x] **LLM 指数退避重试**：`_utils.py` 新增 `llm_invoke_with_retry()`，最多3次，对429/timeout/overload重试

---

### 🟢 长期规划（P3）

#### 1. 主动通知推送
**场景**：订单状态变更（进入质检 / 发货）时，系统主动向客户推送消息，无需等客户来问。

```
生产阶段更新 → webhook → ChatService → Socket.io → CustomerPortal
```

---

#### 2. 客服绩效报表
**场景**：按周 / 月生成每位客服的工单数、解决时长、CSAT 平均分、HITL 操作记录。  
- 后端聚合查询
- 前端报表页（图表）

---

#### 3. 知识库自助管理
**场景**：运营人员通过 Admin UI 直接增删改 FAQ 条目，实时向量化写入 `faq_documents`。  
**现状**：FAQ 通过 `scripts/seed_data.py` 批量导入，无 UI 界面。

---

#### 4. 移动端客服 App
**场景**：客服用手机处理紧急工单（认领 / 回复 / 结单），推送通知取代 SLA 标红。  
- React Native（复用现有 Socket.io 接口）
- APNs / FCM 推送集成

---

### 技术债务（剩余）

| 项目 | 说明 | 优先级 |
|---|---|---|
| `session_manager.py` 内存状态 | 多实例部署时会不一致，需改为纯 PG 查询 | 中 |
| 缺少单元测试 | 各 node 仅有集成测试，mock 测试覆盖率低 | 中 |
| 前端无错误边界 | 组件崩溃时整页白屏，应加 ErrorBoundary | 低 |
