"""
progressive.py — Progressive Intervention State Machine.

Escalation path (per spec):
  CLEAN → MONITORING → CHALLENGED (CAPTCHA) → SUSPENDED → BLOCKED (NSG + Nginx)

All state is persisted in MongoDB so it survives daemon restarts.
Thresholds are configurable via environment variables.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from .persistence import (
    InterventionLevel,
    get_ip_state,
    log_audit_event,
    persist_blocked_ip,
    set_captcha_required,
    set_suspended,
    update_ip_state,
)

logger = logging.getLogger(__name__)

# Violations at a given level before escalating to the next level.
# Override via environment variables for tuning.
_THRESHOLDS: dict[InterventionLevel, int] = {
    InterventionLevel.CLEAN:      int(os.environ.get("SOC_THRESH_CLEAN",     "1")),
    InterventionLevel.MONITORING: int(os.environ.get("SOC_THRESH_MONITOR",   "3")),
    InterventionLevel.CHALLENGED: int(os.environ.get("SOC_THRESH_CHALLENGE", "4")),
    InterventionLevel.SUSPENDED:  int(os.environ.get("SOC_THRESH_SUSPEND",   "2")),
}


async def evaluate_and_escalate(
    ip: str,
    findings: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate an IP's current intervention state and escalate if warranted.
    Called by the daemon for every suspicious IP batch.

    Escalation logic:
      - Increment violation count for the IP.
      - If violations >= threshold for current level → escalate to next level.
      - Apply enforcement action for the new level.
      - Persist everything to MongoDB.

    Returns the action dict describing what was done.
    """
    state = await get_ip_state(ip)
    current_level = InterventionLevel(state.get("level", int(InterventionLevel.CLEAN)))
    violations = state.get("violations", 0)
    reason = decision.get("reason", "SOC autonomous detection")[:300]

    # Already at max — nothing to escalate
    if current_level == InterventionLevel.BLOCKED:
        return {
            "action": "ALREADY_BLOCKED",
            "level": "BLOCKED",
            "ip": ip,
            "detail": f"IP {ip} is already permanently blocked.",
        }

    # Count this new violation
    next_violations = violations + 1
    threshold = _THRESHOLDS.get(current_level, 1)

    # Determine next intervention level
    if next_violations >= threshold and current_level < InterventionLevel.BLOCKED:
        next_level = InterventionLevel(int(current_level) + 1)
    else:
        # At least move to MONITORING on first violation
        next_level = max(current_level, InterventionLevel.MONITORING)

    # Persist the new state before acting (so crashes don't leave ghost state)
    await update_ip_state(ip, next_level, reason)

    # Apply enforcement
    action = await _enforce(ip, next_level, reason)

    # Audit log — full reasoning chain for human review
    await log_audit_event(
        ip=ip,
        event_type=f"ESCALATION_{next_level.name}",
        findings=findings,
        decision=decision,
        action=action,
    )

    if next_level != current_level:
        logger.warning(
            "SOC progressive: %s escalated %s → %s | violations=%d | %s",
            ip,
            current_level.name,
            next_level.name,
            next_violations,
            reason[:80],
        )
    else:
        logger.info(
            "SOC progressive: %s stays at %s | violations=%d | %s",
            ip,
            current_level.name,
            next_violations,
            reason[:80],
        )

    return action


async def _enforce(ip: str, level: InterventionLevel, reason: str) -> dict[str, Any]:
    """
    Apply the enforcement action for the given intervention level.

    MONITORING  → passive watch, no user-visible effect
    CHALLENGED  → set captcha_required flag; middleware intercepts next request
    SUSPENDED   → set suspended flag; all new requests from this IP get 403
    BLOCKED     → hard block: in-memory set + Nginx deny + Azure NSG rule + MongoDB persist
    """
    base = {"ip": ip, "level": level.name}

    if level == InterventionLevel.MONITORING:
        return {
            **base,
            "action": "MONITOR",
            "detail": f"IP {ip} is under active monitoring.",
        }

    if level == InterventionLevel.CHALLENGED:
        await set_captcha_required(ip, required=True)
        return {
            **base,
            "action": "CAPTCHA_CHALLENGE",
            "detail": f"IP {ip} must complete CAPTCHA challenge on next request.",
        }

    if level == InterventionLevel.SUSPENDED:
        await set_suspended(ip, suspended=True)
        return {
            **base,
            "action": "SUSPENDED",
            "detail": f"IP {ip} suspended — all sessions invalidated, new requests blocked.",
        }

    if level == InterventionLevel.BLOCKED:
        # Run synchronous blocker in executor (it calls Azure SDK + subprocess)
        from .blocker import block_ip
        loop = asyncio.get_event_loop()
        block_result = await loop.run_in_executor(None, block_ip, ip, reason)
        await persist_blocked_ip(ip, reason)
        return {
            **base,
            "action": "BLOCKED",
            "detail": f"IP {ip} hard-blocked at NSG + Nginx level.",
            "layers": block_result.get("layers_succeeded", []),
            "fully_blocked": block_result.get("fully_blocked", False),
        }

    return {**base, "action": "NONE", "detail": "No enforcement at this level."}
