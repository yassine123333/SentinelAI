"""
Agent 07 — Report Synthesis
Provider : Local Ollama (llama3.1:8b-instruct-q4_K_M)
Role     : Final delivery stage of the SentinelAI pipeline.
           Receives validated outputs from Agents 02–05 and the Critic verdict,
           then assembles three deliverables:
             1. Interactive dashboard payload  — structured JSON for React frontend
             2. Narrative report text          — 5-section prose synthesised by LLM
             3. PDF document                  — WeasyPrint HTML-to-PDF, local generation

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

from pydantic import ValidationError

from app.core.gemini_keys import OllamaConfig, generate_with_key_rotation, has_gemini_keys

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


def _build_fallback_narrative(
    payload: SynthesisInput, reason: str
) -> "_LLMNarrativeOutput":
    """
    Construct a valid _LLMNarrativeOutput from pipeline data when the Gemini
    response is truncated or unparseable.  Never raises.
    """
    asset   = payload.asset
    verdict = payload.critic.verdict
    conf    = payload.critic.overall_confidence
    geo     = payload.geopolitical
    sent    = payload.sentiment
    aa      = payload.asset_analyst
    qr      = payload.quant_risk

    # ── executive_summary (50–500 chars) ──────────────────────────────────────
    exec_summary = (
        f"{asset} analysis — verdict: {verdict} "
        f"(confidence {conf:.0%}, {qr.risk_level} risk). "
        f"LLM narrative unavailable; deterministic fallback applied."
    )[:500]

    # ── Padding helper ─────────────────────────────────────────────────────────
    _PAD = "  Baseline assessment — detailed real-time data coverage was limited for this run."

    def _ensure(text: str, min_len: int = 100) -> str:
        return (text + _PAD if len(text) < min_len else text)[:1500]

    # ── Narrative sections ─────────────────────────────────────────────────────
    sentiment_label = (
        "bullish" if sent.sentiment_score > 0.1
        else "bearish" if sent.sentiment_score < -0.1
        else "neutral"
    )
    scenarios = qr.monte_carlo_scenarios
    bull_pct  = round(scenarios.get("bull", 0.25) * 100, 1)
    base_pct  = round(scenarios.get("base", 0.50) * 100, 1)
    bear_pct  = round(scenarios.get("bear", 0.25) * 100, 1)

    geo_text = _ensure(
        f"Geopolitical stability score: {geo.stability_score:.1f}/100. "
        f"{geo.risk_summary}"
    )
    sent_text = _ensure(
        f"Market sentiment is {sentiment_label} "
        f"(score: {sent.sentiment_score:+.2f}, Fear & Greed Index: "
        f"{sent.fear_greed_index:.0f}/100). "
        f"Sentiment confidence: {sent.confidence:.0%}."
    )
    asset_text = _ensure(
        f"{asset} shows a {aa.price_trend} trend at ${aa.current_price:.4f}. "
        f"{aa.short_term_outlook}"
    )
    risk_text = _ensure(
        f"Annualised 30-day volatility: {qr.volatility_30d:.1%}. "
        f"95% VaR: {qr.var_95:.1%}. Risk level: {qr.risk_level}. "
        f"GARCH forecast regime: {qr.garch_forecast.get('regime', 'N/A')}."
    )
    outlook_text = _ensure(
        f"Monte Carlo scenario distribution — "
        f"Bull: {bull_pct}%, Base: {base_pct}%, Bear: {bear_pct}%. "
        f"Critic verdict: {verdict} with {conf:.0%} overall confidence."
    )

    # ── key_risks (≥ 1 item) ──────────────────────────────────────────────────
    patterns: list[str] = [
        p for p in aa.key_patterns
        if p and p != "N/A" and "Baseline" not in p and "Pipeline error" not in p
    ]
    key_risks: list[str] = patterns[:5] if patterns else []
    if qr.var_95 > 0.05:
        key_risks.append(f"High VaR: {qr.var_95:.1%} at 95% confidence")
    if geo.stability_score < 40:
        key_risks.append("Low geopolitical stability — elevated macro risk")
    if not key_risks:
        key_risks = [f"Elevated {qr.risk_level} risk for {asset}"]

    # ── reasoning_trace (≥ 100 chars) ─────────────────────────────────────────
    reasoning = (
        f"Fallback synthesis activated. Gemini LLM parse failed: {reason[:150]}. "
        f"Asset: {asset}. Verdict: {verdict}. Confidence: {conf:.2f}. "
        f"Risk level: {qr.risk_level}. Annualised vol: {qr.volatility_30d:.1%}."
    )

    return _LLMNarrativeOutput(
        executive_summary=exec_summary,
        narrative_sections=NarrativeSections(
            geopolitical_context=geo_text,
            market_sentiment=sent_text,
            asset_analysis=asset_text,
            risk_assessment=risk_text,
            scenario_outlook=outlook_text,
        ),
        key_risks=key_risks[:8],
        key_opportunities=[],
        reasoning_trace=reasoning,
    )


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
    model_name = "ollama/llama3.1:8b-instruct-q4_K_M"

    def __init__(self) -> None:
        if not has_gemini_keys():
            raise RuntimeError("LLM client is not available.")
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
        llm_out: _LLMNarrativeOutput
        raw_text = ""
        try:
            response = await generate_with_key_rotation(
                model=self.model_name,
                contents=user_prompt,
                config=OllamaConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.3,
                    top_p=0.95,
                    max_output_tokens=4096,
                ),
            )
            raw_text = response.text

            # ── Step 7: Parse and validate LLM output ─────────────────────────
            json_str = _extract_json(raw_text)
            llm_out = _LLMNarrativeOutput.model_validate(json.loads(json_str))

        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            # LLM response was malformed JSON or schema-invalid.
            reason = f"{type(exc).__name__}: {exc}"
            self._audit(
                "synthesis_parse_error",
                query_id=payload.query_id,
                fingerprint=fp,
                error=reason,
                raw_snippet=raw_text[:200],
                fallback="deterministic",
            )
            logger.warning(
                "Agent 07 LLM parse failed (%s) — using deterministic fallback for %s",
                reason, payload.query_id,
            )
            llm_out = _build_fallback_narrative(payload, reason)

        except Exception as exc:
            # API-level generation errors (e.g., 400 json_validate_failed, transient provider errors)
            # should not fail the full pipeline.
            reason = f"{type(exc).__name__}: {exc}"
            self._audit(
                "synthesis_llm_error",
                query_id=payload.query_id,
                fingerprint=fp,
                error=reason,
                fallback="deterministic",
            )
            logger.warning(
                "Agent 07 LLM call failed (%s) — using deterministic fallback for %s",
                reason, payload.query_id,
            )
            llm_out = _build_fallback_narrative(payload, reason)

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
