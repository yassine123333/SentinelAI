"""
Agent 04 — Universal Asset Engine

LangGraph node that orchestrates the three-layer quantitative pipeline:

  Layer 1 → data_fetcher     : yfinance OHLCV + VIX/OVX + validation
  Layer 2 → chronos_engine   : Chronos-2 curve-behaviour forecasting
  Layer 3 → garch_monte_carlo: GARCH(1,1) regime + Monte Carlo simulation
  LLM     → Gemini 2.5 Flash : thinking-mode synthesis + reasoning trace

Pipeline contract
-----------------
Reads from state : 'ticker', 'asset_name', 'lookback_days', 'forecast_horizon'
Writes to state  : 'agent_04_output'

On any unrecoverable failure the node writes a minimal Agent04Output with
success=False and pipeline_error set, rather than raising — so LangGraph can
route the run to Agent 05 (Critic) which will emit the appropriate FAIL verdict.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from .prompts.analyst_prompt import SYSTEM_PROMPT, build_user_prompt
from .resources.schemas import (
    Agent04Input,
    Agent04Output,
    LLMInterpretation,
    ModelAgreement,
    RiskRating,
)
from .tools.data_fetcher import fetch_asset_data
from .tools.chronos_engine import run_chronos_forecast
from .tools.garch_monte_carlo import run_garch, run_monte_carlo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------

_GEMINI_MODEL = "gemini-2.5-flash"

# Thinking budget: number of tokens the model may use for internal reasoning
# before writing the final answer.  Higher = better synthesis, higher latency.
# 8 192 is a good balance for this use-case.
_THINKING_BUDGET = 8_192


def _get_llm() -> ChatGoogleGenerativeAI:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GOOGLE_API_KEY or GEMINI_API_KEY must be set to use Agent 04."
        )
    return ChatGoogleGenerativeAI(
        model=_GEMINI_MODEL,
        google_api_key=api_key,
        temperature=1.0,           # required for thinking mode
        thinking_budget=_THINKING_BUDGET,
    )


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


def agent_04_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node function for Agent 04.

    Parameters
    ----------
    state : The shared pipeline state dict (typed as dict for LangGraph).

    Returns
    -------
    dict with key 'agent_04_output' set to an Agent04Output instance.
    """
    logger.info("Agent 04 — starting Universal Asset Engine")

    # --- Read inputs from pipeline state ---------------------------------
    try:
        agent_input = Agent04Input(
            ticker=state["ticker"],
            asset_name=state.get("asset_name", state["ticker"]),
            lookback_days=state.get("lookback_days", 90),
            forecast_horizon=state.get("forecast_horizon", 30),
        )
    except Exception as exc:
        logger.error("Agent 04 — invalid pipeline state: %s", exc)
        return {
            "agent_04_output": _failure_output(
                Agent04Input(ticker="UNKNOWN", asset_name="UNKNOWN"),
                f"Invalid pipeline state: {exc}",
            )
        }

    ticker   = agent_input.ticker
    horizon  = agent_input.forecast_horizon
    lookback = agent_input.lookback_days

    # --- Layer 1: Data fetch ---------------------------------------------
    logger.info("Agent 04 [L1] — fetching data for %s", ticker)
    data_result = fetch_asset_data(
        ticker=ticker,
        asset_name=agent_input.asset_name,
        lookback_days=lookback,
    )

    if data_result.quality.value == "failed" or not data_result.close_prices:
        logger.error("Agent 04 [L1] — data fetch failed: %s", data_result.error)
        return {
            "agent_04_output": Agent04Output(
                input=agent_input,
                data=data_result,
                success=False,
                pipeline_error=f"Data fetch failed: {data_result.error}",
            )
        }

    close_prices = data_result.close_prices

    # --- Layer 2: Chronos-2 forecast -------------------------------------
    logger.info("Agent 04 [L2] — running Chronos-2 for %s", ticker)
    chronos_result = run_chronos_forecast(
        ticker=ticker,
        close_prices=close_prices,
        forecast_horizon=horizon,
    )

    # --- Layer 3: GARCH + Monte Carlo ------------------------------------
    logger.info("Agent 04 [L3] — running GARCH for %s", ticker)
    garch_result = run_garch(
        ticker=ticker,
        close_prices=close_prices,
        forecast_horizon=horizon,
    )

    logger.info("Agent 04 [L3] — running Monte Carlo for %s", ticker)
    mc_result = run_monte_carlo(
        ticker=ticker,
        close_prices=close_prices,
        garch_result=garch_result,
        forecast_horizon=horizon,
    )

    # --- LLM synthesis ---------------------------------------------------
    logger.info("Agent 04 [LLM] — calling Gemini 2.5 Flash thinking mode")
    interpretation = _run_llm_synthesis(
        agent_input=agent_input,
        data_result=data_result,
        chronos=chronos_result,
        garch=garch_result,
        mc=mc_result,
    )

    # --- Assemble final output -------------------------------------------
    output = Agent04Output(
        input=agent_input,
        data=data_result,
        chronos=chronos_result,
        garch=garch_result,
        monte_carlo=mc_result,
        interpretation=interpretation,
        success=True,
        pipeline_error=None,
    )

    logger.info(
        "Agent 04 — complete | risk=%s | agreement=%s | confidence=%.2f",
        interpretation.risk_rating.value if interpretation else "N/A",
        interpretation.model_agreement.value if interpretation else "N/A",
        interpretation.confidence if interpretation else 0.0,
    )

    return {"agent_04_output": output}


