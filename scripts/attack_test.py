#!/usr/bin/env python3
"""
SentinelAI — Blue Team Security Attack Test Suite
==================================================
Tests every SOC detection rule against the real running backend.
Run with:  python scripts/attack_test.py

Requirements:
  - Backend running locally: cd backend && uvicorn main:app --reload
    (or: ./start.sh)
  - DEBUG=true in backend/.env so Turnstile is skipped in dev
  - A valid admin JWT in ADMIN_TOKEN (get it by logging in as an admin user)
  - pip install requests (standard library used otherwise)

What each attack tests:
  [1] AUTH_BRUTE_FORCE   — 10+ failed logins from same IP
  [2] RATE_LIMIT_ABUSE   — 35+ requests to sensitive path in 60s
  [3] UA_ROTATION        — 4 distinct User-Agents from same IP
  [4] INJECTION_PROBE    — NoSQL ($where/$gt) and SQL (UNION SELECT) in URL
  [5] SCANNER_PROBE      — WordPress / phpMyAdmin / .env paths
  [6] PATH_DISCOVERY     — 15+ rapid 404s (directory brute-force)
  [7] TOKEN_REPLAY       — Invalid/expired Bearer token on protected route
  [8] XFF_SPOOFING       — X-Forwarded-For manipulation (should NOT affect rate limit)
  [9] XSS_IN_BODY        — <script> tag injected in JSON field
  [10] RATE_LIMIT_VERIFY — slowapi 429 enforcement on /login (10/min)
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

BASE = "http://localhost:8000"
ADMIN_TOKEN = ""           # Fill in after getting a JWT for an admin user
POLL_WAIT = 12             # Seconds to wait after attack before checking SOC (> daemon tick = 10s)

# Test credentials — register this account once so login attacks have a target
TEST_EMAIL = "blue_team_test@example.com"
TEST_PASS  = "Wrong_Pass_1234!"

# ── Helpers ───────────────────────────────────────────────────────────────────

class Color:
    RED    = "\033[31m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    CYAN   = "\033[36m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"

def section(title: str) -> None:
    print(f"\n{Color.CYAN}{Color.BOLD}{'='*60}{Color.RESET}")
    print(f"{Color.CYAN}{Color.BOLD}  {title}{Color.RESET}")
    print(f"{Color.CYAN}{Color.BOLD}{'='*60}{Color.RESET}")

def ok(msg: str)   -> None: print(f"{Color.GREEN}  ✔  {msg}{Color.RESET}")
def warn(msg: str) -> None: print(f"{Color.YELLOW}  ⚠  {msg}{Color.RESET}")
def err(msg: str)  -> None: print(f"{Color.RED}  ✘  {msg}{Color.RESET}")
def info(msg: str) -> None: print(f"     {msg}")

def req(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{BASE}{path}"
    resp = requests.request(method, url, timeout=10, **kwargs)
    return resp

def admin_get(path: str) -> dict | None:
    if not ADMIN_TOKEN:
        warn("ADMIN_TOKEN not set — skipping SOC audit check")
        return None
    resp = req("GET", path, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    if resp.status_code == 200:
        return resp.json()
    warn(f"Admin endpoint {path} returned {resp.status_code}: {resp.text[:200]}")
    return None

def wait_for_daemon(label: str = "") -> None:
    msg = f"Waiting {POLL_WAIT}s for SOC daemon tick{' ('+label+')' if label else ''}…"
    info(msg)
    time.sleep(POLL_WAIT)

def check_soc_for_ip(ip: str = "127.0.0.1") -> None:
    result = admin_get(f"/api/v1/admin/soc/ip/{ip}")
    if result:
        state = result.get("state") or {}
        level_name = state.get("level_name", "N/A")
        violations  = state.get("violations", 0)
        audit       = result.get("audit_events", [])
        last_event  = audit[0] if audit else {}
        print(f"\n  {Color.BOLD}SOC state for {ip}:{Color.RESET}")
        print(f"    Level:       {Color.YELLOW}{level_name}{Color.RESET}")
        print(f"    Violations:  {violations}")
        if last_event:
            print(f"    Last event:  {last_event.get('event_type','?')} — {last_event.get('action',{}).get('action','?')}")
            decision = last_event.get("decision", {})
            print(f"    LLM says:    {decision.get('decision','?')} — {decision.get('reason','?')}")

# ── Preflight ─────────────────────────────────────────────────────────────────

def preflight() -> bool:
    section("PREFLIGHT — Check backend is reachable")
    try:
        r = req("GET", "/api/health")
        if r.status_code == 200:
            ok(f"Backend alive: {r.json()}")
            return True
        err(f"Health check returned {r.status_code}")
        return False
    except requests.ConnectionError:
        err(f"Cannot connect to {BASE} — is the backend running?")
        err("Run: cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000")
        return False

# ── Attack 1 — Auth Brute Force ───────────────────────────────────────────────

def attack_brute_force() -> None:
    section("ATTACK 1 — AUTH_BRUTE_FORCE (10 failed logins)")
    info("Sending 10 wrong-password login attempts…")
    for i in range(1, 11):
        r = req("POST", "/api/v1/auth/login",
                json={"email": TEST_EMAIL, "password": f"WrongPass{i}!"},
                headers={"User-Agent": "Mozilla/5.0 BruteForce-Test"})
        status = r.status_code
        symbol = "✔" if status in (401, 422, 429, 503) else "?"
        info(f"  Attempt {i:02d}: HTTP {status} {symbol}")
        if status == 429:
            warn("  Hit slowapi rate limit (10/min) — expected")
            break
        time.sleep(0.2)

    wait_for_daemon("brute force")
    check_soc_for_ip()
    ok("Expected detection: AUTH_BRUTE_FORCE (HIGH) → ESCALATION_CHALLENGED/BLOCKED")

# ── Attack 2 — Rate Limit Abuse ───────────────────────────────────────────────

def attack_rate_abuse() -> None:
    section("ATTACK 2 — RATE_LIMIT_ABUSE (35 rapid requests to /login)")
    info("Sending 35 rapid requests to /api/v1/auth/login…")
    codes: dict[int, int] = {}
    for i in range(35):
        r = req("POST", "/api/v1/auth/login",
                json={"email": TEST_EMAIL, "password": "Wrong!"},
                headers={"User-Agent": "Python-RateAbuse/1.0"})
        codes[r.status_code] = codes.get(r.status_code, 0) + 1
        time.sleep(0.05)  # 50ms apart = burst
    for code, count in sorted(codes.items()):
        info(f"  HTTP {code}: {count}x")

    wait_for_daemon("rate abuse")
    check_soc_for_ip()
    ok("Expected detection: RATE_LIMIT_ABUSE (HIGH) + slowapi 429s")

# ── Attack 3 — User-Agent Rotation ───────────────────────────────────────────

def attack_ua_rotation() -> None:
    section("ATTACK 3 — UA_ROTATION (4 distinct User-Agents)")
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
        "python-requests/2.31.0",
        "curl/7.88.1",
        "Scrapy/2.11.0",
    ]
    info("Sending requests with rotating User-Agents…")
    for i, ua in enumerate(agents):
        r = req("POST", "/api/v1/auth/login",
                json={"email": TEST_EMAIL, "password": "Wrong!"},
                headers={"User-Agent": ua})
        info(f"  UA {i+1}: [{ua[:40]}…] → HTTP {r.status_code}")
        time.sleep(0.3)

    wait_for_daemon("UA rotation")
    check_soc_for_ip()
    ok("Expected detection: UA_ROTATION (MEDIUM)")

# ── Attack 4 — Injection Probes ───────────────────────────────────────────────

def attack_injection() -> None:
    section("ATTACK 4 — INJECTION_PROBE (NoSQL + SQL in URL path)")
    probes = [
        "/api/v1/auth/login?email[$gt]=",         # MongoDB $gt operator
        "/api/v1/auth/login?q=$where+this.x==1",  # $where operator
        "/api/v1/users?id=1'+UNION+SELECT+*+FROM+users--",  # SQL injection
        "/api/v1/report/x%24gt%3D1",              # URL-encoded $gt
        "/api/v1/search?q=<script>alert(1)</script>",  # XSS in path
        "/api/v1/data?q='+OR+'1'='1",             # SQL tautology
    ]
    info("Sending URL-based injection probes…")
    for probe in probes:
        r = req("GET", probe, headers={"User-Agent": "Mozilla/5.0 InjectionTest"})
        flag = "🔴 PROBE" if r.status_code in (400, 403, 404, 422) else "⚪"
        info(f"  {flag} {probe[:60]} → {r.status_code}")
        time.sleep(0.2)

    wait_for_daemon("injection")
    check_soc_for_ip()
    ok("Expected detection: INJECTION_PROBE (CRITICAL) → immediate BLOCK")

# ── Attack 5 — Scanner Probes ─────────────────────────────────────────────────

def attack_scanner() -> None:
    section("ATTACK 5 — SCANNER_PROBE (CMS / admin path scanning)")
    scanner_paths = [
        "/wp-login.php",
        "/wp-admin",
        "/.env",
        "/.git/config",
        "/phpmyadmin",
        "/shell.php",
        "/xmlrpc.php",
        "/admin.php",
        "/actuator/health",
        "/config.php",
    ]
    info("Probing known scanner/exploit paths…")
    for path in scanner_paths:
        r = req("GET", path, headers={"User-Agent": "Nuclei/2.9"})
        info(f"  {path:<35} → HTTP {r.status_code}")
        time.sleep(0.15)

    wait_for_daemon("scanner")
    check_soc_for_ip()
    ok("Expected detection: SCANNER_PROBE (MEDIUM) → MONITORING/CHALLENGED")

# ── Attack 6 — Path Discovery (404 Storm) ────────────────────────────────────

def attack_path_discovery() -> None:
    section("ATTACK 6 — PATH_DISCOVERY (15+ rapid 404s)")
    ghost_paths = [
        f"/api/v1/internal/secret-{i}" for i in range(15)
    ]
    info("Sending 15 requests to non-existent paths…")
    for path in ghost_paths:
        r = req("GET", path, headers={"User-Agent": "DirBuster/1.0"})
        info(f"  {path:<45} → {r.status_code}")
        time.sleep(0.1)

    wait_for_daemon("path discovery")
    check_soc_for_ip()
    ok("Expected detection: PATH_DISCOVERY (LOW)")

# ── Attack 7 — Token Replay ───────────────────────────────────────────────────

def attack_token_replay() -> None:
    section("ATTACK 7 — TOKEN_REPLAY (Expired/forged Bearer tokens)")
    # Forged token (wrong signature)
    fake_jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwicm9sZSI6ImFkbWluIiwiaWF0IjoxNTE2MjM5MDIyfQ."
        "FakeSig_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    )
    info("Sending 8 requests with invalid Bearer tokens to protected routes…")
    protected = [
        "/api/v1/history",
        "/api/v1/admin/runs",
        "/api/v1/admin/soc/status",
    ]
    for i in range(8):
        path = protected[i % len(protected)]
        r = req("GET", path,
                headers={
                    "Authorization": f"Bearer {fake_jwt}",
                    "User-Agent": "Mozilla/5.0 TokenReplay-Test",
                })
        info(f"  Attempt {i+1}: {path:<35} → HTTP {r.status_code}")
        time.sleep(0.2)

    wait_for_daemon("token replay")
    check_soc_for_ip()
    ok("Expected detection: TOKEN_REPLAY (HIGH) → MONITORING/CHALLENGED")

# ── Attack 8 — XFF Spoofing (now patched) ────────────────────────────────────

def attack_xff_spoofing() -> None:
    section("ATTACK 8 — X-Forwarded-For SPOOFING (should be IGNORED by fixed code)")
    info("Sending requests with spoofed X-Forwarded-For: 10.0.0.1")
    info("Our fix: XFF is only trusted from internal proxy IPs, not external clients.")
    for i in range(5):
        r = req("POST", "/api/v1/auth/login",
                json={"email": TEST_EMAIL, "password": "Wrong!"},
                headers={
                    "User-Agent": "Mozilla/5.0 XFF-Spoof",
                    "X-Forwarded-For": f"10.{i}.{i}.{i}",  # spoofed private IP
                })
        info(f"  Attempt {i+1}: XFF=10.{i}.{i}.{i} → HTTP {r.status_code}")
        time.sleep(0.2)

    ok("Expected: rate limit bucket uses REAL connection IP (127.0.0.1), not spoofed XFF")
    ok("The fix: _real_client_ip() only trusts XFF from internal proxy connections")

# ── Attack 9 — XSS in Request Body ───────────────────────────────────────────

def attack_xss_body() -> None:
    section("ATTACK 9 — XSS PAYLOAD in JSON body fields")
    xss_payloads = [
        {"email": "<script>alert('xss')</script>@evil.com", "password": "Test1234!"},
        {"email": "test@test.com", "password": "javascript:alert(1)"},
        {"email": "test\" onerror=\"alert(1)\"@x.com", "password": "A1!aaaa"},
    ]
    info("Sending XSS payloads in login body…")
    for payload in xss_payloads:
        r = req("POST", "/api/v1/auth/login",
                json=payload,
                headers={"User-Agent": "Mozilla/5.0 XSS-Test"})
        info(f"  Payload email=[{payload['email'][:40]}] → HTTP {r.status_code}")
        # Should be 422 (Pydantic validation) or 401 (auth failed, not XSS executed)
        if r.status_code == 422:
            ok("    Pydantic validation rejected the input (expected)")
        elif r.status_code in (401, 403):
            ok("    Auth failed — XSS payload was sanitised/rejected")
        time.sleep(0.2)

# ── Attack 10 — Rate Limit Enforcement ───────────────────────────────────────

def attack_ratelimit_enforcement() -> None:
    section("ATTACK 10 — RATE LIMIT ENFORCEMENT (verify 429 on /login after 10/min)")
    info("Sending 12 requests to /login — should see 429 after 10th…")
    saw_429 = False
    for i in range(12):
        r = req("POST", "/api/v1/auth/login",
                json={"email": TEST_EMAIL, "password": "Wrong!"},
                headers={"User-Agent": f"Mozilla/5.0 RateLimit-Test/{i}"})
        marker = "🔴 429!" if r.status_code == 429 else f"HTTP {r.status_code}"
        info(f"  Request {i+1:02d}: {marker}")
        if r.status_code == 429:
            saw_429 = True
            ok("  slowapi rate limit triggered correctly")
        time.sleep(0.1)

    if not saw_429:
        warn("No 429 seen — may already be blocked by SOC (403) or DEBUG rate limit differs")

# ── SOC Audit Report ──────────────────────────────────────────────────────────

def print_soc_report() -> None:
    section("SOC AUDIT REPORT — Last 20 events")
    result = admin_get("/api/v1/admin/soc/audit?limit=20")
    if not result:
        return

    events: list[dict[str, Any]] = result.get("items", [])
    total  = result.get("total", 0)
    info(f"Total audit events in DB: {total}")
    print()

    for ev in events[:20]:
        ts         = str(ev.get("ts", ""))[:19]
        ip         = ev.get("ip", "?")
        etype      = ev.get("event_type", "?")
        decision   = ev.get("decision", {})
        action_obj = ev.get("action", {})
        verdict    = decision.get("decision", "?")
        reason     = decision.get("reason", "")[:80]
        action     = action_obj.get("action", "?")

        color = Color.RED if "BLOCK" in action else (Color.YELLOW if "CHALLENGED" in action else Color.RESET)
        print(f"  {ts}  {ip:<15}  {etype:<28}  {color}{action:<12}{Color.RESET}  {verdict}  {reason}")

    section("BLOCKED IPs")
    blocked = admin_get("/api/v1/admin/soc/blocked")
    if blocked:
        ips = blocked.get("items", [])
        if ips:
            for b in ips:
                print(f"  🔴  {b.get('ip','?')}  — {b.get('reason','?')[:80]}")
        else:
            ok("No permanently blocked IPs yet")

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{Color.BOLD}{Color.CYAN}")
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   SentinelAI — Blue Team Attack Test Suite               ║")
    print("║   Tests all SOC detection rules against live backend     ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(Color.RESET)

    if not ADMIN_TOKEN:
        warn("ADMIN_TOKEN is empty — SOC audit checks will be skipped.")
        warn("Get a token: POST /api/v1/auth/login as an admin user, copy the access_token.")
        warn("Then set ADMIN_TOKEN = '...' at the top of this script.\n")

    if not preflight():
        sys.exit(1)

    # Run attacks in order
    attack_brute_force()
    attack_rate_abuse()
    attack_ua_rotation()
    attack_injection()
    attack_scanner()
    attack_path_discovery()
    attack_token_replay()
    attack_xff_spoofing()
    attack_xss_body()
    attack_ratelimit_enforcement()

    # Final audit report
    if ADMIN_TOKEN:
        print_soc_report()

    section("TEST COMPLETE")
    print(f"""
  {Color.BOLD}How to read the results:{Color.RESET}

  1. {Color.CYAN}Live backend logs{Color.RESET} (run in separate terminal):
       tail -f backend.log | python -m json.tool
     OR (Docker):
       docker compose logs -f backend

  2. {Color.CYAN}SOC audit dashboard{Color.RESET} (requires admin JWT):
       curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/soc/audit
       curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/soc/blocked
       curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/soc/status

  3. {Color.CYAN}Specific IP state{Color.RESET}:
       curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/soc/ip/127.0.0.1

  4. {Color.CYAN}Unblock your own IP after tests{Color.RESET}:
       curl -X POST -H "Authorization: Bearer $TOKEN" \\
            http://localhost:8000/api/v1/admin/soc/unblock/127.0.0.1

  5. {Color.CYAN}MongoDB direct (Atlas or local):{Color.RESET}
       db.soc_audit_log.find().sort({{ts:-1}}).limit(20).pretty()
       db.soc_blocked_ips.find().pretty()
       db.soc_ip_states.find().pretty()
""")


if __name__ == "__main__":
    main()
