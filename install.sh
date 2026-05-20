#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# 缘梦婚纱 AI 客服系统 — 一键安装脚本
# 用法：bash install.sh [--no-docker]
#   --no-docker   使用 Homebrew Postgres+Redis 代替 Docker（macOS 推荐）
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

RESET='\033[0m'; BOLD='\033[1m'
GREEN='\033[92m'; YELLOW='\033[93m'; RED='\033[91m'
CYAN='\033[96m'; DIM='\033[2m'

ok()   { echo -e "${GREEN}  ✓ $*${RESET}"; }
info() { echo -e "${CYAN}  ▸ $*${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠ $*${RESET}"; }
err()  { echo -e "${RED}  ✗ $*${RESET}"; exit 1; }
step() { echo -e "\n${BOLD}${CYAN}── $* ──${RESET}"; }

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ── 参数 ──────────────────────────────────────────────────────────────────────
NO_DOCKER=false
for arg in "$@"; do
    [ "$arg" = "--no-docker" ] && NO_DOCKER=true
done

# 如果 Docker daemon 不可达，自动切换 no-docker 模式
if ! curl -sf --unix-socket /Users/jay/.docker/run/docker.sock \
     'http://localhost/v1.41/_ping' --max-time 3 >/dev/null 2>&1; then
    warn "Docker daemon 不可达，自动切换为 Homebrew 模式（--no-docker）"
    NO_DOCKER=true
fi

echo -e "${BOLD}${CYAN}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   缘梦婚纱 · AI 客服系统 · 一键安装         ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${RESET}"
echo -e "  模式：${BOLD}$([ "$NO_DOCKER" = true ] && echo 'Homebrew Postgres+Redis' || echo 'Docker Compose')${RESET}\n"

# ── 1. 检查系统依赖 ───────────────────────────────────────────────────────────
step "检查系统依赖"

command -v python3 >/dev/null 2>&1 || err "未找到 Python3"
command -v node    >/dev/null 2>&1 || err "未找到 Node.js 18+"
command -v npm     >/dev/null 2>&1 || err "未找到 npm"

if [ "$NO_DOCKER" = false ]; then
    command -v docker >/dev/null 2>&1 || err "未找到 Docker，请安装 Docker Desktop 或使用 --no-docker"
else
    command -v brew >/dev/null 2>&1 || err "未找到 Homebrew，请先安装：https://brew.sh"
fi

info "Python $(python3 --version 2>&1 | awk '{print $2}')  Node $(node -v)"
ok "依赖检查通过"

# ── 2. 检查 .env ──────────────────────────────────────────────────────────────
step "检查环境变量配置"

if [ ! -f "$ROOT/.env" ]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    warn ".env 已从模板创建，请填入 LLM_API_KEY 后重新运行"
    exit 1
fi

LLM_KEY=$(grep '^LLM_API_KEY=' "$ROOT/.env" | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d ' ')
if [ -z "$LLM_KEY" ] || [ "$LLM_KEY" = "sk-xxx" ]; then
    warn ".env 中 LLM_API_KEY 未配置，请填入有效 Key 后重新运行"
    exit 1
fi
ok ".env 配置已就绪"

# ── 3. Python 虚拟环境 ────────────────────────────────────────────────────────
step "安装 Python 依赖"

VENV="$ROOT/.venv"
[ -d "$VENV" ] || python3 -m venv "$VENV"
info "pip install（首次约 2-3 分钟）..."
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e ".[dev]"
ok "Python 依赖完成"

# ── 4. 前端依赖 ───────────────────────────────────────────────────────────────
step "安装前端依赖"

if [ ! -d "$ROOT/workspace/node_modules" ]; then
    info "npm install（首次约 1 分钟）..."
    npm install --prefix "$ROOT/workspace" --silent
else
    info "node_modules 已存在，跳过"
fi
ok "前端依赖完成"

