#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 缘梦婚纱 · 一键开发启动脚本
#
# 用法：
#   ./dev.sh            启动后端 + 前端（不重置数据库）
#   ./dev.sh --seed     迁移数据库 + 写入种子数据，再启动
#   ./dev.sh --stop     停止所有后台进程
#   ./dev.sh --logs     实时查看合并日志（Ctrl+C 退出，不影响服务）
#   ./dev.sh --status   显示各服务进程状态
#   ./dev.sh -h|--help  帮助
#
# 日志文件：
#   logs/backend.log    后端 (uvicorn + LangGraph)
#   logs/frontend.log   前端 (Vite dev server)
# ─────────────────────────────────────────────────────────────────────────────
set -eo pipefail

# ── 路径 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="$SCRIPT_DIR/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
PID_FILE="$LOG_DIR/.dev_pids"

BACKEND_PORT=8000
FRONTEND_PORT=3000

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}  ▸  $*${RESET}"; }
success() { echo -e "${GREEN}  ✓  $*${RESET}"; }
warn()    { echo -e "${YELLOW}  ⚠  $*${RESET}"; }
error()   { echo -e "${RED}  ✗  $*${RESET}" >&2; }
step()    { echo -e "\n${BOLD}${BLUE}══ $* ${RESET}"; }

# ── 工具函数：找端口上的所有 PID（安全，永不报错） ────────────────────────────
pids_on_port() {
  local port="$1"
  lsof -ti tcp:"$port" 2>/dev/null || true
}

kill_port() {
  local port="$1"
  local pids
  pids=$(pids_on_port "$port")
  if [ -n "$pids" ]; then
    echo "$pids" | xargs kill 2>/dev/null || true
    return 0
  fi
  return 1
}

# ── --stop ────────────────────────────────────────────────────────────────────
stop_all() {
  step "停止服务"
  if [ -f "$PID_FILE" ]; then
    while IFS= read -r pid; do
      [ -z "$pid" ] && continue
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null && info "已终止进程 $pid"
      fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
  # 兜底：按端口杀
  for port in $BACKEND_PORT $FRONTEND_PORT; do
    if kill_port "$port"; then
      info "已终止端口 $port 上的进程"
    fi
  done
  success "所有服务已停止"
}

# ── --logs ────────────────────────────────────────────────────────────────────
show_logs() {
  mkdir -p "$LOG_DIR"
  touch "$BACKEND_LOG" "$FRONTEND_LOG"
  echo -e "${BOLD}实时日志（Ctrl+C 退出，不影响后台进程）${RESET}"
  echo ""
  tail -f "$BACKEND_LOG" | sed "s/^/${CYAN}[backend] /" &
  local tail_b=$!
  tail -f "$FRONTEND_LOG" | sed "s/^/${GREEN}[frontend]/" &
  local tail_f=$!
  trap "kill $tail_b $tail_f 2>/dev/null; exit 0" INT TERM
  wait
}

# ── --status ──────────────────────────────────────────────────────────────────
show_status() {
  step "服务状态"
  local pids label
  for port in $BACKEND_PORT $FRONTEND_PORT; do
    pids=$(pids_on_port "$port" | head -1)
    label="后端 :$port"
    [ "$port" = "$FRONTEND_PORT" ] && label="前端 :$port"
    if [ -n "$pids" ]; then
      success "$label  （PID $pids）"
    else
      warn    "$label  未运行"
    fi
  done
  if pg_isready -h localhost -p 5432 -q 2>/dev/null; then
    success "PostgreSQL    :5432"
  else
    warn    "PostgreSQL    未就绪"
  fi
  if redis-cli ping 2>/dev/null | grep -q PONG; then
    success "Redis         :6379"
  else
    warn    "Redis         未就绪"
  fi
}

# ── 前置检查 ──────────────────────────────────────────────────────────────────
preflight() {
  step "前置检查"

  if ! pg_isready -h localhost -p 5432 -q 2>/dev/null; then
    error "PostgreSQL 未就绪（localhost:5432）"
    error "请先启动 PostgreSQL，例如：brew services start postgresql@16"
    exit 1
  fi
  success "PostgreSQL :5432"

  if ! redis-cli ping 2>/dev/null | grep -q PONG; then
    error "Redis 未就绪（localhost:6379）"
    error "请先启动 Redis，例如：brew services start redis"
    exit 1
  fi
  success "Redis :6379"

  if ! command -v uv >/dev/null 2>&1; then
    error "未找到 uv，请先安装：curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
  fi
  success "uv $(uv --version 2>/dev/null | head -1)"

  if ! command -v node >/dev/null 2>&1; then
    error "未找到 node，请先安装 Node.js"
    exit 1
  fi
  success "Node.js $(node --version)"

  if [ ! -f ".env" ]; then
    warn ".env 不存在，从 .env.example 复制"
    cp .env.example .env
  fi
  success ".env 就绪"

  if [ ! -d "workspace/node_modules" ]; then
    info "安装前端依赖（首次运行）..."
    npm --prefix workspace install --silent
  fi
  success "前端依赖就绪"
}

# ── 数据库初始化 ───────────────────────────────────────────────────────────────
db_seed() {
  step "数据库初始化"
  info "运行 migration..."
  uv run python scripts/migrate_db.py
  success "数据库表已创建/更新"

  info "写入种子数据..."
  uv run python scripts/seed_all.py
  success "种子数据已写入"
}

