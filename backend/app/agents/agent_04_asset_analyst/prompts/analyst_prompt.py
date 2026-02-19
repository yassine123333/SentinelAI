"""
Prompts for Agent 04 — Universal Asset Engine.

Gemini 2.5 Flash runs in thinking mode here.  The model is asked to:
  1. Read the quantitative outputs from Chronos-2 and GARCH/Monte Carlo
  2. Identify whether the models agree or conflict
  3. Assign a risk rating
  4. Produce 3–5 key findings and flag any tensions
  5. Write its full chain-of-thought (this becomes the reasoning trace in the PDF)

The prompt is intentionally structured as a JSON contract so the output
can be parsed directly into an LLMInterpretation schema without a second
LLM call.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a senior quantitative risk analyst at a macro hedge fund.

You have been given the outputs of two independent quantitative models \
for a financial asset:

1. **Chronos-2 Forecast** — a time-series foundation model that reads the \
shape of the price curve and generates a distribution of 100 possible future \
price paths.  It has no knowledge of what asset this is.

2. **GARCH(1,1) + Monte Carlo** — a volatility-regime model that captures \
volatility clustering in the return series, then runs 5 000 forward \
simulations using that regime's volatility schedule.

Your task is to synthesise these two independent signals into a coherent \
risk assessment.  Think carefully — do not rush.  The output will be \
attached to a professional risk report reviewed by institutional investors.

Key analytical principles:
- **Agreement amplifies signal.**  When both models indicate the same \
direction or risk level, that is a stronger signal than either alone.
- **Conflict is a signal too.**  If Chronos-2 shows low uncertainty but \
GARCH shows an elevated-volatility regime, that tension must be flagged.  \
Historical shocks often occur exactly when volatility models are \
artificially calm.
- **Never confuse forecast with fact.**  These are probability-weighted \
scenarios.  Use language like "the models suggest", "there is elevated \
probability that", "the downside scenario implies" — never "the price will".
- **Data quality matters.**  If the fetch layer flagged data issues \
(gaps, sparse data, outliers), weight the quantitative outputs accordingly \
and say so explicitly.

You must respond with a single valid JSON object — no markdown fences, \
no extra text before or after — conforming to this schema:

{
  "model_agreement": "<agree_bullish|agree_bearish|agree_neutral|conflict>",
  "risk_rating": "<low|moderate|high|critical>",
  "key_findings": ["<finding 1>", "<finding 2>", "<finding 3>"],
  "tensions": ["<tension 1>"],
  "reasoning_trace": "<your full chain-of-thought here>",
  "confidence": <float between 0.0 and 1.0>
}

Rules:
- key_findings: 3 to 5 items.  Each is one concise sentence with a \
specific number or percentage where possible.
- tensions: 0 to 3 items.  Leave as [] if models fully agree and data is clean.
- reasoning_trace: write your complete step-by-step reasoning BEFORE \
reaching the conclusion.  This is the thinking log — be thorough, include \
the specific numbers you are working with.
- confidence: your honest self-assessment.  Low if data quality is poor or \
models conflict sharply.  High only if both models converge and data is clean.
"""


# ---------------------------------------------------------------------------
# User prompt builder
# ---------------------------------------------------------------------------

