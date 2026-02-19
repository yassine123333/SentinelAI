"""
Agent 07 — Report Synthesis
Provider : Google Gemini 2.5 Flash (Standard mode — no thinking tokens)
Role     : Final delivery stage of the SentinelAI pipeline.
           Receives validated outputs from Agents 02–05 and the Critic verdict,
           then assembles three deliverables:
             1. Interactive dashboard payload  — structured JSON for React frontend
             2. Narrative report text          — 5-section prose synthesised by Gemini
             3. PDF document                  — WeasyPrint HTML-to-PDF, local generation

           Standard mode is chosen over Thinking mode because the task is structured
           writing (fast, low hallucination) — not deep multi-step reasoning.

Security controls:
  - Prompt injection detection on the user query free-text field
  - Token-bucket rate limiter (10 calls / min)
  - Structured audit log (no secrets, no raw keys)
  - Input fingerprinting (SHA-256) for traceability
  - Pydantic v2 validation on both input and LLM output
  - Hallucination guard: dashboard locked values reconciled post-LLM
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

from google import genai
from google.genai import types
from pydantic import ValidationError

from .resources.schemas import (
    DashboardPayload,
    NarrativeSections,
    SynthesisInput,
    SynthesisOutput,
    _LLMNarrativeOutput,
)
from .tools.dashboard_builder import build_dashboard_payload
from .tools.pdf_renderer import render_pdf

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ── Prompt loading ─────────────────────────────────────────────────────────────
_PROMPTS = Path(__file__).parent / "prompts"
_SYSTEM_PROMPT: str = (_PROMPTS / "system.md").read_text(encoding="utf-8")
_USER_TEMPLATE: str = (_PROMPTS / "user.md").read_text(encoding="utf-8")

# ── Constants ──────────────────────────────────────────────────────────────────
_RATE_LIMIT_CALLS = 10          # max calls per minute (token bucket)
_RATE_LIMIT_WINDOW = 60.0       # seconds
_MAX_PIPELINE_CHARS = 14_000    # hard cap on pipeline JSON inserted into prompt
_MAX_DASHBOARD_CHARS = 4_000    # hard cap on dashboard JSON inserted into prompt

# Patterns that suggest prompt injection inside free-text fields
_INJECTION_RE = re.compile(
    r"(ignore\s+previous\s+instructions|disregard\s+all|"
    r"system\s*:\s*you\s+are|<\|im_end\|>|</s>\s*<s>|"
    r"act\s+as\s+.*(different|new)\s+(ai|llm|model))",
    re.IGNORECASE | re.DOTALL,
)

# Regex to extract JSON from markdown code fences (LLM fallback)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sanitize(text: str, max_len: int) -> str:
    """
    Truncate to max_len and scan for prompt injection.
    Raises ValueError if an injection pattern is detected.
    """
    truncated = text[:max_len]
    if _INJECTION_RE.search(truncated):
        raise ValueError(
            "Prompt injection pattern detected in pipeline data. "
            "Synthesis run aborted for security."
        )
    return truncated


def _extract_json(raw: str) -> str:
    """Return the raw JSON string from the LLM response."""
    raw = raw.strip()
    if raw.startswith("{"):
        return raw
    match = _JSON_FENCE_RE.search(raw)
    if match:
        return match.group(1)
    raise ValueError(f"No JSON object found in LLM response: {raw[:200]!r}")


# ── SynthesisAgent ─────────────────────────────────────────────────────────────

class SynthesisAgent:
    """
    Agent 07: Report Synthesis.

    Usage (async):
        agent  = SynthesisAgent()
        result = await agent.run(synthesis_input)

    Usage (sync wrapper for scripts/tests):
        import asyncio
        result = asyncio.run(agent.run(synthesis_input))

    Output (`SynthesisOutput`):
        - executive_summary        : 1–2 sentence TL;DR
        - narrative_sections       : 5 prose paragraphs (Gemini)
        - key_risks                : 3–6 risk factors (Gemini)
        - key_opportunities        : 0–4 upside factors (Gemini)
        - dashboard_payload        : full structured JSON for React (deterministic)
        - pdf_bytes                : raw PDF bytes from WeasyPrint (or None)
        - reasoning_trace          : structured audit trail (Gemini)
        - timestamp                : UTC ISO timestamp
    """

    agent_id   = "agent_07"
    model_name = "gemini-2.5-flash"

    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY environment variable is not set. "
                "Add it to backend/.env or export it before running."
            )
        self._client = genai.Client(api_key=api_key)
        # Token-bucket rate limiter state
        self._tokens: float = float(_RATE_LIMIT_CALLS)
        self._last_refill: float = time.monotonic()

    # ── Rate Limiting ──────────────────────────────────────────────────────────

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

    # ── Audit Logging ──────────────────────────────────────────────────────────

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

    # ── Input Fingerprinting ───────────────────────────────────────────────────

    @staticmethod
    def _fingerprint(payload: SynthesisInput) -> str:
        """SHA-256 digest (first 12 hex chars) of the serialised input."""
        raw = payload.model_dump_json()
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    # ── Core Run ───────────────────────────────────────────────────────────────

    async def run(self, payload: SynthesisInput) -> SynthesisOutput:
        """
        Execute the full synthesis pipeline asynchronously.

        Steps:
          1. Rate-limit check
          2. Input fingerprinting
          3. Build deterministic dashboard payload (no LLM)
          4. Prompt injection scan on pipeline JSON
          5. Build user prompt from template with locked values
          6. Gemini 2.5 Flash Standard mode call (JSON, temperature=0.3)
          7. Parse + validate LLM output with Pydantic
          8. Reconcile locked values (hallucination guard)
          9. Assemble SynthesisOutput
          10. Render PDF via WeasyPrint
          11. Audit log result
          12. Return SynthesisOutput
        """
        self._consume_rate_token()
        fp = self._fingerprint(payload)
        self._audit(
            "synthesis_start",
            query_id=payload.query_id,
            asset=payload.asset,
            fingerprint=fp,
            critic_verdict=payload.critic.verdict,
        )

        # ── Step 3: Deterministic dashboard (no LLM) ─────────────────────────
        dashboard = build_dashboard_payload(payload)

        # ── Step 4: Injection scan on serialised pipeline ─────────────────────
        pipeline_json = _sanitize(
            json.dumps(payload.model_dump(), indent=2, default=str),
            _MAX_PIPELINE_CHARS,
        )
        dashboard_json = _sanitize(
            json.dumps(dashboard.model_dump(), indent=2, default=str),
            _MAX_DASHBOARD_CHARS,
        )

        # ── Step 5: Fill prompt template with locked values ───────────────────
        rg = dashboard.risk_gauge
        sp = dashboard.scenario_probabilities
        meta = dashboard.meta
        overall_confidence = str(round(float(meta.get("overall_confidence", 0)), 4))

        user_prompt = (
            _USER_TEMPLATE
            .replace("{{query_id}}",         payload.query_id)
            .replace("{{asset}}",            payload.asset)
            .replace("{{verdict}}",          payload.critic.verdict)
            .replace("{{overall_confidence}}", overall_confidence)
            .replace("{{risk_gauge_score}}", str(rg.score))
            .replace("{{risk_gauge_level}}", rg.level)
            .replace("{{bull_pct}}",         str(round(sp.bull * 100, 1)))
            .replace("{{base_pct}}",         str(round(sp.base * 100, 1)))
            .replace("{{bear_pct}}",         str(round(sp.bear * 100, 1)))
            .replace("{{dashboard_json}}",   dashboard_json)
            .replace("{{pipeline_json}}",    pipeline_json)
        )

        # ── Step 6: Gemini 2.5 Flash — Standard mode ─────────────────────────
        # Standard mode = no thinking_config.
        # temperature=0.3 allows natural prose while staying grounded.
        response = await self._client.aio.models.generate_content(
            model=self.model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.3,
                top_p=0.95,
                max_output_tokens=4096,
            ),
        )

        raw_text = response.text

        # ── Step 7: Parse and validate LLM output ─────────────────────────────
        try:
            json_str = _extract_json(raw_text)
            llm_out  = _LLMNarrativeOutput.model_validate(json.loads(json_str))
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            self._audit(
                "synthesis_parse_error",
                query_id=payload.query_id,
                fingerprint=fp,
                error=str(exc),
            )
            raise RuntimeError(
                f"Agent 07 failed to parse/validate LLM output: {exc}\n"
                f"Raw response snippet: {raw_text[:300]!r}"
            ) from exc

        # ── Step 8: Reconcile locked values (hallucination guard) ─────────────
        # Dashboard is deterministic — LLM cannot change these.
        # We patch key_risks and key_opportunities back into the dashboard payload
        # now that the LLM has produced them.
        dashboard = dashboard.model_copy(
            update={
                "key_risks": llm_out.key_risks,
                "key_opportunities": llm_out.key_opportunities,
            }
        )

        # ── Step 9: Assemble final output ─────────────────────────────────────
        now_ts = datetime.now(timezone.utc).isoformat()
        output = SynthesisOutput(
            query_id=payload.query_id,
            asset=payload.asset,
            verdict=payload.critic.verdict,
            executive_summary=llm_out.executive_summary,
            narrative_sections=llm_out.narrative_sections,
            key_risks=llm_out.key_risks,
            key_opportunities=llm_out.key_opportunities,
            dashboard_payload=dashboard,
            reasoning_trace=llm_out.reasoning_trace,
            timestamp=now_ts,
        )

        # ── Step 10: Render PDF ────────────────────────────────────────────────
        pdf = render_pdf(output)
        # Use object.__setattr__ to bypass Pydantic immutability on excluded field
        object.__setattr__(output, "pdf_bytes", pdf)

        # ── Step 11: Audit result ─────────────────────────────────────────────
        self._audit(
            "synthesis_done",
            query_id=payload.query_id,
            asset=payload.asset,
            verdict=output.verdict,
            overall_confidence=meta.get("overall_confidence"),
            risk_level=rg.level,
            key_risks_count=len(output.key_risks),
            key_opportunities_count=len(output.key_opportunities),
            pdf_generated=pdf is not None,
            fingerprint=fp,
        )

        return output
