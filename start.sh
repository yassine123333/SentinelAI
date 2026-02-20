#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════╗
# ║           SentinelAI — Dev Stack Launcher               ║
# ╚══════════════════════════════════════════════════════════╝
# Usage:
#   ./start.sh          → start everything, then tail logs for 8 s
#   ./start.sh --stop   → stop all services
#   ./start.sh --status → show service status
#   ./start.sh --logs   → follow backend.log (Ctrl-C to exit)

set -euo pipefail

# ── Colours ────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✔  $*${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠  $*${RESET}"; }
err()  { echo -e "${RED}  ✘  $*${RESET}"; }
step() { echo -e "\n${CYAN}${BOLD}▶ $*${RESET}"; }
info() { echo -e "     $*"; }

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV="$ROOT_DIR/.venv/bin/activate"

MONGO_NAME="sentinel-mongo"
NEO4J_NAME="sentinel-neo4j"
MONGO_PORT=27017
NEO4J_BOLT=7687
NEO4J_HTTP=7474
BACKEND_PORT=8000

# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

wait_for_port() {
    local host=$1 port=$2 name=$3 max=${4:-30}
    local i=0
    printf "     Waiting for %s" "$name"
    while ! nc -z "$host" "$port" 2>/dev/null; do
        ((i++))
        if [ $i -ge $max ]; then
            echo ""
            err "$name did not become reachable on :$port after ${max}s"
            return 1
        fi
        printf "."
        sleep 1
    done
    echo ""
    ok "$name ready on :$port"
}

docker_available() {
    command -v docker &>/dev/null && docker info &>/dev/null 2>&1
}

container_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^$1$"
}

container_exists() {
    docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^$1$"
}

brew_service_running() {
    brew services list 2>/dev/null | grep -E "^$1\s+started" &>/dev/null
}

# ══════════════════════════════════════════════════════════════
# --stop flag
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# --logs flag
# ══════════════════════════════════════════════════════════════

if [[ "${1:-}" == "--logs" ]]; then
    LOG="$ROOT_DIR/backend.log"
    if [ ! -f "$LOG" ]; then
        err "Log file not found: $LOG"
        info "Run ./start.sh first to start the backend."
        exit 1
    fi
    echo -e "\n${CYAN}${BOLD}Tailing $LOG  (Ctrl-C to exit)${RESET}\n"
    tail -f "$LOG"
    exit 0
fi

if [[ "${1:-}" == "--stop" ]]; then
    step "Stopping services"

    # Docker containers
    if docker_available; then
        for name in "$MONGO_NAME" "$NEO4J_NAME"; do
            if container_running "$name"; then
                docker stop "$name" >/dev/null && ok "Stopped Docker container: $name"
            fi
        done
    fi

    # Homebrew services
    if command -v brew &>/dev/null; then
        brew_service_running mongodb-community && brew services stop mongodb-community && ok "Stopped MongoDB (Homebrew)"
        brew_service_running neo4j && brew services stop neo4j && ok "Stopped Neo4j (Homebrew)"
    fi

    # Backend
    if [ -f "$ROOT_DIR/.backend.pid" ]; then
        PID=$(cat "$ROOT_DIR/.backend.pid")
        kill "$PID" 2>/dev/null && ok "Stopped FastAPI (pid $PID)" || warn "FastAPI was not running"
        rm -f "$ROOT_DIR/.backend.pid"
    else
        pkill -f "uvicorn main:app" 2>/dev/null && ok "Stopped FastAPI" || warn "FastAPI was not running"
    fi
    exit 0
fi

# ══════════════════════════════════════════════════════════════
# --status flag
# ══════════════════════════════════════════════════════════════

if [[ "${1:-}" == "--status" ]]; then
    echo -e "\n${BOLD}SentinelAI — Service Status${RESET}"
    echo "────────────────────────────────"
    nc -z localhost "$MONGO_PORT" 2>/dev/null  && ok "MongoDB    :$MONGO_PORT  (running)" || err "MongoDB    :$MONGO_PORT  (stopped)"
    nc -z localhost "$NEO4J_BOLT" 2>/dev/null  && ok "Neo4j      :$NEO4J_BOLT (running)" || warn "Neo4j      :$NEO4J_BOLT (stopped) — agent_02 uses fallback"
    nc -z localhost "$BACKEND_PORT" 2>/dev/null && ok "FastAPI    :$BACKEND_PORT (running)" || err "FastAPI    :$BACKEND_PORT (stopped)"
    echo ""
    exit 0
