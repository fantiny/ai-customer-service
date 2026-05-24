# 部署指南 · 缘梦婚纱 AI 客服平台

> 记录从零到生产环境的完整部署流程，以及过程中遇到的真实问题与解决方案。

---

## 架构总览

```
用户浏览器
  │
  ├── 前端 (Vercel)
  │     https://yuanmeng-ai-cs.vercel.app
  │     技术栈：React + Vite + TypeScript
  │     环境变量：VITE_API_BASE_URL → Railway 后端地址
  │
  └── 后端 (Railway)
        https://ai-customer-service-production-bf04.up.railway.app
        技术栈：FastAPI + LangGraph + Python 3.11
        依赖服务：
          ├── PostgreSQL (Railway 内置，postgres.railway.internal:5432)
          └── Redis     (Railway 内置，redis.railway.internal:6379)
```

---

## 部署步骤

### 1. 数据库：Railway PostgreSQL（推荐，替代 Supabase）

```bash
# 在 Railway 项目中添加 PostgreSQL 服务
railway add --database postgres

# 获取内部连接 URL（供后端服务使用）
railway variables --service Postgres --json | python3 -c "
import sys, json; d=json.load(sys.stdin)
print('Internal:', d['DATABASE_URL'])
print('Public:  ', d['DATABASE_PUBLIC_URL'])
"
```

内部 URL 格式：`postgresql://postgres:PASSWORD@postgres.railway.internal:5432/railway`  
公网 URL 格式：`postgresql://postgres:PASSWORD@PROXY_HOST:PORT/railway`

### 2. Redis：Railway 内置

```bash
railway variables --service Redis --json | python3 -c "
import sys, json; d=json.load(sys.stdin); print(d['REDIS_URL'])
"
```

内部 URL 格式：`redis://default:PASSWORD@redis.railway.internal:6379`

### 3. 后端：Railway（Docker 部署）

**railway.json**（关键：startCommand 必须用 shell 包裹以展开 `$PORT`）：
```json
{
  "$schema": "https://railway.app/railway-schema.json",
  "build": { "builder": "DOCKERFILE", "dockerfilePath": "Dockerfile" },
  "deploy": {
    "startCommand": "sh -c 'uvicorn src.ai_customer_service.app.main:app --host 0.0.0.0 --port ${PORT:-8000}'",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 30,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

**必须设置的 Railway 环境变量**：

| 变量 | 值 |
|------|----|
| `POSTGRES_URL` | `postgresql+asyncpg://postgres:PWD@postgres.railway.internal:5432/railway` |
| `REDIS_URL` | `redis://default:PWD@redis.railway.internal:6379` |
| `LLM_API_KEY` | 你的 LLM API Key |
| `EMBEDDING_API_KEY` | 你的 Embedding API Key |
| `LLM_BASE_URL` | `https://api.minimaxi.com/v1`（或 OpenAI）|
| `LLM_MODEL` | `MiniMax-M2.7`（或 `gpt-4o`）|
| `LLM_PROVIDER` | `openai_compat`（或 `openai`）|
| `EMBEDDING_MODEL` | `text-embedding-3-small` |
| `EMBEDDING_PROVIDER` | `openai`（用 OpenAI）/ `minimax`（用 MiniMax）|
| `JWT_SECRET` | 随机字符串（生产环境务必修改）|

```bash
# 一次性设置所有变量
railway variables set \
  POSTGRES_URL="postgresql+asyncpg://..." \
  REDIS_URL="redis://..." \
  LLM_API_KEY="sk-..." \
  EMBEDDING_API_KEY="sk-..." \
  LLM_BASE_URL="https://api.openai.com/v1" \
  LLM_MODEL="gpt-4o-mini" \
  LLM_PROVIDER="openai" \
  EMBEDDING_MODEL="text-embedding-3-small" \
  EMBEDDING_PROVIDER="openai" \
  JWT_SECRET="your-random-secret"
```

