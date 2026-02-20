"""
daemon.py — SOC Security Daemon: always-on background monitor.

Embedded in the FastAPI process as an asyncio background task.
Every SOC_POLL_INTERVAL seconds (default: 10s):

  1. Drain all FastAPI request events from the in-process queue
  2. Poll MongoDB system.profile for slow queries / injection probes
  3. Tail Nginx access log (if NGINX_LOG_PATH is set and accessible)
  4. Heuristic threat detection per IP (rate abuse, brute-force, injection, scanners)
  5. For HIGH/CRITICAL threats → run Groq LLM reasoning in thread executor
  6. Apply progressive intervention: MONITOR → CAPTCHA → SUSPEND → BLOCK
  7. Persist all decisions + full reasoning chains to MongoDB for audit

Environment variables (all optional, sane defaults):
  SOC_POLL_INTERVAL      Seconds between ticks (default: 10)
  SOC_RATE_WINDOW        Sliding window in seconds for rate tracking (default: 60)
  SOC_RATE_THRESHOLD     Requests in window before flagging (default: 30)
  SOC_AUTH_FAIL_THRESH   Auth failures before brute-force alert (default: 5)
  SOC_UA_ROTATION_THRESH Distinct User-Agents per IP before flagging (default: 3)
  SOC_MAX_WORKERS        Thread executor workers for sync LLM calls (default: 2)
  NGINX_LOG_PATH         Nginx access log path (default: /var/log/nginx/access.log)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

POLL_INTERVAL: float = float(os.environ.get("SOC_POLL_INTERVAL", "10"))
NGINX_LOG_PATH: str = os.environ.get("NGINX_LOG_PATH", "/var/log/nginx/access.log")
MAX_EXECUTOR_WORKERS: int = int(os.environ.get("SOC_MAX_WORKERS", "2"))

RATE_LIMIT_WINDOW_SEC: int = int(os.environ.get("SOC_RATE_WINDOW", "60"))
RATE_LIMIT_THRESHOLD: int = int(os.environ.get("SOC_RATE_THRESHOLD", "30"))
AUTH_FAIL_THRESHOLD: int = int(os.environ.get("SOC_AUTH_FAIL_THRESH", "5"))
UA_ROTATION_THRESHOLD: int = int(os.environ.get("SOC_UA_ROTATION_THRESH", "3"))

_SENSITIVE_PATHS = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/verify-email",
        "/api/v1/auth/resend-verification",
    }
)

_SCANNER_PATHS = frozenset(
    {
        "/wp-login.php",
        "/wp-admin",
        "/.env",
        "/.git/config",
        "/phpmyadmin",
        "/shell.php",
        "/xmlrpc.php",
        "/admin.php",
        "/.well-known/acme-challenge",
        "/actuator/health",
        "/config.php",
        "/setup.php",
    }
)

# Injection patterns matched against the raw request path
_INJECTION_RE = [
    re.compile(r'%24(gt|lt|ne|where|regex|in|nin)', re.IGNORECASE),  # URL-encoded $
    re.compile(r'\$where|\$gt|\$lt|\$ne', re.IGNORECASE),
    re.compile(r'<script\b|javascript:|on\w+\s*=', re.IGNORECASE),
    re.compile(r"'\s*(or|and)\s+'?\d+'?\s*=\s*'?\d", re.IGNORECASE),
    re.compile(r'union\s+select|select\s+.*\s+from', re.IGNORECASE),
]

# Severity ordering for throttling Groq API calls
_SEV_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


class SecurityDaemon:
    """
    Always-on background security monitor embedded in FastAPI.

    Usage:
        daemon = SecurityDaemon()
        await daemon.start()    # in lifespan startup
        await daemon.stop()     # in lifespan shutdown
    """

    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        self._executor = ThreadPoolExecutor(
            max_workers=MAX_EXECUTOR_WORKERS,
            thread_name_prefix="soc-worker",
        )

        # Nginx log cursor (mutable list acts as pointer shared with executor)
        self._nginx_pos: list[int] = [0]

        # MongoDB profiler timestamp cursor
        self._mongo_ts: datetime = datetime.now(timezone.utc)

        # Per-IP sliding window tracking (in-memory, reset on daemon restart)
        # These are complementary to MongoDB state — fast lookups without DB I/O
        self._ip_req_times: defaultdict[str, list[float]] = defaultdict(list)
        self._ip_auth_fails: defaultdict[str, int] = defaultdict(int)
        self._ip_user_agents: defaultdict[str, set[str]] = defaultdict(set)

        # Hard-blocked IPs loaded from MongoDB on startup
        # Checked before processing to skip already-blocked IPs
        self._hard_blocked: set[str] = set()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Initialise and start the daemon. Must be called after MongoDB is connected.
        """
        from .collectors import enable_mongo_profiling
        from .persistence import create_indexes, load_blocked_ips
        from .blocker import _blocked_ips as _mem_blocked

        await create_indexes()
        self._hard_blocked = await load_blocked_ips()
        # Sync loaded IPs into the in-memory blocker set so the CLI tool also
        # knows about them without a round-trip
        _mem_blocked.update(self._hard_blocked)
        await enable_mongo_profiling()

        self._running = True
        self._task = asyncio.create_task(self._loop(), name="soc-daemon")

        logger.info(
            "SOC daemon started — poll=%.0fs | workers=%d | blocked=%d IPs loaded",
            POLL_INTERVAL,
            MAX_EXECUTOR_WORKERS,
            len(self._hard_blocked),
        )

    async def stop(self) -> None:
        """Gracefully cancel the background task and shut down the executor."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._executor.shutdown(wait=False)
        logger.info("SOC daemon stopped.")

    # ── Main Loop ─────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("SOC daemon tick error: %s", exc, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL)

    async def _tick(self) -> None:
        """One full monitoring cycle: collect → detect → reason → act."""
        from .collectors import collect_mongodb_events, collect_nginx_events, drain_events

        # 1. Collect from all sources in parallel
        fastapi_events, (mongo_events, new_mongo_ts), nginx_events = await asyncio.gather(
            drain_events(max_items=500),
            collect_mongodb_events(self._mongo_ts),
            collect_nginx_events(NGINX_LOG_PATH, self._nginx_pos, self._executor),
        )
        self._mongo_ts = new_mongo_ts

        all_events = fastapi_events + mongo_events + nginx_events
        if not all_events:
            return

        logger.debug(
            "SOC tick — events: total=%d fastapi=%d mongo=%d nginx=%d",
            len(all_events),
            len(fastapi_events),
            len(mongo_events),
            len(nginx_events),
        )

        # 2. MongoDB injection probes have no IP — log and skip
        for ev in mongo_events:
            if ev.extra.get("is_injection_probe"):
                logger.warning(
                    "SOC: DB-level injection probe — ns=%s millis=%d",
                    ev.extra.get("ns"),
                    ev.extra.get("millis", 0),
                )

        # 3. Per-IP threat detection
        now = asyncio.get_event_loop().time()
        suspicious: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

        for ev in all_events:
            if ev.ip in ("mongodb_internal", "", "unknown"):
                continue
            if ev.is_private_ip():
                continue
            self._track(ev, now)
            detections = self._detect(ev)
            if detections:
                suspicious[ev.ip].extend(detections)

        # 4. Reason + act for each suspicious IP (run concurrently)
        if suspicious:
            tasks = [
                self._handle_ip(ip, detections, all_events)
                for ip, detections in suspicious.items()
                if ip not in self._hard_blocked
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        # 5. Purge stale rate-limit window entries
        self._purge_windows(now)

    # ── Per-IP State Tracking ─────────────────────────────────────────────────

    def _track(self, ev, now: float) -> None:
        """Update in-memory sliding window counters for an IP."""
        self._ip_req_times[ev.ip].append(now)
        if ev.user_agent:
            self._ip_user_agents[ev.ip].add(ev.user_agent)
        if ev.status_code in (401, 403) and ev.path in _SENSITIVE_PATHS:
            self._ip_auth_fails[ev.ip] += 1

    def _purge_windows(self, now: float) -> None:
        """Remove timestamps outside the sliding window to cap memory usage."""
        cutoff = now - RATE_LIMIT_WINDOW_SEC
        for ip in list(self._ip_req_times.keys()):
            fresh = [t for t in self._ip_req_times[ip] if t > cutoff]
            if fresh:
                self._ip_req_times[ip] = fresh
            else:
                del self._ip_req_times[ip]

    # ── Heuristic Threat Detection ────────────────────────────────────────────

    def _detect(self, ev) -> list[dict[str, Any]]:
        """
        Check a single event against all heuristic rules.
        Returns a list of detection dicts (empty = clean event).
        """
        detections: list[dict[str, Any]] = []
        ip = ev.ip

        # --- Auth brute-force ---
        fails = self._ip_auth_fails.get(ip, 0)
        if fails >= AUTH_FAIL_THRESHOLD:
            detections.append(
                {
                    "type": "AUTH_BRUTE_FORCE",
                    "severity": "HIGH",
                    "detail": f"{fails} auth failures on {ev.path}",
                }
            )

        # --- Distributed rate-limit abuse on sensitive paths ---
        rate = len(self._ip_req_times.get(ip, []))
        if rate >= RATE_LIMIT_THRESHOLD and ev.path in _SENSITIVE_PATHS:
            detections.append(
                {
                    "type": "RATE_LIMIT_ABUSE",
                    "severity": "HIGH",
                    "detail": f"{rate} requests to {ev.path} within {RATE_LIMIT_WINDOW_SEC}s",
                }
            )

        # --- User-Agent rotation (VPN/proxy botnet) ---
        ua_count = len(self._ip_user_agents.get(ip, set()))
        if ua_count >= UA_ROTATION_THRESHOLD:
            detections.append(
                {
                    "type": "UA_ROTATION",
                    "severity": "MEDIUM",
                    "detail": f"{ua_count} distinct User-Agents from {ip}",
                }
            )

        # --- NoSQL / SQL injection probes in URL path ---
        if any(p.search(ev.path) for p in _INJECTION_RE):
            detections.append(
                {
                    "type": "INJECTION_PROBE",
                    "severity": "CRITICAL",
                    "detail": f"Injection pattern in path: {ev.path[:200]}",
                }
            )

        # --- Known scanner / exploit paths ---
        if ev.path in _SCANNER_PATHS:
            detections.append(
                {
                    "type": "SCANNER_PROBE",
                    "severity": "MEDIUM",
                    "detail": f"Known scanner path probed: {ev.path}",
                }
            )

        # --- 404 path-discovery storm ---
        if ev.status_code == 404 and rate >= 10:
            detections.append(
                {
                    "type": "PATH_DISCOVERY",
                    "severity": "LOW",
                    "detail": f"404 storm: {rate} requests, latest: {ev.path}",
                }
            )

        # --- Token replay: rejected Bearer token ---
        if ev.status_code == 401 and "bearer" in ev.extra.get("auth_scheme", "").lower():
            detections.append(
                {
                    "type": "TOKEN_REPLAY",
                    "severity": "HIGH",
                    "detail": f"Rejected Bearer token from {ip} on {ev.path}",
                }
            )

        # --- Vector DB exhaustion (high-frequency pipeline queries) ---
        if ev.path.startswith("/api/v1/pipeline") and rate >= RATE_LIMIT_THRESHOLD:
            detections.append(
                {
                    "type": "VECTOR_DB_EXHAUSTION",
                    "severity": "MEDIUM",
                    "detail": f"{rate} pipeline/search queries from {ip}",
                }
            )

        return detections

    # ── Per-IP Reasoning + Action ─────────────────────────────────────────────

    async def _handle_ip(
        self,
        ip: str,
        detections: list[dict[str, Any]],
        all_events,
    ) -> None:
        """Run LLM reasoning and apply progressive intervention for one IP."""
        from .progressive import evaluate_and_escalate

        findings = self._build_findings(ip, detections, all_events)

        max_severity = max(
            (d.get("severity", "LOW") for d in detections),
            key=lambda s: _SEV_ORDER.get(s, 0),
            default="LOW",
        )

        # Only invoke Groq for HIGH/CRITICAL to conserve free-tier quota.
        # LOW/MEDIUM are handled by the heuristic escalator directly.
        if max_severity in ("HIGH", "CRITICAL"):
            decision = await self._groq_reason(findings)
        else:
            decision = {
                "decision": "MONITOR",
                "reason": f"Heuristic ({max_severity}): {detections[0]['type']}",
                "fallback": True,
            }

        # Critical injection probes always escalate regardless of LLM output
        if any(d["type"] == "INJECTION_PROBE" for d in detections):
            decision["decision"] = "BLOCK"

        action = await evaluate_and_escalate(ip, findings, decision)

        if action.get("action") == "BLOCKED":
            self._hard_blocked.add(ip)
            logger.warning("SOC daemon: IP %s permanently blocked.", ip)

    def _build_findings(
        self,
        ip: str,
        detections: list[dict[str, Any]],
        all_events,
    ) -> dict[str, Any]:
        """Assemble the findings dict forwarded to the LLM reasoning agent."""
        ip_events = [e for e in all_events if e.ip == ip]
        return {
            "ip": ip,
            "event_count": len(ip_events),
            "sources": list({e.source for e in ip_events}),
            "detections": detections,
            "paths_accessed": list({e.path for e in ip_events})[:10],
            "status_codes": list({e.status_code for e in ip_events}),
            "unique_user_agents": list(self._ip_user_agents.get(ip, set()))[:5],
            "ua_rotation": len(self._ip_user_agents.get(ip, set())) >= UA_ROTATION_THRESHOLD,
            "request_rate": len(self._ip_req_times.get(ip, [])),
            "auth_failures": self._ip_auth_fails.get(ip, 0),
        }

    async def _groq_reason(self, findings: dict[str, Any]) -> dict[str, Any]:
        """
        Invoke the Groq reasoning agent (sync) in a thread executor.
        Maps daemon findings into the format expected by reasoning_agent().
        """
        from .agents import reasoning_agent

        # Map to the format the existing reasoning_agent expects
        wrapped = {
            "parsed_log": {
                "ip": findings["ip"],
                "paths": findings["paths_accessed"],
            },
            "identity": {
                "alert": findings["ua_rotation"],
                "ip_count": len(findings["unique_user_agents"]),
            },
            "threat_intel": {"is_malicious": False},
            "pattern": {
                "alert": findings["request_rate"] >= RATE_LIMIT_THRESHOLD,
                "request_count": findings["request_rate"],
            },
            "detections": findings["detections"],
            "auth_failures": findings["auth_failures"],
            "sources": findings["sources"],
        }

        loop = asyncio.get_event_loop()
        try:
            decision = await loop.run_in_executor(self._executor, reasoning_agent, wrapped)
            return decision
        except Exception as exc:
            logger.error("SOC daemon: Groq error for %s: %s", findings["ip"], exc)
            has_critical = any(
                d["severity"] == "CRITICAL" for d in findings["detections"]
            )
            return {
                "decision": "BLOCK" if has_critical else "MONITOR",
                "reason": f"Groq unavailable — fallback heuristic: {exc}",
                "fallback": True,
            }


# ── Module-Level Singleton ────────────────────────────────────────────────────

_daemon: SecurityDaemon | None = None


def get_daemon() -> SecurityDaemon:
    """Return (or create) the global SecurityDaemon singleton."""
    global _daemon
    if _daemon is None:
        _daemon = SecurityDaemon()
    return _daemon
