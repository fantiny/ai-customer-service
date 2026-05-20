#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# 缘梦婚纱 AI 客服系统 — 一键启动脚本
# 用法：bash start.sh [--no-docker]
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── 颜色 ─────────────────────────────────────────────────────────────────────
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

# ── 参数解析 ──────────────────────────────────────────────────────────────────
NO_DOCKER=false
for arg in "$@"; do
    [ "$arg" = "--no-docker" ] && NO_DOCKER=true
done

# ── PID 文件 ──────────────────────────────────────────────────────────────────
PIDS_DIR="$ROOT/.pids"
mkdir -p "$PIDS_DIR"
BACKEND_PID_FILE="$PIDS_DIR/backend.pid"
FRONTEND_PID_FILE="$PIDS_DIR/frontend.pid"
BACKEND_LOG="$ROOT/logs/backend.log"
FRONTEND_LOG="$ROOT/logs/frontend.log"
mkdir -p "$ROOT/logs"

# ── 清理函数 ──────────────────────────────────────────────────────────────────
stop_services() {
    echo -e "\n${YELLOW}  正在停止服务...${RESET}"
    if [ -f "$BACKEND_PID_FILE" ]; then
        kill "$(cat "$BACKEND_PID_FILE")" 2>/dev/null && ok "后端已停止" || true
        rm -f "$BACKEND_PID_FILE"
    fi
    if [ -f "$FRONTEND_PID_FILE" ]; then
        kill "$(cat "$FRONTEND_PID_FILE")" 2>/dev/null && ok "前端已停止" || true
        rm -f "$FRONTEND_PID_FILE"
    fi
}
trap stop_services EXIT INT TERM

echo -e "${BOLD}${CYAN}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   缘梦婚纱 · AI 客服系统 · 一键启动         ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${RESET}"

# ── 前置检查 ──────────────────────────────────────────────────────────────────
step "前置检查"

[ -f "$ROOT/.env" ] || err "缺少 .env 文件，请先运行：bash install.sh"
[ -d "$ROOT/.venv" ] || err "缺少 .venv，请先运行：bash install.sh"
[ -d "$ROOT/workspace/node_modules" ] || err "缺少 node_modules，请先运行：bash install.sh"

ok "前置检查通过"

# ── 1. 基础服务 ───────────────────────────────────────────────────────────────
# 自动检测：Docker daemon 不可用时自动切换 Homebrew 模式
if [ "$NO_DOCKER" = false ]; then
    if ! curl -sf --unix-socket /Users/jay/.docker/run/docker.sock \
         'http://localhost/v1.41/_ping' --max-time 3 >/dev/null 2>&1 2>/dev/null; then
        warn "Docker daemon 不可达，自动切换为 Homebrew 模式"
        NO_DOCKER=true
    fi
fi

if [ "$NO_DOCKER" = true ]; then
    step "确保 Homebrew PostgreSQL + Redis 运行中"

    export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"

    if ! nc -z localhost 5432 2>/dev/null; then
        info "启动 PostgreSQL 16..."
        brew services start postgresql@16 2>/dev/null || true
        TIMEOUT=20; ELAPSED=0
        until nc -z localhost 5432 2>/dev/null; do
            [ $ELAPSED -ge $TIMEOUT ] && err "PostgreSQL 启动超时"
            sleep 2; ELAPSED=$((ELAPSED+2))
        done
    fi

    if ! nc -z localhost 6379 2>/dev/null; then
        info "启动 Redis..."
        brew services start redis 2>/dev/null || true
        TIMEOUT=10; ELAPSED=0
        until nc -z localhost 6379 2>/dev/null; do
            [ $ELAPSED -ge $TIMEOUT ] && err "Redis 启动超时"
            sleep 1; ELAPSED=$((ELAPSED+1))
        done
    fi

    ok "PostgreSQL (5432) + Redis (6379) 已运行（Homebrew）"

else
    step "确保 Docker 服务运行中"

    if ! nc -z localhost 5432 2>/dev/null; then
        info "启动 PostgreSQL + Redis 容器..."
        docker compose up -d postgres redis

        TIMEOUT=60; ELAPSED=0
        until nc -z localhost 5432 2>/dev/null && nc -z localhost 6379 2>/dev/null; do
            [ $ELAPSED -ge $TIMEOUT ] && err "Docker 服务启动超时（${TIMEOUT}s）"
            printf "."; sleep 2; ELAPSED=$((ELAPSED+2))
        done
        echo ""
    fi

    ok "PostgreSQL (5432) + Redis (6379) 已运行（Docker）"
fi