**生成公网域名**：
```bash
railway domain
# 输出: 🚀 https://ai-customer-service-production-xxxx.up.railway.app
```

### 4. 数据库迁移 + 种子数据

```bash
# 用公网 URL 在本地执行迁移（含建表 + 业务配置 + FAQ 文档嵌入）
EMBEDDING_PROVIDER=openai \
EMBEDDING_API_KEY="sk-..." \
POSTGRES_URL="postgresql+asyncpg://postgres:PWD@PROXY_HOST:PORT/railway" \
uv run python scripts/migrate_db.py
```

> 迁移幂等：重复运行安全，已存在的行会跳过。

### 5. 前端：Vercel

```bash
cd workspace

# 设置后端 URL 环境变量
echo "https://ai-customer-service-production-xxxx.up.railway.app" | \
  npx vercel env add VITE_API_BASE_URL production

# 部署到生产
npx vercel --prod --yes
```

前端生产地址：`https://yuanmeng-ai-cs.vercel.app`

---

## 验证部署

```bash
BACKEND="https://ai-customer-service-production-bf04.up.railway.app"

# 1. 健康检查
curl $BACKEND/health
# → {"status":"ok","version":"0.1.0"}

# 2. 获取 JWT
TOKEN=$(curl -s -X POST "$BACKEND/api/auth/token" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test_001"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 3. 发送对话
curl -s -X POST "$BACKEND/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"退货政策是什么？"}' | python3 -m json.tool
```

---

## 问题排查 Q&A

### Q1：Railway 部署报错 `$PORT` 没有展开，服务端口固定为 8000

**现象**：healthcheck 失败，Railway 日志显示 uvicorn 监听了固定端口而非 `$PORT`。

**根因**：`railway.json` 的 `startCommand` 使用了 exec 形式（直接命令数组），Docker exec 模式不经过 shell，无法展开 `$PORT` 这类 shell 变量。

**修复**：将 startCommand 包裹在 `sh -c '...'` 中，并用 `${PORT:-8000}` 提供默认值：
```json
"startCommand": "sh -c 'uvicorn src.ai_customer_service.app.main:app --host 0.0.0.0 --port ${PORT:-8000}'"
```

---

### Q2：asyncpg 连接 Supabase 报 `ConnectionRefusedError [Errno 111]`

**现象**：Railway 部署时应用启动失败，asyncpg 报连接被拒绝。

**根因**：两个问题叠加：
1. asyncpg 不读取 DSN URL 中的 `sslmode=require`，需要显式传 `ssl='require'` 关键字参数；
2. `POSTGRES_URL` 变量值不完整（只有 `host:password@`，缺少主机名和端口）。

**修复（SSL 自动检测）**：在 `database.py` 中添加 `_extract_ssl()` 函数，对 Supabase / Neon / RDS 等云数据库自动启用 `ssl='require'`：
```python
cloud_patterns = ('supabase.co', 'amazonaws.com', 'rds.', 'neon.tech', 'railway.app')
if any(p in url for p in cloud_patterns):
    ssl_value = 'require'
```

---

### Q3：Supabase 连接池（Supavisor）报 `ENOTFOUND tenant/user not found`

**现象**：切换到 Supabase 连接池地址 `aws-0-ap-southeast-1.pooler.supabase.com:6543` 后，本地和 Railway 均报 tenant not found。

**原因分析**：
- Supabase 直连地址（`db.PROJECT_ID.supabase.co`）解析为 **IPv6**，Railway 容器是纯 IPv4，无法直连。
- Supabase 连接池地址虽然是 IPv4，但 Supavisor 持续返回 "tenant/user not found"，即使账号密码、项目 ID、区域均正确。该问题可能与免费套餐的 Supavisor 配置有关，无法从客户端侧修复。

