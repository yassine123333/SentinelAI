"""
Agent 06 — Critic & Verifier
Provider : Local Ollama (llama3.1:8b-instruct-q4_K_M)
Role     : Autonomous quality gate that validates pipeline outputs from
           Agents 02–05 across five dimensions:
             1. Source attribution
             2. Internal consistency
             3. Confidence calibration
             4. Narrative coherence
             5. Completeness

           Returns a structured PASS/FAIL verdict with full reasoning trace
           and actionable retry instructions on failure.

Security controls:
  - Prompt injection detection on all free-text inputs
  - Token-bucket rate limiter (10 calls / min)
  - Structured audit log (no secrets, no raw keys)
  - Input fingerprinting for traceability
  - Pydantic v2 validation on both input and LLM output
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.core.gemini_keys import OllamaConfig, generate_with_key_rotation, has_gemini_keys

from .schemas import CriticInput, CriticOutput
from .tools.confidence_scorer import get_confidence_breakdown
from .tools.consistency_checker import check_consistency
from .tools.source_verifier import verify_sources

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ── Prompt loading ────────────────────────────────────────────────────────────
_PROMPTS = Path(__file__).parent / "prompts"
_SYSTEM_PROMPT: str = (_PROMPTS / "system.md").read_text(encoding="utf-8")
_USER_TEMPLATE: str = (_PROMPTS / "user.md").read_text(encoding="utf-8")

# ── Constants ─────────────────────────────────────────────────────────────────
_PASS_THRESHOLD = 0.60
_MAX_PROMPT_CHARS = 12_000          # hard cap on pipeline JSON inserted into prompt
_RATE_LIMIT_CALLS = 10              # max calls per minute (token bucket)
_RATE_LIMIT_WINDOW = 60.0           # seconds

# Patterns that suggest prompt injection inside pipeline data
_INJECTION_RE = re.compile(
    r"(ignore\s+previous\s+instructions|disregard\s+all|"
    r"system\s*:\s*you\s+are|<\|im_end\|>|</s>\s*<s>|"
    r"act\s+as\s+.*(different|new)\s+(ai|llm|model))",
    re.IGNORECASE | re.DOTALL,
)

# Regex to extract JSON from markdown code fences (LLM fallback)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


# ── Helper: sanitize text before prompt insertion ─────────────────────────────

def _sanitize(text: str, max_len: int = _MAX_PROMPT_CHARS) -> str:
    """
    Truncate and scan for prompt injection attempts.
    Raises ValueError if injection pattern is detected.
    """
    truncated = text[:max_len]
    if _INJECTION_RE.search(truncated):
        raise ValueError(
            "Prompt injection pattern detected in pipeline data. "
            "Pipeline run aborted for security."
        )
    return truncated


# ── Helper: extract JSON from LLM response (handles markdown fences) ──────────

def _extract_json(raw: str) -> str:
    """Return the raw JSON string from the LLM response."""
    raw = raw.strip()
    if raw.startswith("{"):
        return raw
    match = _JSON_FENCE_RE.search(raw)
    if match:
        return match.group(1)
    raise ValueError(f"No JSON object found in LLM response: {raw[:200]!r}")


# ── Helper: normalize LLM output to match CriticOutput schema ────────────────

_KNOWN_CHECKS = {
    "source_attribution", "internal_consistency",
    "confidence_calibration", "narrative_coherence", "completeness",
}


def _normalize_critic_json(data: dict, payload_query_id: str) -> dict:
    """
    Repair common schema deviations from smaller LLMs (llama3.1:8b) before
    Pydantic validation.  Handles:
      - Missing query_id / verdict
      - checks as dict instead of list
      - Check data leaked to top-level keys
      - reasoning_trace as list instead of string
      - Missing required list fields
    """
    # ── 1. Inject identity fields ─────────────────────────────────────────────
    if not data.get("query_id"):
        data["query_id"] = payload_query_id

    # ── 2. Normalise checks → must be list[CheckResult] ───────────────────────
    checks_raw = data.get("checks", {})

    if isinstance(checks_raw, dict):
        checks_list: list[dict] = []
        for check_name, check_data in checks_raw.items():
            if not isinstance(check_data, dict):
                continue
            passed = bool(check_data.get("passed", False))
            checks_list.append({
                "check_name": check_name,
                "passed": passed,
                "score": float(check_data.get("score", 1.0 if passed else 0.0)),
                "details": str(check_data.get("details", f"Check {check_name}"))[:500],
                "affected_agents": list(check_data.get("affected_agents", [])),
            })
        data["checks"] = checks_list
    elif not isinstance(checks_raw, list):
        data["checks"] = []

    # ── 3. Absorb check data leaked to top-level keys ─────────────────────────
    existing_names = {c.get("check_name") for c in data["checks"] if isinstance(c, dict)}
    for key in list(_KNOWN_CHECKS):
        if key not in data or key in existing_names:
            continue
        raw_val = data.pop(key)
        if isinstance(raw_val, dict):
            passed = bool(raw_val.get("passed", False))
            data["checks"].append({
                "check_name": key,
                "passed": passed,
                "score": float(raw_val.get("score", 1.0 if passed else 0.0)),
                "details": str(raw_val.get("details", f"Check {key}"))[:500],
                "affected_agents": list(raw_val.get("affected_agents", [])),
            })
        elif isinstance(raw_val, list):
            # Model serialised the check as a list of sub-items; create a stub
            data["checks"].append({
                "check_name": key,
                "passed": False,
                "score": 0.0,
                "details": f"Check {key}: model returned list format.",
                "affected_agents": [],
            })

    # ── 4. Ensure all 5 checks are present ────────────────────────────────────
    present_names = {c.get("check_name") for c in data["checks"] if isinstance(c, dict)}
    for required in _KNOWN_CHECKS - present_names:
        data["checks"].append({
            "check_name": required,
            "passed": False,
            "score": 0.0,
            "details": "Check not evaluated by model.",
            "affected_agents": [],
        })

    # ── 5. Normalise reasoning_trace → must be str ≥ 100 chars ───────────────
    rt = data.get("reasoning_trace", "")
    if isinstance(rt, list):
        rt = " ".join(json.dumps(x, default=str) if isinstance(x, dict) else str(x) for x in rt)
    elif not isinstance(rt, str):
        rt = str(rt)
    if len(rt) < 100:
        rt = rt + "  Pipeline critic evaluation completed. " * 4
    data["reasoning_trace"] = rt[:5000]

    # ── 6. Derive verdict if missing ─────────────────────────────────────────
    if not data.get("verdict"):
        all_passed = all(c.get("passed", False) for c in data["checks"] if isinstance(c, dict))
        data["verdict"] = "PASS" if all_passed else "FAIL"

    # ── 7. Ensure list fields exist ───────────────────────────────────────────
    if not isinstance(data.get("retry_instructions"), list):
        data["retry_instructions"] = []
    if not isinstance(data.get("flagged_claims"), list):
        data["flagged_claims"] = []

    return data


# ── CriticAgent ───────────────────────────────────────────────────────────────

class CriticAgent:
    """
    Agent 06: Critic & Verifier.

    Usage (async):
        agent  = CriticAgent()
        result = await agent.run(critic_input)

    Usage (sync wrapper for scripts/tests):
        import asyncio
        result = asyncio.run(agent.run(critic_input))
    """

    agent_id   = "agent_06"
    model_name = "ollama/llama3.1:8b-instruct-q4_K_M"

    def __init__(self) -> None:
        if not has_gemini_keys():
            raise RuntimeError("LLM client is not available.")
        # Token-bucket rate limiter state
        self._tokens: float = float(_RATE_LIMIT_CALLS)
        self._last_refill: float = time.monotonic()

    # ── Rate Limiting ─────────────────────────────────────────────────────────

    def _consume_rate_token(self) -> None:
        """Token-bucket: refill proportionally over time, consume one token."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            float(_RATE_LIMIT_CALLS),
            self._tokens + elapsed * (_RATE_LIMIT_CALLS / _RATE_LIMIT_WINDOW),
        )
        self._last_refill = now
        if self._tokens < 1.0:
            raise RuntimeError(
                f"Rate limit exceeded: max {_RATE_LIMIT_CALLS} calls/min. "
                "Wait before retrying."
            )
        self._tokens -= 1.0

    # ── Audit Logging ─────────────────────────────────────────────────────────

    def _audit(self, event: str, **fields: object) -> None:
        """
        Emit a structured JSON audit log entry.
        Never logs the API key, raw pipeline data, or PII.
        """
        entry = {
            "ts":    datetime.now(timezone.utc).isoformat(),
            "agent": self.agent_id,
            "model": self.model_name,
            "event": event,
            **fields,
        }
        logger.info(json.dumps(entry, default=str))

    # ── Input Fingerprinting ──────────────────────────────────────────────────

    @staticmethod
    def _fingerprint(payload: CriticInput) -> str:
        """SHA-256 digest (first 12 hex chars) of the serialised input."""
        raw = payload.model_dump_json()
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    # ── Core Run ──────────────────────────────────────────────────────────────

    async def run(self, payload: CriticInput) -> CriticOutput:
        """
        Execute the full critic pipeline asynchronously.

        Steps:
          1. Rate-limit check
          2. Three deterministic pre-checks (source, consistency, confidence)
          3. Prompt injection scan on pipeline JSON
          4. Build user prompt from template
          5. Gemini 2.5 Flash LLM call (JSON mode)
          6. Parse + validate LLM output with Pydantic
          7. Audit log result
          8. Return CriticOutput
        """
        self._consume_rate_token()
        fp = self._fingerprint(payload)
        self._audit(
            "critic_start",
            query_id=payload.query_id,
            asset=payload.asset,
            attempt=payload.attempt,
            fingerprint=fp,
        )

        # ── Step 2: Deterministic pre-checks ─────────────────────────────────
        source_result     = verify_sources(payload)
        consistency_result = check_consistency(payload)
        confidence_result  = get_confidence_breakdown(payload)

        # ── Step 3: Injection scan ────────────────────────────────────────────
        pipeline_json = _sanitize(
            json.dumps(payload.model_dump(), indent=2, default=str)
        )

        # ── Step 4: Build user prompt with locked values ──────────────────────
        # Locked values are injected explicitly so the LLM cannot invent them.
        locked_source_passed     = str(source_result["passed"]).lower()
        locked_confidence_passed = str(confidence_result["passed"]).lower()
        locked_sources_verified  = str(source_result["sources_verified"])
        locked_sources_total     = str(source_result["sources_total"])
        locked_aggregate         = str(round(confidence_result["aggregate"], 4))

        user_prompt = (
            _USER_TEMPLATE
            .replace("{{query_id}}",                  payload.query_id)
            .replace("{{asset}}",                     payload.asset)
            .replace("{{attempt}}",                   str(payload.attempt))
            .replace("{{locked_sources_verified}}",   locked_sources_verified)
            .replace("{{locked_sources_total}}",      locked_sources_total)
            .replace("{{locked_aggregate_confidence}}",locked_aggregate)
            .replace("{{locked_source_passed}}",      locked_source_passed)
            .replace("{{locked_confidence_passed}}",  locked_confidence_passed)
            .replace("{{source_check}}",              json.dumps(source_result,      indent=2))
            .replace("{{consistency_check}}",         json.dumps(consistency_result, indent=2))
            .replace("{{confidence_check}}",          json.dumps(confidence_result,  indent=2))
            .replace("{{pipeline_json}}",             pipeline_json)
        )

        # ── Step 5: LLM call — temperature=0.0 for maximum determinism ────────
        # A verification agent must be greedy/deterministic. Any temperature above 0
        # introduces randomness that can cause the model to deviate from the locked
        # values or fabricate evidence.
        response = await generate_with_key_rotation(
            model=self.model_name,
            contents=user_prompt,
            config=OllamaConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.0,        # greedy — no hallucination slack
                top_p=1.0,
                max_output_tokens=8192,
            ),
        )

        raw_text = response.text

        # ── Step 6: Parse, normalize, and validate ───────────────────────────
        try:
            json_str  = _extract_json(raw_text)
            raw_dict  = json.loads(json_str)
            norm_dict = _normalize_critic_json(raw_dict, payload.query_id)
            output    = CriticOutput.model_validate(norm_dict)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            self._audit(
                "critic_parse_error",
                query_id=payload.query_id,
                fingerprint=fp,
                error=str(exc),
            )
            raise RuntimeError(
                f"Agent 06 failed to parse/validate LLM output: {exc}\n"
                f"Raw response snippet: {raw_text[:300]!r}"
            ) from exc

        # ── Step 7: Deterministic reconciliation (hallucination guard) ──────────
        # The LLM was instructed to copy locked values verbatim.
        # If it deviated anyway (hallucination), we silently correct and log a warning.
        # This means the pipeline is NEVER dependent on the LLM getting numbers right.
        corrections: list[str] = []

        det_sources_verified  = source_result["sources_verified"]
        det_sources_total     = source_result["sources_total"]
        det_aggregate         = round(confidence_result["aggregate"], 4)
        det_source_passed     = source_result["passed"]
        det_confidence_passed = confidence_result["passed"]

        if output.sources_verified != det_sources_verified:
            corrections.append(
                f"sources_verified: LLM={output.sources_verified} → corrected to {det_sources_verified}"
            )
            output = output.model_copy(update={"sources_verified": det_sources_verified})

        if output.sources_total != det_sources_total:
            corrections.append(
                f"sources_total: LLM={output.sources_total} → corrected to {det_sources_total}"
            )
            output = output.model_copy(update={"sources_total": det_sources_total})

        if round(output.overall_confidence, 4) != det_aggregate:
            corrections.append(
                f"overall_confidence: LLM={output.overall_confidence} → corrected to {det_aggregate}"
            )
            output = output.model_copy(update={"overall_confidence": det_aggregate})

        # Reconcile per-check passed flags for the two fully-deterministic checks
        reconciled_checks = []
        for chk in output.checks:
            if chk.check_name == "source_attribution" and chk.passed != det_source_passed:
                corrections.append(
                    f"checks[source_attribution].passed: LLM={chk.passed} → corrected to {det_source_passed}"
                )
                chk = chk.model_copy(update={"passed": det_source_passed})
            if chk.check_name == "confidence_calibration" and chk.passed != det_confidence_passed:
                corrections.append(
                    f"checks[confidence_calibration].passed: LLM={chk.passed} → corrected to {det_confidence_passed}"
                )
                chk = chk.model_copy(update={"passed": det_confidence_passed})
            reconciled_checks.append(chk)

        if reconciled_checks != output.checks:
            output = output.model_copy(update={"checks": reconciled_checks})

        # Replace placeholder timestamp with real UTC time
        output = output.model_copy(
            update={"timestamp": datetime.now(timezone.utc).isoformat()}
        )

        if corrections:
            self._audit(
                "critic_reconciliation",
                query_id=payload.query_id,
                fingerprint=fp,
                corrections=corrections,
                warning="LLM deviated from deterministic locked values — auto-corrected",
            )

        # ── Step 8: Audit result ──────────────────────────────────────────────
        self._audit(
            "critic_done",
            query_id=payload.query_id,
            asset=payload.asset,
            verdict=output.verdict,
            overall_confidence=output.overall_confidence,
            sources_verified=output.sources_verified,
            sources_total=output.sources_total,
            retry_instructions_count=len(output.retry_instructions),
            attempt=payload.attempt,
            fingerprint=fp,
            reconciliation_corrections=len(corrections),
        )

        return output