fi

# ══════════════════════════════════════════════════════════════
# START
# ══════════════════════════════════════════════════════════════

echo -e "\n${BOLD}${CYAN}╔══════════════════════════════════════╗"
echo -e "║       SentinelAI  Dev Stack          ║"
echo -e "╚══════════════════════════════════════╝${RESET}\n"

# ── 1. Ensure Docker is available (try to launch it) ────────
step "Docker"

if ! command -v docker &>/dev/null; then
    warn "Docker CLI not found — will try Homebrew instead"
    USE_DOCKER=false
elif docker info &>/dev/null 2>&1; then
    ok "Docker daemon is running"
    USE_DOCKER=true
else
    # Docker installed but daemon is not running → try to launch Docker Desktop
    warn "Docker daemon is not running — launching Docker Desktop..."
    open -a Docker 2>/dev/null || true
    printf "     Waiting for Docker to start (up to 60s)"
    for i in $(seq 1 60); do
        if docker info &>/dev/null 2>&1; then
            echo ""
            ok "Docker Desktop is now running"
            break
        fi
        printf "."
        sleep 1
        if [ "$i" -eq 60 ]; then
            echo ""
            warn "Docker didn't start in time — will try Homebrew instead"
        fi
    done
    docker info &>/dev/null 2>&1 && USE_DOCKER=true || USE_DOCKER=false
fi

# ── 2. MongoDB ──────────────────────────────────────────────
step "MongoDB (port $MONGO_PORT)"

if nc -z localhost "$MONGO_PORT" 2>/dev/null; then
    ok "MongoDB already reachable on :$MONGO_PORT"

elif [ "$USE_DOCKER" = true ]; then
    if container_running "$MONGO_NAME"; then
        ok "MongoDB Docker container already running"
    elif container_exists "$MONGO_NAME"; then
        docker start "$MONGO_NAME" >/dev/null
        ok "MongoDB container restarted"
    else
        docker run -d \
            --name "$MONGO_NAME" \
            -p "$MONGO_PORT:27017" \
            --restart unless-stopped \
            -v sentinel-mongo-data:/data/db \
            mongo:7 >/dev/null
        ok "MongoDB container created and started"
    fi
    wait_for_port localhost "$MONGO_PORT" "MongoDB"

elif command -v brew &>/dev/null && brew list mongodb-community &>/dev/null 2>&1; then
    brew services start mongodb-community >/dev/null 2>&1 && ok "MongoDB started via Homebrew"
    wait_for_port localhost "$MONGO_PORT" "MongoDB"

else
    err "MongoDB is not running and no way to start it was found."
    err "Options:"
    info "  a) Install Docker Desktop: https://docker.com"
    info "  b) brew install mongodb-community && brew services start mongodb-community"
    info "  c) Start MongoDB manually, then re-run this script"
    exit 1
fi

# ── 3. Neo4j ────────────────────────────────────────────────
step "Neo4j Knowledge Graph (bolt :$NEO4J_BOLT)"

NEO4J_PASS=$(grep -E '^NEO4J_PASSWORD=' "$BACKEND_DIR/.env" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "12345678")
NEO4J_USER_VAL=$(grep -E '^NEO4J_USER=' "$BACKEND_DIR/.env" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "neo4j")

NEO4J_STARTED=false

if nc -z localhost "$NEO4J_BOLT" 2>/dev/null; then
    ok "Neo4j already reachable on :$NEO4J_BOLT"
    NEO4J_STARTED=true