# ---------------------------------------------------------------------------
# LLM synthesis helper
# ---------------------------------------------------------------------------


def _run_llm_synthesis(
    agent_input: Agent04Input,
    data_result,
    chronos,
    garch,
    mc,
) -> LLMInterpretation | None:
    """
    Call Gemini 2.5 Flash in thinking mode and parse the JSON response
    into an LLMInterpretation.

    Returns None only if the LLM call itself completely fails.
    """
    current_price = data_result.close_prices[-1] if data_result.close_prices else 0.0

    user_message = build_user_prompt(
        asset_name=agent_input.asset_name,
        ticker=agent_input.ticker,
        lookback_days=agent_input.lookback_days,
        forecast_horizon=agent_input.forecast_horizon,
        data_quality=data_result.quality.value,
        data_quality_notes=data_result.quality_notes,
        current_price=current_price,
        vix_current=data_result.vix_current,
        ovx_current=data_result.ovx_current,
        # Chronos
        chronos_error=chronos.error if chronos else "Chronos did not run",
        chronos_directional_bias=chronos.directional_bias if chronos else "neutral",
        chronos_median_terminal=chronos.median_terminal if chronos else 0.0,
        chronos_p10_terminal=chronos.p10_terminal if chronos else 0.0,
        chronos_p90_terminal=chronos.p90_terminal if chronos else 0.0,
        chronos_spread_pct=chronos.forecast_spread_pct if chronos else 0.0,
        chronos_uncertainty_score=chronos.uncertainty_score if chronos else 0.5,
        # GARCH
        garch_error=garch.error if garch else "GARCH did not run",
        garch_converged=garch.model_converged if garch else False,
        garch_annual_vol=garch.current_annualised_vol if garch else 0.0,
        garch_regime=garch.vol_regime.value if garch else "unknown",
        garch_alpha=garch.params.alpha if garch else 0.0,
        garch_beta=garch.params.beta if garch else 0.0,
        garch_persistence=garch.params.persistence if garch else 0.0,
        # Monte Carlo
        mc_error=mc.error if mc else "Monte Carlo did not run",
        mc_mean_return=mc.mean_return_pct if mc else 0.0,
        mc_median_return=mc.median_return_pct if mc else 0.0,
        mc_p5_return=mc.p5_return_pct if mc else 0.0,
        mc_p95_return=mc.p95_return_pct if mc else 0.0,
        mc_prob_dd5=mc.prob_drawdown_5pct if mc else 0.0,
        mc_prob_dd10=mc.prob_drawdown_10pct if mc else 0.0,
        mc_prob_dd20=mc.prob_drawdown_20pct if mc else 0.0,
        mc_prob_gain5=mc.prob_gain_5pct if mc else 0.0,
        mc_prob_gain10=mc.prob_gain_10pct if mc else 0.0,
    )

    try:
        llm = _get_llm()
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ]
        response = llm.invoke(messages)
        raw_text = response.content

        return _parse_llm_response(raw_text)

    except Exception as exc:
        logger.error("Agent 04 LLM call failed: %s", exc)
        # Return a degraded interpretation rather than None
        return LLMInterpretation(
            model_agreement=ModelAgreement.CONFLICT,
            risk_rating=RiskRating.MODERATE,
            key_findings=["LLM synthesis unavailable — quantitative signals only."],
            tensions=[f"LLM call failed: {exc}"],
            reasoning_trace=f"LLM synthesis failed: {exc}",
            confidence=0.3,
        )


def _parse_llm_response(raw_text: str) -> LLMInterpretation:
    """
    Parse the JSON response from Gemini into an LLMInterpretation.

    Gemini thinking-mode prepends its <think>…</think> block before the
    answer; we strip that if present before JSON parsing.
    """
    text = raw_text.strip()

    # Strip any <think>…</think> block that thinking mode may expose
    if "<think>" in text and "</think>" in text:
        start = text.index("</think>") + len("</think>")
        text = text[start:].strip()

    # Strip markdown code fences if the model emitted them despite instructions
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    data = json.loads(text)

    return LLMInterpretation(
        model_agreement=ModelAgreement(data["model_agreement"]),
        risk_rating=RiskRating(data["risk_rating"]),
        key_findings=data.get("key_findings", []),
        tensions=data.get("tensions", []),
        reasoning_trace=data.get("reasoning_trace", ""),
        confidence=float(data.get("confidence", 0.5)),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _failure_output(agent_input: Agent04Input, error: str) -> Agent04Output:
    from .tools.data_fetcher import DataFetchResult
    from .resources.schemas import DataQuality

    return Agent04Output(
        input=agent_input,
        data=DataFetchResult(
            ticker=agent_input.ticker,
            asset_name=agent_input.asset_name,
            bars=[],
            close_prices=[],
            trading_days=0,
            quality=DataQuality.FAILED,
            quality_notes=[error],
            error=error,
        ),
        success=False,
        pipeline_error=error,
    )