# ── 5. 数据库与 Redis ─────────────────────────────────────────────────────────
if [ "$NO_DOCKER" = true ]; then
    # ─── Homebrew 模式 ──────────────────────────────────────────────────────────
    step "安装 / 启动 PostgreSQL 16 + pgvector + Redis（Homebrew）"

    # 安装（已安装则跳过）
    brew list postgresql@16 >/dev/null 2>&1 || { info "brew install postgresql@16..."; brew install postgresql@16; }
    brew list redis          >/dev/null 2>&1 || { info "brew install redis...";         brew install redis; }
    brew list pgvector       >/dev/null 2>&1 || { info "brew install pgvector...";      brew install pgvector; }
    ok "Homebrew 包已就绪"

    # 链接 pg 命令到 PATH
    export PATH="$(brew --prefix postgresql@16)/bin:$PATH"

    # 启动服务
    brew services start postgresql@16 2>/dev/null || true
    brew services start redis 2>/dev/null || true

    # 等待 PG 就绪
    info "等待 PostgreSQL 启动..."
    TIMEOUT=30; ELAPSED=0
    until pg_isready -q 2>/dev/null; do
        [ $ELAPSED -ge $TIMEOUT ] && err "PostgreSQL 启动超时"
        sleep 2; ELAPSED=$((ELAPSED+2))
    done
    ok "PostgreSQL 已就绪（localhost:5432）"

    # 等待 Redis 就绪
    info "等待 Redis 启动..."
    ELAPSED=0
    until redis-cli ping >/dev/null 2>&1; do
        [ $ELAPSED -ge $TIMEOUT ] && err "Redis 启动超时"
        sleep 1; ELAPSED=$((ELAPSED+1))
    done
    ok "Redis 已就绪（localhost:6379）"

    # 创建数据库和用户
    info "初始化 PostgreSQL 用户和数据库..."
    PG_USER="csuser"
    PG_PASS="cspass"
    PG_DB="customer_service"

    # 创建 role（忽略已存在错误）
    psql postgres -c "CREATE USER $PG_USER WITH PASSWORD '$PG_PASS';" 2>/dev/null || true
    psql postgres -c "CREATE DATABASE $PG_DB OWNER $PG_USER;" 2>/dev/null || true
    psql postgres -c "GRANT ALL PRIVILEGES ON DATABASE $PG_DB TO $PG_USER;" 2>/dev/null || true

    # 安装 pgvector 扩展（Homebrew 版本需要手动配置）
    PG_LIB="$(brew --prefix pgvector)/lib"
    PG_SHARE="$(brew --prefix postgresql@16)/share/postgresql@16/extension"
    PG_PKGLIB="$(pg_config --pkglibdir 2>/dev/null || echo "$PG_LIB")"

    # 复制扩展文件
    for f in "$PG_LIB"/vector.dylib 2>/dev/null; do
        [ -f "$f" ] && cp "$f" "$PG_PKGLIB/" 2>/dev/null || true
    done
    for f in "$(brew --prefix pgvector)/share/postgresql@16/extension/"*.{sql,control} 2>/dev/null; do
        [ -f "$f" ] && cp "$f" "$PG_SHARE/" 2>/dev/null || true
    done

    ok "PostgreSQL 初始化完成"

    # 更新 .env 中的连接串（Homebrew 模式下用本机认证）
    # 保持默认配置（localhost:5432）即可

else
    # ─── Docker 模式 ────────────────────────────────────────────────────────────
    step "启动 Docker 服务（PostgreSQL + Redis）"

    docker info >/dev/null 2>&1 || err "Docker daemon 未运行"
    info "docker compose up -d postgres redis..."
    docker compose up -d postgres redis

    info "等待 PostgreSQL 健康检查..."
    TIMEOUT=60; ELAPSED=0
    until docker compose exec -T postgres pg_isready -U csuser -d customer_service >/dev/null 2>&1; do
        [ $ELAPSED -ge $TIMEOUT ] && err "PostgreSQL 启动超时"
        printf "."; sleep 2; ELAPSED=$((ELAPSED+2))
    done
    echo ""; ok "PostgreSQL 已就绪"

    info "等待 Redis 健康检查..."
    ELAPSED=0
    until docker compose exec -T redis redis-cli ping >/dev/null 2>&1; do
        [ $ELAPSED -ge $TIMEOUT ] && err "Redis 启动超时"
        printf "."; sleep 2; ELAPSED=$((ELAPSED+2))
    done
    echo ""; ok "Redis 已就绪"
fi

# ── 6. 数据库迁移 ─────────────────────────────────────────────────────────────
step "初始化数据库"

info "执行迁移（建表 + pgvector 扩展）..."
"$VENV/bin/python" scripts/migrate_db.py
ok "数据库迁移完成"

# 检查是否已有数据
check_count() {
    local table="$1"
    if [ "$NO_DOCKER" = true ]; then
        PGPASSWORD=cspass psql -U csuser -d customer_service -tAc "SELECT COUNT(*) FROM $table;" 2>/dev/null | tr -d '[:space:]' || echo "0"
    else
        docker compose exec -T postgres psql -U csuser -d customer_service -tAc \
            "SELECT COUNT(*) FROM $table;" 2>/dev/null | tr -d '[:space:]' || echo "0"
    fi
}

DOC_COUNT=$(check_count "faq_documents")
ORDER_COUNT=$(check_count "orders")

if [ "${DOC_COUNT:-0}" -gt 0 ]; then
    info "FAQ 数据已存在（${DOC_COUNT} 条），跳过"
else
    info "导入 FAQ 知识库（生成向量嵌入，约 1-2 分钟）..."
    "$VENV/bin/python" scripts/seed_faq.py
    ok "FAQ 知识库导入完成（15 篇婚纱专业文档）"
fi

if [ "${ORDER_COUNT:-0}" -gt 0 ]; then
    info "演示订单已存在（${ORDER_COUNT} 条），跳过"
else
    info "导入演示订单数据..."
    "$VENV/bin/python" scripts/seed_orders.py
    ok "演示订单导入完成（6 个典型婚纱订单）"
fi

# ── 完成 ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   ✅ 安装完成！                              ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${RESET}"
echo -e "  下一步：${BOLD}bash start.sh$([ "$NO_DOCKER" = true ] && echo ' --no-docker' || echo '')${RESET}"
echo ""
