"""
agents.py — SOC Multi-Agent Security System: Sub-Agent Definitions
==================================================================
Six sub-agents: Ingestion, Identity, ThreatIntel, Pattern, Reasoning, Action.

LLM backend : Groq — llama-3.1-8b-instant
              (blazing-fast inference, generous free tier)

Environment setup:
    export GROQ_API_KEY="your-groq-api-key-here"
    # Get a free key at https://console.groq.com

Rate-limit configuration (override via env vars):
    GROQ_RPM            Max requests per minute          (default: 30)
    GROQ_RPD            Max requests per day             (default: 14400)
    GROQ_MAX_RETRIES    Max retry attempts on 429/quota  (default: 4)
    GROQ_BURST          Max burst tokens in the bucket   (default: same as RPM)

Groq free-tier limits for llama-3.1-8b-instant (as of 2025):
    30 RPM  |  14,400 RPD  |  6,000 TPM  |  500,000 TPD
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import requests
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load .env from the same directory as this file
load_dotenv(Path(__file__).resolve().parent / ".env")

from groq import (
    Groq,
    RateLimitError,
    APIConnectionError,
    APIStatusError,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ===========================================================================
# Groq Rate Limiter — Dual Token Bucket (RPM + RPD) + Exponential Back-off
# ===========================================================================

class GroqRateLimiter:
    """
    Thread-safe dual token-bucket rate limiter for the Groq API.

    Groq enforces **three** independent quota axes simultaneously:
      • RPM  — requests per minute  (short-window burst control)
      • RPD  — requests per day     (long-window total cap)
      • TPM  — tokens per minute    (most binding on free tier!)

    All buckets must have a token available before a call is permitted.

    When the API returns HTTP 429 (``RateLimitError``) or a transient 5xx
    (``APIConnectionError`` / ``APIStatusError``), the limiter retries with
    full-jitter exponential back-off up to ``max_retries`` attempts, and
    honours any ``Retry-After`` header Groq provides.

    Usage
    -----
        result = limiter.call(client.chat.completions.create, **kwargs)

    Configuration (environment variables)
    --------------------------------------
    GROQ_RPM          Sustained requests-per-minute  (default 10 — conservative for free tier)
    GROQ_RPD          Sustained requests-per-day     (default 14400)
    GROQ_BURST        Burst capacity (RPM bucket)    (default = RPM)
    GROQ_MAX_RETRIES  Retry attempts on quota errors (default 6)
    GROQ_MIN_DELAY    Minimum seconds between calls  (default 3 — paces TPM usage)
    """

    def __init__(
        self,
        rpm: int | None = None,
        rpd: int | None = None,
        burst: int | None = None,
        max_retries: int | None = None,
        min_delay: float | None = None,
    ) -> None:
        self._rpm: int = rpm or int(os.environ.get("GROQ_RPM", 10))
        self._rpd: int = rpd or int(os.environ.get("GROQ_RPD", 14_400))
        self._max_retries: int = max_retries or int(os.environ.get("GROQ_MAX_RETRIES", 6))
        self._burst: int = burst or int(os.environ.get("GROQ_BURST", self._rpm))
        self._min_delay: float = min_delay if min_delay is not None else float(os.environ.get("GROQ_MIN_DELAY", 3.0))

        # ── RPM bucket ───────────────────────────────────────────────────
        # Refills at 1 token every (60 / rpm) seconds
        self._rpm_refill_interval: float = 60.0 / self._rpm
        self._rpm_tokens: float = float(self._burst)
        self._rpm_last_refill: float = time.monotonic()

        # ── RPD bucket ───────────────────────────────────────────────────
        # Refills at 1 token every (86400 / rpd) seconds
        self._rpd_refill_interval: float = 86_400.0 / self._rpd
        self._rpd_tokens: float = float(self._rpd)   # start with full daily quota
        self._rpd_last_refill: float = time.monotonic()

        # ── Minimum delay between calls (TPM pacing) ────────────────────
        self._last_call_time: float = 0.0

        self._lock = threading.Lock()

        logger.info(
            "GroqRateLimiter initialised — rpm=%d  rpd=%d  burst=%d  "
            "max_retries=%d  min_delay=%.1fs",
            self._rpm,
            self._rpd,
            self._burst,
            self._max_retries,
            self._min_delay,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refill_buckets(self) -> None:
        """Refill both token buckets proportional to elapsed wall time."""
        now = time.monotonic()

        # RPM bucket
        rpm_elapsed = now - self._rpm_last_refill
        self._rpm_tokens = min(
            float(self._burst),
            self._rpm_tokens + rpm_elapsed / self._rpm_refill_interval,
        )
        self._rpm_last_refill = now

        # RPD bucket
        rpd_elapsed = now - self._rpd_last_refill
        self._rpd_tokens = min(
            float(self._rpd),
            self._rpd_tokens + rpd_elapsed / self._rpd_refill_interval,
        )
        self._rpd_last_refill = now

    def _acquire(self) -> None:
        """
        Block until **both** RPM and RPD buckets have >= 1 token AND the
        minimum inter-call delay has elapsed, then consume one token from each.
        """
        while True:
            with self._lock:
                self._refill_buckets()

                now = time.monotonic()
                time_since_last = now - self._last_call_time
                delay_needed = self._min_delay - time_since_last

                rpm_ok = self._rpm_tokens >= 1.0
                rpd_ok = self._rpd_tokens >= 1.0
                delay_ok = delay_needed <= 0

                if rpm_ok and rpd_ok and delay_ok:
                    self._rpm_tokens -= 1.0
                    self._rpd_tokens -= 1.0
                    self._last_call_time = now
                    return

                rpm_wait = (
                    (1.0 - self._rpm_tokens) * self._rpm_refill_interval
                    if not rpm_ok else 0.0
                )
                rpd_wait = (
                    (1.0 - self._rpd_tokens) * self._rpd_refill_interval
                    if not rpd_ok else 0.0
                )
                min_delay_wait = max(delay_needed, 0.0) if not delay_ok else 0.0
                sleep_for = max(rpm_wait, rpd_wait, min_delay_wait)

            bucket_name = "RPD (daily quota)" if rpd_wait >= rpm_wait else "RPM"
            logger.debug(
                "GroqRateLimiter: %s bucket empty — sleeping %.2fs.",
                bucket_name,
                sleep_for,
            )
            time.sleep(sleep_for)

    @staticmethod
    def _backoff_delay(attempt: int, base: float = 2.0, cap: float = 90.0) -> float:
        """
        Full-jitter exponential back-off.

        delay = random(0, min(cap, base x 2^attempt))

        Spreads retries to avoid thundering-herd pile-ups when multiple
        workers share the same Groq quota simultaneously.
        """
        ceiling = min(cap, base * (2 ** attempt))
        return random.uniform(0.0, ceiling)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call(self, fn: Any, /, *args: Any, **kwargs: Any) -> Any:
        """
        Invoke ``fn(*args, **kwargs)`` respecting both RPM and RPD limits.

        Retries automatically on Groq ``RateLimitError`` (HTTP 429) and
        transient connection / 5xx server errors with full-jitter exponential
        back-off.  All other exceptions propagate immediately.

        Parameters
        ----------
        fn:
            The callable to invoke
            (e.g. ``client.chat.completions.create``).
        *args, **kwargs:
            Forwarded verbatim to ``fn``.

        Returns
        -------
        The return value of ``fn(*args, **kwargs)``.

        Raises
        ------
        groq.RateLimitError
            If the quota is still exceeded after all retries are exhausted.
        Exception
            Any other exception raised by ``fn`` propagates immediately.
        """
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            self._acquire()   # honour both token buckets

            try:
                result = fn(*args, **kwargs)
                if attempt > 0:
                    logger.info(
                        "GroqRateLimiter: call succeeded on attempt %d.", attempt + 1
                    )
                return result

            except RateLimitError as exc:
                # HTTP 429 — hit Groq's server-side quota despite local pacing.
                last_exc = exc
                if attempt >= self._max_retries:
                    logger.error(
                        "GroqRateLimiter: RateLimitError after %d attempts — giving up. %s",
                        attempt + 1,
                        exc,
                    )
                    raise

                # Honour Retry-After header if Groq provides it
                retry_after: float | None = None
                if hasattr(exc, "response") and exc.response is not None:
                    ra_header = exc.response.headers.get("Retry-After")
                    if ra_header:
                        try:
                            retry_after = float(ra_header)
                        except ValueError:
                            pass

                delay = retry_after if retry_after is not None else self._backoff_delay(attempt)
                logger.warning(
                    "GroqRateLimiter: RateLimitError (attempt %d/%d) — "
                    "retrying in %.2fs.",
                    attempt + 1,
                    self._max_retries,
                    delay,
                )
                time.sleep(delay)

            except (APIConnectionError, APIStatusError) as exc:
                # Transient network / 5xx server errors
                last_exc = exc
                if attempt >= self._max_retries:
                    logger.error(
                        "GroqRateLimiter: transient API error after %d attempts — "
                        "giving up. %s",
                        attempt + 1,
                        exc,
                    )
                    raise

                delay = self._backoff_delay(attempt)
                logger.warning(
                    "GroqRateLimiter: transient error (attempt %d/%d) — "
                    "retrying in %.2fs. Error: %s",
                    attempt + 1,
                    self._max_retries,
                    delay,
                    exc,
                )
                time.sleep(delay)

        raise RuntimeError("GroqRateLimiter exhausted all retries.") from last_exc


# ---------------------------------------------------------------------------
# Groq client + rate-limiter singletons
# ---------------------------------------------------------------------------
_GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")

if _GROQ_API_KEY:
    _groq_client: Groq | None = Groq(api_key=_GROQ_API_KEY)
else:
    _groq_client = None
    logger.warning(
        "GROQ_API_KEY not set. ReasoningAgent will use the local heuristic fallback.\n"
        "Get a free key at https://console.groq.com then run:\n"
        "    export GROQ_API_KEY='your-key-here'"
    )

# Module-level singleton — shared across all reasoning_agent() calls.
# Override limits via env vars before importing, or pass constructor args:
#   _rate_limiter = GroqRateLimiter(rpm=10, rpd=5000, max_retries=3)
_rate_limiter = GroqRateLimiter()


# ---------------------------------------------------------------------------
# Shared in-memory session state (simulates Redis / shared cache)
# ---------------------------------------------------------------------------
_ua_ip_map: dict[str, set[str]] = defaultdict(set)      # { user_agent: {ip, ...} }
_path_request_counts: dict[str, int] = defaultdict(int)  # { path: count }


def reset_session_state() -> None:
    """Clear in-memory counters. Call between independent test runs."""
    _ua_ip_map.clear()
    _path_request_counts.clear()


# ===========================================================================
# 1. IngestionAgent
# ===========================================================================

# Nginx Combined Log Format regex
_NGINX_RE = re.compile(
    r'(?P<ip>\S+)\s+'           # client IP
    r'\S+\s+\S+\s+'             # ident / auth (ignored)
    r'\[(?P<timestamp>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+'      # HTTP method
    r'(?P<path>\S+)\s+'         # request path
    r'\S+"\s+'                  # protocol (ignored)
    r'(?P<status>\d{3})\s+'     # status code
    r'\S+\s+'                   # bytes sent (ignored)
    r'"[^"]*"\s+'               # referer (ignored)
    r'"(?P<user_agent>[^"]*)"'  # user-agent
)


def ingestion_agent(raw_log: str) -> dict[str, Any] | None:
    """
    IngestionAgent — Parse a raw Nginx Combined Log Format line.

    Returns a structured dict or None if the line cannot be parsed.
    """
    match = _NGINX_RE.search(raw_log)
    if not match:
        logger.warning("IngestionAgent: could not parse log line: %r", raw_log)
        return None

    data = match.groupdict()
    try:
        parsed_ts = datetime.strptime(data["timestamp"], "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        parsed_ts = None

    return {
        "ip": data["ip"],
        "timestamp": data["timestamp"],
        "parsed_timestamp": parsed_ts.isoformat() if parsed_ts else None,
        "method": data["method"],
        "path": data["path"],
        "status_code": int(data["status"]),
        "user_agent": data["user_agent"],
        "raw": raw_log,
    }


# ===========================================================================
# 2. IdentityAgent
# ===========================================================================

_IP_ROTATION_THRESHOLD = 3   # > N distinct IPs per User-Agent triggers alert


def identity_agent(ip: str, user_agent: str) -> dict[str, Any]:
    """
    IdentityAgent — Detect IP-rotation abuse by tracking distinct IPs per
    User-Agent string.

    Returns a finding dict with ``alert=True`` when the threshold is exceeded.
    """
    _ua_ip_map[user_agent].add(ip)
    ip_count = len(_ua_ip_map[user_agent])

    alert = ip_count > _IP_ROTATION_THRESHOLD
    finding: dict[str, Any] = {
        "agent": "IdentityAgent",
        "alert": alert,
        "user_agent": user_agent,
        "ip_count": ip_count,
        "seen_ips": list(_ua_ip_map[user_agent]),
    }
    if alert:
        finding["reason"] = (
            f"IP rotation detected: User-Agent '{user_agent}' has used "
            f"{ip_count} distinct IPs (threshold: {_IP_ROTATION_THRESHOLD})."
        )
        logger.warning("IdentityAgent ALERT — %s", finding["reason"])
    return finding


# ===========================================================================
# 3. ThreatIntelAgent (AbuseIPDB API)
# ===========================================================================

_ABUSEIPDB_API_KEY: str = os.environ.get(
    "ABUSEIPDB_API_KEY",
    "",
)
_ABUSEIPDB_URL = "https://api.abuseipdb.com/api/v2/check"
_ABUSEIPDB_ABUSE_THRESHOLD = 50  # confidence score >= this → malicious

# Cache to avoid re-checking the same IP within a session
_abuseipdb_cache: dict[str, dict[str, Any]] = {}


def _check_abuseipdb(ip: str) -> dict[str, Any]:
    """
    Query the AbuseIPDB CHECK endpoint for a single IP.

    Returns a dict with keys:
        is_malicious (bool), abuse_score (int), country (str|None),
        isp (str|None), total_reports (int), reason (str|None)

    Falls back gracefully on network / API errors.
    """
    # Return cached result if available
    if ip in _abuseipdb_cache:
        logger.debug("ThreatIntelAgent: cache hit for %s", ip)
        return _abuseipdb_cache[ip]

    # Private / reserved IPs can't be queried on AbuseIPDB
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_reserved or addr.is_loopback:
            result = {
                "is_malicious": False,
                "abuse_score": 0,
                "country": None,
                "isp": None,
                "total_reports": 0,
                "reason": f"IP {ip} is a private/reserved address — skipping AbuseIPDB lookup.",
            }
            _abuseipdb_cache[ip] = result
            return result
    except ValueError:
        pass

    headers = {
        "Key": _ABUSEIPDB_API_KEY,
        "Accept": "application/json",
    }
    params = {
        "ipAddress": ip,
        "maxAgeInDays": 90,
        "verbose": "",
    }

    try:
        resp = requests.get(_ABUSEIPDB_URL, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", {})

        abuse_score = int(data.get("abuseConfidenceScore", 0))
        is_malicious = abuse_score >= _ABUSEIPDB_ABUSE_THRESHOLD

        result = {
            "is_malicious": is_malicious,
            "abuse_score": abuse_score,
            "country": data.get("countryCode"),
            "isp": data.get("isp"),
            "total_reports": int(data.get("totalReports", 0)),
            "reason": (
                f"AbuseIPDB: IP {ip} has abuse confidence score {abuse_score}% "
                f"({data.get('totalReports', 0)} reports). "
                f"Threshold: {_ABUSEIPDB_ABUSE_THRESHOLD}%."
            ) if is_malicious else None,
        }
        _abuseipdb_cache[ip] = result
        logger.info(
            "ThreatIntelAgent: AbuseIPDB check for %s — score=%d%%, malicious=%s",
            ip, abuse_score, is_malicious,
        )
        return result

    except requests.RequestException as exc:
        logger.error("ThreatIntelAgent: AbuseIPDB API error for %s — %s. Assuming safe.", ip, exc)
        return {
            "is_malicious": False,
            "abuse_score": 0,
            "country": None,
            "isp": None,
            "total_reports": 0,
            "reason": f"AbuseIPDB lookup failed: {exc}",
        }


def threat_intel_agent(ip: str) -> dict[str, Any]:
    """
    ThreatIntelAgent — Check the request IP against AbuseIPDB's threat
    intelligence database.

    Returns a finding dict with ``is_malicious=True`` when the abuse
    confidence score meets or exceeds the threshold.
    """
    abuseipdb_result = _check_abuseipdb(ip)

    finding: dict[str, Any] = {
        "agent": "ThreatIntelAgent",
        "ip": ip,
        "is_malicious": abuseipdb_result["is_malicious"],
        "abuse_score": abuseipdb_result["abuse_score"],
        "country": abuseipdb_result["country"],
        "isp": abuseipdb_result["isp"],
        "total_reports": abuseipdb_result["total_reports"],
    }
    if abuseipdb_result["is_malicious"]:
        finding["reason"] = abuseipdb_result["reason"]
        logger.warning("ThreatIntelAgent ALERT — %s", finding["reason"])
    elif abuseipdb_result.get("reason"):
        finding["note"] = abuseipdb_result["reason"]

    return finding


# ===========================================================================
# 4. PatternAgent
# ===========================================================================

_RATE_LIMIT_THRESHOLD = 10   # > N total requests to a path triggers alert
_SENSITIVE_PATHS: frozenset[str] = frozenset(
    {"/login", "/admin", "/api/auth", "/wp-login.php"}
)


def pattern_agent(path: str) -> dict[str, Any]:
    """
    PatternAgent — Detect distributed rate-limit abuse by counting global
    requests to sensitive paths.

    Returns a finding dict with ``alert=True`` when the threshold is exceeded.
    """
    _path_request_counts[path] += 1
    count = _path_request_counts[path]

    alert = path in _SENSITIVE_PATHS and count > _RATE_LIMIT_THRESHOLD
    finding: dict[str, Any] = {
        "agent": "PatternAgent",
        "alert": alert,
        "path": path,
        "request_count": count,
    }
    if alert:
        finding["reason"] = (
            f"Distributed rate-limit threshold exceeded: path '{path}' has "
            f"received {count} total requests (threshold: {_RATE_LIMIT_THRESHOLD})."
        )
        logger.warning("PatternAgent ALERT — %s", finding["reason"])
    return finding


# ===========================================================================
# 5. ReasoningAgent (Groq — llama-3.1-8b-instant)
# ===========================================================================

_GROQ_MODEL = "llama-3.1-8b-instant"

_SYSTEM_PROMPT = """\
You are a SOC analyst AI. Given JSON findings from security sub-agents, decide BLOCK or ALLOW.
Rules: If ANY sub-agent reports is_malicious=true, ip_rotation alert, or rate-limit alert, respond BLOCK.
Respond with ONLY valid JSON: {"decision": "BLOCK"|"ALLOW", "reason": "<one sentence>"}
"""


def reasoning_agent(findings: dict[str, Any]) -> dict[str, Any]:
    """
    ReasoningAgent — Send aggregated sub-agent findings to
    Groq llama-3.1-8b-instant and return a structured BLOCK/ALLOW decision.

    Rate limiting
    -------------
    All Groq calls are routed through the module-level ``_rate_limiter``
    (:class:`GroqRateLimiter`), which enforces:

    * RPM bucket  — caps short-window throughput (default: 30 req/min).
    * RPD bucket  — caps long-window total (default: 14,400 req/day).
    * Exponential back-off with full jitter on HTTP 429 / transient errors,
      up to ``GROQ_MAX_RETRIES`` attempts (default: 4).
    * Respects ``Retry-After`` response headers when Groq provides them.

    Fallback
    --------
    If the API key is absent, all retries are exhausted, or an unrecoverable
    error occurs, the function returns a deterministic local heuristic decision
    so the LangGraph pipeline never crashes.
    """

    def _local_fallback(reason_suffix: str = "Groq unavailable") -> dict[str, Any]:
        should_block = (
            findings.get("threat_intel", {}).get("is_malicious", False)
            or findings.get("identity", {}).get("alert", False)
            or findings.get("pattern", {}).get("alert", False)
        )
        return {
            "decision": "BLOCK" if should_block else "ALLOW",
            "reason": f"Local heuristic ({reason_suffix}): based on sub-agent flags.",
            "fallback": True,
        }

    if not _GROQ_API_KEY or _groq_client is None:
        logger.info("ReasoningAgent: using local fallback (no API key).")
        return _local_fallback("no API key")

    context_json = json.dumps(findings, indent=None, default=str)  # compact JSON saves tokens

    try:
        # ── Rate-limited Groq API call ───────────────────────────────────
        # _rate_limiter.call() handles:
        #   • Dual token-bucket pacing (RPM + RPD)
        #   • Automatic retry with exponential back-off on 429 / 5xx
        #   • Retry-After header honouring on RateLimitError
        response = _rate_limiter.call(
            _groq_client.chat.completions.create,
            model=_GROQ_MODEL,
            temperature=0.0,
            max_tokens=128,                        # decision JSON is tiny; cap spend
            response_format={"type": "json_object"},  # enforce strict JSON output
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Sub-agent findings:\n{context_json}",
                },
            ],
        )
        # ────────────────────────────────────────────────────────────────

        raw_text: str = response.choices[0].message.content or ""
        decision: dict[str, Any] = json.loads(raw_text.strip())
        decision["fallback"] = False
        logger.info(
            "ReasoningAgent decision via %s: %s", _GROQ_MODEL, decision
        )
        return decision

    except json.JSONDecodeError as exc:
        logger.error("ReasoningAgent: JSON parse error — %s. Falling back.", exc)
        return _local_fallback("JSON parse error")

    except RateLimitError as exc:
        # Only reached if all retries inside _rate_limiter.call() were exhausted
        logger.error(
            "ReasoningAgent: Groq quota exhausted after all retries — %s. "
            "Falling back.", exc
        )
        return _local_fallback("quota exhausted")

    except (APIConnectionError, APIStatusError) as exc:
        logger.error(
            "ReasoningAgent: Groq API error after all retries — %s. Falling back.",
            exc,
        )
        return _local_fallback("API error")

    except Exception as exc:  # pylint: disable=broad-except
        logger.error("ReasoningAgent: unexpected error — %s. Falling back.", exc)
        return _local_fallback("unexpected error")


# ===========================================================================
# 6. ActionAgent (Defense-in-Depth: Azure NSG + Nginx)
# ===========================================================================

from .blocker import block_ip as _block_ip
from .blocker import get_blocked_ips as _get_blocked_ips


def action_agent(ip: str, decision: dict[str, Any]) -> dict[str, Any]:
    """
    ActionAgent — Execute the enforcement action based on the ReasoningAgent's
    decision.

    On BLOCK, delegates to blocker.block_ip() which fires:
      Layer 1 — Azure NSG deny rule  (if BLOCK_LAYER_AZURE=true)
      Layer 2 — Nginx deny directive  (if BLOCK_LAYER_NGINX=true)
      Fallback — In-memory simulation (if neither layer is enabled)
    """
    verdict = decision.get("decision", "ALLOW").upper()
    reason = decision.get("reason", "No reason provided.")
    used_fallback = decision.get("fallback", False)

    result: dict[str, Any] = {
        "agent": "ActionAgent",
        "ip": ip,
        "verdict": verdict,
        "reason": reason,
        "used_fallback": used_fallback,
    }

    if verdict == "BLOCK":
        # ── Fire both blocking layers ────────────────────────────────
        block_result = _block_ip(ip, reason)
        result["block_result"] = block_result

        layers_ok = ", ".join(block_result["layers_succeeded"]) or "none"
        border = "=" * 62
        fallback_note = "  ⚠️  [decided by local heuristic]\n" if used_fallback else ""

        print(f"\n{border}")
        print(f"  🚨  BLOCKING IP : {ip}")
        print(f"  REASON         : {reason}")
        print(f"{fallback_note}  LAYERS OK       : {layers_ok}")
        for lr in block_result["results"]:
            status = "✅" if lr["success"] else "❌"
            print(f"    {status} {lr['layer']}: {lr['detail']}")
        print(f"  TOTAL BLOCKED  : {block_result['total_blocked_ips']} IP(s)")
        print(f"{border}\n")

        result["action_taken"] = (
            f"IP {ip} blocked via [{layers_ok}] "
            f"({len(block_result['layers_succeeded'])}/{len(block_result['layers_attempted'])} layers)."
        )
        logger.warning("ActionAgent: BLOCKED %s via %s — %s", ip, layers_ok, reason)
    else:
        fallback_note = " [local heuristic]" if used_fallback else ""
        print(f"  ✅  ALLOWING {ip} — {reason}{fallback_note}")
        result["action_taken"] = "Request allowed; no action taken."
        logger.info("ActionAgent: ALLOWED %s — %s", ip, reason)

    return result


def get_blocked_ips() -> frozenset[str]:
    """Return the current set of blocked IPs (read-only, from blocker)."""
    return _get_blocked_ips()
