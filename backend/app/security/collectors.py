"""
collectors.py — Unified security event collectors for all platform layers.

Sources:
  1. FastAPI in-process — asyncio.Queue fed by SOCMiddleware (zero-latency)
  2. MongoDB profiler   — polls system.profile for slow queries / injection probes
  3. Nginx file tail    — optional, tails the access log if the path is accessible
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Unified Event Model ───────────────────────────────────────────────────────

@dataclass
class RequestEvent:
    """Unified security event from any platform layer."""
    source: str           # "fastapi" | "nginx" | "mongodb"
    ip: str
    path: str
    method: str
    status_code: int
    user_agent: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    extra: dict[str, Any] = field(default_factory=dict)

    def is_private_ip(self) -> bool:
        try:
            return ipaddress.ip_address(self.ip).is_private
        except ValueError:
            return False


# ── In-Process Queue ──────────────────────────────────────────────────────────

_request_queue: asyncio.Queue[RequestEvent] = asyncio.Queue(maxsize=10_000)


def emit_event(event: RequestEvent) -> None:
    """
    Non-blocking emit from FastAPI middleware or route handlers.
    Silently drops events when the queue is full (backpressure protection).
    """
    try:
        _request_queue.put_nowait(event)
    except asyncio.QueueFull:
        pass


async def drain_events(max_items: int = 500) -> list[RequestEvent]:
    """Drain up to max_items events without blocking. Called each daemon tick."""
    events: list[RequestEvent] = []
    for _ in range(max_items):
        try:
            events.append(_request_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return events


# ── MongoDB Profiler Collector ────────────────────────────────────────────────

_NOSQL_PATTERNS = [
    re.compile(r'\$where', re.IGNORECASE),
    re.compile(r'%24(gt|lt|ne|where|regex|in|nin|or|and)', re.IGNORECASE),
    re.compile(r'\{[^}]{0,200}\$[^}]{0,200}\}'),
    re.compile(r"'\s*(or|and)\s+'?\d+'?\s*=\s*'?\d", re.IGNORECASE),
]

_SLOW_QUERY_MS: int = int(os.environ.get("SOC_SLOW_QUERY_MS", "500"))
_MONGO_PROFILING_ENABLED: bool = (
    os.environ.get("SOC_ENABLE_MONGO_PROFILING", "false").lower() == "true"
)


async def enable_mongo_profiling() -> None:
    """
    Enable MongoDB slow-query profiling (level=1).
    Opt-in: set SOC_ENABLE_MONGO_PROFILING=true.
    Level 1 only logs queries slower than slowms — minimal performance impact.
    """
    if not _MONGO_PROFILING_ENABLED:
        return
    try:
        from app.db.mongodb import get_db
        db = get_db()
        await db.command("profile", 1, slowms=_SLOW_QUERY_MS)
        logger.info("SOC: MongoDB profiling enabled (level=1, slowms=%d).", _SLOW_QUERY_MS)
    except Exception as exc:
        logger.warning("SOC: could not enable MongoDB profiling: %s", exc)


async def collect_mongodb_events(
    last_ts: datetime,
) -> tuple[list[RequestEvent], datetime]:
    """
    Poll system.profile for:
      - Slow queries (> SOC_SLOW_QUERY_MS ms) — resource exhaustion indicator
      - Queries matching NoSQL injection patterns

    Returns (new_events, updated_timestamp_cursor).
    """
    if not _MONGO_PROFILING_ENABLED:
        return [], last_ts

    events: list[RequestEvent] = []
    new_last_ts = last_ts

    try:
        from app.db.mongodb import get_db
        db = get_db()
        cursor = db.system_profile.find(
            {"ts": {"$gt": last_ts}, "millis": {"$gte": _SLOW_QUERY_MS}},
            sort=[("ts", 1)],
            limit=100,
        )
        async for doc in cursor:
            ts = doc.get("ts", datetime.now(timezone.utc))
            if ts > new_last_ts:
                new_last_ts = ts

            query_str = str(doc.get("query", doc.get("command", "")))
            is_injection = any(p.search(query_str) for p in _NOSQL_PATTERNS)

            if is_injection:
                logger.warning(
                    "SOC MongoDB profiler: injection probe detected — ns=%s query=%.200s",
                    doc.get("ns", "unknown"),
                    query_str,
                )

            events.append(
                RequestEvent(
                    source="mongodb",
                    ip="mongodb_internal",
                    path=f"/{doc.get('ns', 'unknown')}",
                    method=str(doc.get("op", "query")).upper(),
                    status_code=200,
                    timestamp=ts,
                    extra={
                        "millis": doc.get("millis", 0),
                        "ns": doc.get("ns", ""),
                        "op": doc.get("op", ""),
                        "query": query_str[:500],
                        "is_injection_probe": is_injection,
                    },
                )
            )
    except Exception as exc:
        logger.debug("SOC MongoDB profiler collect error: %s", exc)

    return events, new_last_ts


# ── Nginx Log File Tail ───────────────────────────────────────────────────────

_NGINX_RE = re.compile(
    r'(?P<ip>\S+)\s+\S+\s+\S+\s+'
    r'\[(?P<ts>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
    r'(?P<status>\d{3})\s+\S+\s+"[^"]*"\s+"(?P<ua>[^"]*)"'
)


def _parse_nginx_line(line: str) -> RequestEvent | None:
    m = _NGINX_RE.search(line)
    if not m:
        return None
    try:
        ts = datetime.strptime(m.group("ts"), "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        ts = datetime.now(timezone.utc)
    return RequestEvent(
        source="nginx",
        ip=m.group("ip"),
        path=m.group("path"),
        method=m.group("method"),
        status_code=int(m.group("status")),
        user_agent=m.group("ua"),
        timestamp=ts,
    )


def _sync_tail_nginx(path: str, position: list[int]) -> list[RequestEvent]:
    """
    Synchronous Nginx file tail — called via run_in_executor.
    position[0] is the file byte offset cursor, updated in place.
    """
    events: list[RequestEvent] = []
    p = Path(path)
    if not p.exists():
        return events
    try:
        current_size = p.stat().st_size
        if current_size < position[0]:  # log rotation detected
            position[0] = 0
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(position[0])
            for line in fh:
                raw = line.rstrip("\n")
                if raw and not raw.startswith("#"):
                    ev = _parse_nginx_line(raw)
                    if ev:
                        events.append(ev)
            position[0] = fh.tell()
    except Exception as exc:
        logger.debug("SOC Nginx tail error: %s", exc)
    return events


async def collect_nginx_events(
    path: str,
    position: list[int],
    executor,
) -> list[RequestEvent]:
    """Async wrapper: run synchronous file tail in a thread executor."""
    if not path or not Path(path).exists():
        return []
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _sync_tail_nginx, path, position)