elif [ "$USE_DOCKER" = true ]; then
    if container_running "$NEO4J_NAME"; then
        ok "Neo4j Docker container already running"
        NEO4J_STARTED=true
    elif container_exists "$NEO4J_NAME"; then
        docker start "$NEO4J_NAME" >/dev/null
        ok "Neo4j container restarted"
        NEO4J_STARTED=true
    else
        docker run -d \
            --name "$NEO4J_NAME" \
            -p "$NEO4J_HTTP:7474" \
            -p "$NEO4J_BOLT:7687" \
            --restart unless-stopped \
            -v sentinel-neo4j-data:/data \
            -e NEO4J_AUTH="${NEO4J_USER_VAL}/${NEO4J_PASS}" \
            neo4j:5 >/dev/null
        ok "Neo4j container created and started"
        NEO4J_STARTED=true
    fi
    wait_for_port localhost "$NEO4J_BOLT" "Neo4j" 60

elif command -v brew &>/dev/null && brew list neo4j &>/dev/null 2>&1; then
    brew services start neo4j >/dev/null 2>&1 && ok "Neo4j started via Homebrew"
    wait_for_port localhost "$NEO4J_BOLT" "Neo4j" 60
    NEO4J_STARTED=true

else
    warn "Neo4j not found — Agent 02 will use Groq fallback (no knowledge graph)"
    info "  To enable Neo4j: start Docker Desktop, then re-run ./start.sh"
fi

# ── 4. Python venv ──────────────────────────────────────────
step "Python virtual environment"
if [ ! -f "$VENV" ]; then
    err "venv not found at $VENV"
    info "Run: python -m venv .venv && source .venv/bin/activate && pip install -r backend/requirements.txt"
    exit 1
fi
# shellcheck source=/dev/null
source "$VENV"
ok "venv activated ($(python --version))"

# ── 5. FastAPI backend ──────────────────────────────────────
step "FastAPI backend (port $BACKEND_PORT)"

# Kill any stale process on same port
if lsof -ti tcp:"$BACKEND_PORT" &>/dev/null; then
    warn "Port $BACKEND_PORT in use — killing existing process"
    lsof -ti tcp:"$BACKEND_PORT" | xargs kill -9 2>/dev/null || true
    sleep 1
fi

info "Logs → $ROOT_DIR/backend.log"
cd "$BACKEND_DIR"
nohup uvicorn main:app \
    --host 0.0.0.0 \
    --port "$BACKEND_PORT" \
    --reload \
    --log-level info \
    > "$ROOT_DIR/backend.log" 2>&1 &

BACKEND_PID=$!
echo "$BACKEND_PID" > "$ROOT_DIR/.backend.pid"
wait_for_port localhost "$BACKEND_PORT" "FastAPI backend" 30

# Show recent startup output so errors are immediately visible
echo ""
echo -e "  ${BOLD}── Last startup log lines ──────────────────────────────${RESET}"
tail -n 8 "$ROOT_DIR/backend.log" 2>/dev/null | sed 's/^/  /'
echo -e "  ${BOLD}────────────────────────────────────────────────────────${RESET}"

# ── Summary ─────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}══════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  SentinelAI is running!${RESET}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════${RESET}"
echo ""
echo -e "  ${BOLD}Backend API${RESET}   http://localhost:$BACKEND_PORT"
echo -e "  ${BOLD}API Docs   ${RESET}   http://localhost:$BACKEND_PORT/api/docs  (debug mode only)"
echo -e "  ${BOLD}MongoDB    ${RESET}   mongodb://localhost:$MONGO_PORT"
if [ "$NEO4J_STARTED" = true ]; then
echo -e "  ${BOLD}Neo4j Bolt ${RESET}   bolt://localhost:$NEO4J_BOLT"
echo -e "  ${BOLD}Neo4j UI   ${RESET}   http://localhost:$NEO4J_HTTP"
else
echo -e "  ${YELLOW}Neo4j      ${RESET}   not running (agent_02 using Groq fallback)"
fi
echo ""
echo -e "  ${CYAN}Frontend${RESET}    cd frontend && npm run dev"
echo ""
echo -e "  Logs:     ${CYAN}./start.sh --logs${RESET}   (live tail, Ctrl-C to exit)"
echo -e "  Stop:     ${CYAN}./start.sh --stop${RESET}"
echo -e "  Status:   ${CYAN}./start.sh --status${RESET}"
echo ""