def build_user_prompt(
    asset_name: str,
    ticker: str,
    lookback_days: int,
    forecast_horizon: int,
    data_quality: str,
    data_quality_notes: list[str],
    current_price: float,
    vix_current: float | None,
    ovx_current: float | None,
    # Chronos fields
    chronos_error: str | None,
    chronos_directional_bias: str,
    chronos_median_terminal: float,
    chronos_p10_terminal: float,
    chronos_p90_terminal: float,
    chronos_spread_pct: float,
    chronos_uncertainty_score: float,
    # GARCH fields
    garch_error: str | None,
    garch_converged: bool,
    garch_annual_vol: float,
    garch_regime: str,
    garch_alpha: float,
    garch_beta: float,
    garch_persistence: float,
    # Monte Carlo fields
    mc_error: str | None,
    mc_mean_return: float,
    mc_median_return: float,
    mc_p5_return: float,
    mc_p95_return: float,
    mc_prob_dd5: float,
    mc_prob_dd10: float,
    mc_prob_dd20: float,
    mc_prob_gain5: float,
    mc_prob_gain10: float,
) -> str:
    """
    Build the user-turn message that presents the quantitative data
    to Gemini 2.5 Flash.
    """

    # Format optional supplementary indices
    supplementary = []
    if vix_current is not None:
        supplementary.append(f"  - VIX (equity fear gauge): {vix_current:.2f}")
    if ovx_current is not None:
        supplementary.append(f"  - OVX (oil volatility index): {ovx_current:.2f}")
    supplementary_str = (
        "\n".join(supplementary) if supplementary else "  - Not available"
    )

    # Format data quality block
    quality_block = f"Quality verdict: {data_quality.upper()}"
    if data_quality_notes:
        quality_block += "\nNotes:\n" + "\n".join(
            f"  - {n}" for n in data_quality_notes
        )

    # Format Chronos block
    if chronos_error:
        chronos_block = f"[FAILED — {chronos_error}]"
    else:
        pct_change_median = (
            (chronos_median_terminal - current_price) / current_price * 100
            if current_price > 0 else 0.0
        )
        chronos_block = f"""\
  Directional bias:      {chronos_directional_bias.upper()}
  Current price:         {current_price:.4f}
  Median terminal price: {chronos_median_terminal:.4f} ({pct_change_median:+.2f}%)
  P10 terminal price:    {chronos_p10_terminal:.4f}  (downside scenario)
  P90 terminal price:    {chronos_p90_terminal:.4f}  (upside scenario)
  Forecast spread:       {chronos_spread_pct:.2f}%  of current price (P90−P10)
  Uncertainty score:     {chronos_uncertainty_score:.3f}  (0=confident, 1=highly uncertain)"""

    # Format GARCH block
    if garch_error:
        garch_block = f"[FAILED — {garch_error}]"
    else:
        converged_str = "YES" if garch_converged else "NO (results may be unreliable)"
        garch_block = f"""\
  Model converged:       {converged_str}
  Current annual vol:    {garch_annual_vol:.2f}%
  Volatility regime:     {garch_regime.upper()}
  GARCH alpha (ARCH):    {garch_alpha:.6f}
  GARCH beta:            {garch_beta:.6f}
  Persistence (α+β):     {garch_persistence:.6f}  (near 1.0 = long memory / slow mean-reversion)"""

    # Format Monte Carlo block
    if mc_error:
        mc_block = f"[FAILED — {mc_error}]"
    else:
        mc_block = f"""\
  Terminal return mean:  {mc_mean_return:+.2f}%
  Terminal return median:{mc_median_return:+.2f}%
  P5  return (left tail):{mc_p5_return:+.2f}%
  P95 return (right tail):{mc_p95_return:+.2f}%

  Drawdown probabilities (max intra-path from start):
    P(max drawdown ≥  5%): {mc_prob_dd5 * 100:.1f}%
    P(max drawdown ≥ 10%): {mc_prob_dd10 * 100:.1f}%
    P(max drawdown ≥ 20%): {mc_prob_dd20 * 100:.1f}%

  Upside probabilities (terminal gain):
    P(gain ≥  5%): {mc_prob_gain5 * 100:.1f}%
    P(gain ≥ 10%): {mc_prob_gain10 * 100:.1f}%"""

    return f"""\
ASSET UNDER ANALYSIS
  Name:   {asset_name}
  Ticker: {ticker}

ANALYSIS WINDOW
  Historical lookback: {lookback_days} calendar days
  Forecast horizon:    {forecast_horizon} trading days

DATA QUALITY
{quality_block}

SUPPLEMENTARY CONTEXT
{supplementary_str}

═══════════════════════════════════════
MODEL 1 — CHRONOS-2 PRICE FORECAST
(Abstract curve-behaviour model; asset-class agnostic)
═══════════════════════════════════════
{chronos_block}

═══════════════════════════════════════
MODEL 2A — GARCH(1,1) VOLATILITY MODEL
═══════════════════════════════════════
{garch_block}

═══════════════════════════════════════
MODEL 2B — MONTE CARLO SIMULATION
(5 000 paths; uses GARCH volatility schedule)
═══════════════════════════════════════
{mc_block}

═══════════════════════════════════════
YOUR TASK
═══════════════════════════════════════
Synthesise the above into a single JSON risk assessment.
Remember: respond with valid JSON only — no markdown, no preamble.
"""