**最终解决方案**：放弃 Supabase，改用 **Railway 内置 PostgreSQL**：
- 与后端服务同属一个 Railway 项目，通过内部域名 `postgres.railway.internal` 直连，零网络延迟，无 SSL 配置问题，无套餐限制。
- 内置 pgvector 扩展（`CREATE EXTENSION IF NOT EXISTS vector` 验证通过）。

```bash
railway add --database postgres
# 自动创建 Postgres 服务，DATABASE_URL 自动注入
```

---

### Q4：密码含特殊字符 `@#` 导致 DSN 解析错误

**现象**：数据库密码为 `4Supabase!@#`，直接拼入 URL 后 asyncpg 解析失败。

**根因**：URL 中 `@` 是用户信息与主机的分隔符，`#` 是 fragment 标记，未转义时解析器截断密码。

**修复**：对特殊字符进行 URL 编码：
- `@` → `%40`
- `#` → `%23`

```
postgresql+asyncpg://user:4Supabase!%40%23@host:5432/db
```

---

### Q5：本地运行 `migrate_db.py` 时始终使用本地 FastEmbed，忽略 MiniMax API

**现象**：即使设置了 `EMBEDDING_API_KEY`，迁移脚本依旧调用 `local_embedding.py`。

**根因**：本地 `.env` 文件中设置了 `EMBEDDING_PROVIDER=local`，pydantic-settings 优先读取 `.env`，覆盖了命令行的 `export` 设置。

**修复**：运行迁移时显式覆盖：
```bash
EMBEDDING_PROVIDER=openai EMBEDDING_API_KEY="sk-..." uv run python scripts/migrate_db.py
```

---

### Q6：MiniMax Embedding API 返回 `code=1008 insufficient balance`

**现象**：切换到 MiniMax embedding 后，API 返回余额不足。

**解决方案**：改用 OpenAI Embedding API（`text-embedding-3-small`，1536 维，与现有 schema `vector(1536)` 完全匹配）：
```bash
railway variables set EMBEDDING_PROVIDER=openai EMBEDDING_API_KEY="sk-openai-..."
```

---

### Q7：FAQ 文档种子插入后，BM25 仍检索不到结果

**现象**：应用在文档入库前已启动，BM25 索引在内存中为空。

**根因**：BM25Retriever 在应用启动时从数据库一次性加载文档构建内存索引，后续插入的文档不会自动更新索引。

**修复**：插入文档后重新部署（或调用 `/api/workspace/admin/knowledge/embed-all` 接口触发重载）：
```bash
railway redeploy --yes
```

> 对中文内容，BM25 效果有限（无分词），**向量检索（pgvector）才是主要路径**，应优先保证 embedding 生成正常。

---

## 当前生产状态（2026-05-21）

| 组件 | 状态 | 备注 |
|------|------|------|
| 后端 API | ✅ 运行中 | Railway，health OK |
| 前端 | ✅ 运行中 | Vercel |
| PostgreSQL | ✅ 运行中 | Railway 内置，pgvector 可用 |
| Redis | ✅ 运行中 | Railway 内置 |
| LLM 对话 | ✅ 正常 | MiniMax M2.7 |
| FAQ 文档 | ⚠️ 仅 BM25 | 5 篇政策文档，embedding 待生成 |
| 商品数据 | ✅ 已种子 | 5 款婚纱 |
| Embedding | ⚠️ 待配置 | 需提供 OpenAI Key 后运行迁移 |

### 下一步：生成 FAQ Embedding

提供 OpenAI API Key 后执行：
```bash
EMBEDDING_PROVIDER=openai \
EMBEDDING_API_KEY="sk-..." \
POSTGRES_URL="postgresql+asyncpg://postgres:WFbhBzLRarmPuXjScFZmUaqLpKDeWsWl@kodama.proxy.rlwy.net:37252/railway" \
uv run python scripts/migrate_db.py
```

完成后 FAQ 知识库将具备完整的向量检索能力，退货政策、换货条款等问题可精准召回。