# ── 启动后端 ──────────────────────────────────────────────────────────────────
start_backend() {
  step "启动后端"

  if kill_port "$BACKEND_PORT"; then
    warn "端口 $BACKEND_PORT 已有旧进程，已终止，重启中..."
    sleep 1
  fi

  mkdir -p "$LOG_DIR"
  PYTHONPATH="$SCRIPT_DIR/src" uv run uvicorn \
    ai_customer_service.app.main:app \
    --host 0.0.0.0 \
    --port "$BACKEND_PORT" \
    --reload \
    --reload-dir src \
    --log-level info \
    > "$BACKEND_LOG" 2>&1 &
  local backend_pid=$!
  echo "$backend_pid" >> "$PID_FILE"

  info "等待后端就绪..."
  local i=0
  while [ $i -lt 30 ]; do
    if curl -sf "http://localhost:$BACKEND_PORT/health" >/dev/null 2>&1; then
      success "后端已启动  http://localhost:$BACKEND_PORT  (PID $backend_pid)"
      return 0
    fi
    sleep 0.5
    i=$((i + 1))
  done
  error "后端启动超时，请查看日志："
  error "  tail -f $BACKEND_LOG"
  exit 1
}

# ── 启动前端 ──────────────────────────────────────────────────────────────────
start_frontend() {
  step "启动前端"

  if kill_port "$FRONTEND_PORT"; then
    warn "端口 $FRONTEND_PORT 已有旧进程，已终止，重启中..."
    sleep 1
  fi

  mkdir -p "$LOG_DIR"
  npm --prefix workspace run dev \
    > "$FRONTEND_LOG" 2>&1 &
  local frontend_pid=$!
  echo "$frontend_pid" >> "$PID_FILE"

  info "等待前端就绪..."
  local i=0
  while [ $i -lt 40 ]; do
    if curl -sf "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1; then
      success "前端已启动  http://localhost:$FRONTEND_PORT  (PID $frontend_pid)"
      return 0
    fi
    sleep 0.5
    i=$((i + 1))
  done
  error "前端启动超时，请查看日志："
  error "  tail -f $FRONTEND_LOG"
  exit 1
}

# ── 完成提示 ──────────────────────────────────────────────────────────────────
print_summary() {
  local jwt_hint
  if grep -qE '^JWT_SECRET=.+' .env 2>/dev/null; then
    jwt_hint="${GREEN}✓ JWT 已配置（HS256）${RESET}"
  else
    jwt_hint="${YELLOW}⚠ JWT_SECRET 未设置，当前为访客模式${RESET}"
  fi

  echo ""
  echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}║         缘梦婚纱 · 开发环境已就绪                   ║${RESET}"
  echo -e "${BOLD}╠══════════════════════════════════════════════════════╣${RESET}"
  echo -e "║  ${CYAN}客户聊天界面${RESET}  http://localhost:$FRONTEND_PORT             ║"
  echo -e "║  ${CYAN}测试控制台  ${RESET}  http://localhost:$FRONTEND_PORT/test.html   ║"
  echo -e "║  ${CYAN}API 文档    ${RESET}  http://localhost:$BACKEND_PORT/docs          ║"
  echo -e "║  ${CYAN}健康检查    ${RESET}  http://localhost:$BACKEND_PORT/health        ║"
  echo -e "${BOLD}╠══════════════════════════════════════════════════════╣${RESET}"
  echo -e "║  $jwt_hint"
  echo -e "${BOLD}╠══════════════════════════════════════════════════════╣${RESET}"
  echo -e "║  ${YELLOW}./dev.sh --logs${RESET}   实时查看日志                    ║"
  echo -e "║  ${YELLOW}./dev.sh --stop${RESET}   停止所有服务                    ║"
  echo -e "║  ${YELLOW}./dev.sh --seed${RESET}   重置并重新写入测试数据           ║"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"

  if grep -qE '^JWT_SECRET=.+' .env 2>/dev/null; then
    echo ""
    info "测试用户直达链接："
    uv run python scripts/generate_token.py --list 2>/dev/null || true
  fi
}

# ── 主流程 ────────────────────────────────────────────────────────────────────
main() {
  local do_seed=0

  case "${1:-}" in
    --stop)    stop_all;    exit 0 ;;
    --logs)    show_logs;   exit 0 ;;
    --status)  show_status; exit 0 ;;
    -h|--help) usage;       exit 0 ;;
    --seed)    do_seed=1 ;;
    "")        do_seed=0 ;;
    *)
      error "未知参数：${1}"
      usage
      exit 1
      ;;
  esac

  echo ""
  echo -e "${BOLD}${BLUE}  缘梦婚纱 · AI 客服开发环境启动${RESET}"
  echo ""

  rm -f "$PID_FILE"
  mkdir -p "$LOG_DIR"

  preflight

  if [ "$do_seed" = "1" ]; then
    db_seed
  fi

  start_backend
  start_frontend
  print_summary
}

usage() {
  echo -e "${BOLD}用法：${RESET}"
  echo "  ./dev.sh            启动后端 + 前端（不覆盖数据库）"
  echo "  ./dev.sh --seed     迁移数据库 + 写入种子数据，再启动服务"
  echo "  ./dev.sh --stop     停止所有后台进程"
  echo "  ./dev.sh --logs     实时合并日志（Ctrl+C 退出，不影响服务）"
  echo "  ./dev.sh --status   显示各服务状态"
  echo "  ./dev.sh -h|--help  显示此帮助"
}

main "$@"