# ── 2. 停止已有进程 ───────────────────────────────────────────────────────────
step "清理已有进程"

if [ -f "$BACKEND_PID_FILE" ]; then
    OLD_PID=$(cat "$BACKEND_PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" && info "已停止旧后端进程 (PID $OLD_PID)"
    fi
    rm -f "$BACKEND_PID_FILE"
fi

if [ -f "$FRONTEND_PID_FILE" ]; then
    OLD_PID=$(cat "$FRONTEND_PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" && info "已停止旧前端进程 (PID $OLD_PID)"
    fi
    rm -f "$FRONTEND_PID_FILE"
fi

# 释放端口
for PORT in 8000 3000; do
    OCCUPANT=$(lsof -ti ":$PORT" 2>/dev/null || true)
    if [ -n "$OCCUPANT" ]; then
        kill "$OCCUPANT" 2>/dev/null && info "已释放端口 $PORT (PID $OCCUPANT)" || true
    fi
done

sleep 1
ok "端口清理完成"

# ── 3. 启动后端 ───────────────────────────────────────────────────────────────
step "启动后端（FastAPI + LangGraph + Socket.io）"

info "日志输出至：logs/backend.log"
"$ROOT/.venv/bin/uvicorn" \
    src.ai_customer_service.app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --reload-dir src \
    > "$BACKEND_LOG" 2>&1 &

BACKEND_PID=$!
echo "$BACKEND_PID" > "$BACKEND_PID_FILE"
info "后端进程 PID: $BACKEND_PID"

# 等待后端就绪
info "等待后端启动..."
TIMEOUT=30; ELAPSED=0
until curl -sf http://localhost:8000/health >/dev/null 2>&1; do
    if [ $ELAPSED -ge $TIMEOUT ]; then
        warn "后端启动超时，最近日志："
        tail -20 "$BACKEND_LOG" | sed 's/^/    /'
        err "后端启动失败，请检查 logs/backend.log"
    fi
    # 检查进程是否还在
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        warn "后端进程意外退出，最近日志："
        tail -20 "$BACKEND_LOG" | sed 's/^/    /'
        err "后端启动失败"
    fi
    printf "."
    sleep 1; ELAPSED=$((ELAPSED+1))
done
echo ""
ok "后端已就绪 → http://localhost:8000"
ok "API 文档  → http://localhost:8000/docs"

# ── 4. 启动前端 ───────────────────────────────────────────────────────────────
step "启动前端（React + Vite）"

info "日志输出至：logs/frontend.log"
npm run dev --prefix "$ROOT/workspace" \
    > "$FRONTEND_LOG" 2>&1 &

FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$FRONTEND_PID_FILE"
info "前端进程 PID: $FRONTEND_PID"

# 等待前端就绪
info "等待前端编译..."
TIMEOUT=40; ELAPSED=0
until grep -q "Local\|localhost" "$FRONTEND_LOG" 2>/dev/null; do
    if [ $ELAPSED -ge $TIMEOUT ]; then
        warn "前端启动超时，最近日志："
        tail -10 "$FRONTEND_LOG" | sed 's/^/    /'
        err "前端启动失败，请检查 logs/frontend.log"
    fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        err "前端进程意外退出"
    fi
    printf "."
    sleep 1; ELAPSED=$((ELAPSED+1))
done
echo ""

# 获取实际端口
FRONTEND_PORT=$(grep -oE 'localhost:[0-9]+' "$FRONTEND_LOG" | head -1 | cut -d: -f2 || echo "3000")
ok "前端已就绪 → http://localhost:${FRONTEND_PORT}"

# ── 完成 ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}"
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║   🚀 系统已启动！                                       ║"
echo "  ║                                                          ║"
printf "  ║   前端地址：http://localhost:%-28s║\n" "${FRONTEND_PORT}/"
echo "  ║     ├── 客户视角（发送消息测试 AI）                      ║"
echo "  ║     └── 智能工作台（HITL 审批 / 人工接管）               ║"
echo "  ║                                                          ║"
echo "  ║   后端地址：http://localhost:8000                        ║"
echo "  ║     └── API 文档：http://localhost:8000/docs             ║"
echo "  ║                                                          ║"
echo "  ║   按 Ctrl+C 停止所有服务                                 ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# ── 实时日志 tail ──────────────────────────────────────────────────────────────
echo -e "${DIM}  ── 后端实时日志 (Ctrl+C 退出) ──${RESET}"
tail -f "$BACKEND_LOG" &
TAIL_PID=$!
trap "kill $TAIL_PID 2>/dev/null; stop_services" EXIT INT TERM
wait
