#!/usr/bin/env bash
# =============================================================================
# SentinelAI — Live SOC Monitor
# Usage:
#   ./scripts/soc_watch.sh              # watches backend.log
#   ./scripts/soc_watch.sh docker       # watches docker compose logs
#   ./scripts/soc_watch.sh audit        # polls SOC audit API every 5s
#   ./scripts/soc_watch.sh status       # one-shot SOC status snapshot
# =============================================================================

RED='\033[31m'; YELLOW='\033[33m'; GREEN='\033[32m'
CYAN='\033[36m'; BOLD='\033[1m'; RESET='\033[0m'

BASE="http://localhost:8000"
TOKEN="${ADMIN_TOKEN:-}"       # export ADMIN_TOKEN=eyJ... before running
LOG="${1:-log}"

header() { echo -e "\n${CYAN}${BOLD}▶ $*${RESET}"; }
ok()     { echo -e "${GREEN}  ✔  $*${RESET}"; }
warn()   { echo -e "${YELLOW}  ⚠  $*${RESET}"; }
err()    { echo -e "${RED}  ✘  $*${RESET}"; }

# ── Mode: docker ──────────────────────────────────────────────────────────────
if [[ "$LOG" == "docker" ]]; then
    header "Watching Docker Compose backend logs (Ctrl-C to exit)"
    echo "  SOC events are tagged: SOC daemon | soc_middleware"
    echo "  Filter: docker compose logs -f backend | grep -i 'soc\|blocked\|violation'"
    echo ""
    docker compose logs -f backend 2>&1 | grep --line-buffered -iE \
        "soc|blocked|violation|injection|brute|captcha|suspended|escalat|daemon|turnstile|jwt"
    exit 0
fi

# ── Mode: log (default) ───────────────────────────────────────────────────────
if [[ "$LOG" == "log" ]]; then
    LOGFILE="${ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || echo '.')}/backend.log"
    if [[ ! -f "$LOGFILE" ]]; then
        err "Log file not found: $LOGFILE"
        echo "  Run: ./start.sh first"
        exit 1
    fi
    header "Tailing $LOGFILE — filtering SOC events (Ctrl-C to exit)"
    echo ""
    # Pretty-print JSON log lines, highlight SOC events
    tail -f "$LOGFILE" | while IFS= read -r line; do
        if echo "$line" | grep -qiE "soc|blocked|injection|brute|captcha|turnstile|escalat"; then
            echo -e "${YELLOW}${BOLD}${line}${RESET}"
        elif echo "$line" | grep -qiE "error|critical|fatal"; then
            echo -e "${RED}${line}${RESET}"
        elif echo "$line" | grep -qiE "warning"; then
            echo -e "${YELLOW}${line}${RESET}"
        else
            echo "$line"
        fi
    done
    exit 0
fi

# ── Remaining modes require ADMIN_TOKEN ──────────────────────────────────────
if [[ -z "$TOKEN" ]]; then
    err "ADMIN_TOKEN environment variable not set."
    echo ""
    echo "  Get a token by logging in as admin:"
    echo "    curl -s -X POST http://localhost:8000/api/v1/auth/login \\"
    echo "      -H 'Content-Type: application/json' \\"
    echo "      -d '{\"email\":\"admin@example.com\",\"password\":\"YourPass\"}'"
    echo "    # Copy 'access_token' from response"
    echo ""
    echo "  Then run:"
    echo "    export ADMIN_TOKEN=<token>"
    echo "    ./scripts/soc_watch.sh status"
    exit 1
fi

api() {
    curl -s -H "Authorization: Bearer $TOKEN" "${BASE}$1"
}

# ── Mode: status ─────────────────────────────────────────────────────────────
if [[ "$LOG" == "status" ]]; then
    header "SOC Daemon Status"
    api "/api/v1/admin/soc/status" | python3 -m json.tool 2>/dev/null || \
    api "/api/v1/admin/soc/status"

    echo ""
    header "Last 10 Audit Events"
    api "/api/v1/admin/soc/audit?limit=10" | python3 -c "
import json, sys
data = json.load(sys.stdin)
events = data.get('items', [])
for ev in events:
    ts       = str(ev.get('ts',''))[:19]
    ip       = ev.get('ip','?')
    etype    = ev.get('event_type','?')
    dec      = ev.get('decision', {}).get('decision','?')
    reason   = ev.get('decision', {}).get('reason','')[:70]
    action   = ev.get('action', {}).get('action','?')
    print(f'  {ts}  {ip:<15}  {etype:<28}  {action:<12}  {dec}  {reason}')
" 2>/dev/null || api "/api/v1/admin/soc/audit?limit=10"

    echo ""
    header "Blocked IPs"
    api "/api/v1/admin/soc/blocked" | python3 -c "
import json, sys
data = json.load(sys.stdin)
items = data.get('items', [])
if not items:
    print('  (none)')
for b in items:
    print(f\"  🔴  {b.get('ip','?')}  blocked_at={str(b.get('blocked_at',''))[:19]}  reason={b.get('reason','?')[:80]}\")
" 2>/dev/null || api "/api/v1/admin/soc/blocked"
    exit 0
fi

# ── Mode: audit (live polling) ───────────────────────────────────────────────
if [[ "$LOG" == "audit" ]]; then
    header "Live SOC audit poll every 5s (Ctrl-C to exit)"
    LAST_TS=""
    while true; do
        RAW=$(api "/api/v1/admin/soc/audit?limit=5")
        NEW=$(echo "$RAW" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for ev in data.get('items', []):
    ts       = str(ev.get('ts',''))[:19]
    ip       = ev.get('ip','?')
    etype    = ev.get('event_type','?')
    action   = ev.get('action', {}).get('action','?')
    severity = ''
    dets     = ev.get('findings', {}).get('detections', [])
    if dets:
        severity = max((d.get('severity','LOW') for d in dets), default='LOW')
    reason   = ev.get('decision', {}).get('reason','')[:60]
    color    = '\033[31m' if 'BLOCK' in action else ('\033[33m' if 'CHALLENGED' in action or 'SUSPENDED' in action else '')
    reset    = '\033[0m'
    print(f'{color}  {ts}  {ip:<15}  {etype:<28}  {action:<12}  [{severity:<8}]  {reason}{reset}')
" 2>/dev/null)
        if [[ -n "$NEW" ]]; then
            echo "$NEW"
        fi
        sleep 5
    done
    exit 0
fi

echo "Usage: $0 [log|docker|status|audit]"
echo "  log    — tail backend.log (default), highlight SOC events"
echo "  docker — follow docker compose backend logs"
echo "  status — one-shot SOC status snapshot (requires ADMIN_TOKEN)"
echo "  audit  — live poll SOC audit log every 5s (requires ADMIN_TOKEN)"
exit 1
