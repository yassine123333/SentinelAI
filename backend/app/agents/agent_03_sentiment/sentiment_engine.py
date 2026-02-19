"""
Sentiment Signal Engine.

Combines GDELT (institutional) and Reddit (retail) sentiment data into
a structured signal: sentiment_score, panic_index, divergence_score,
confidence, and trend_direction.

Includes optional regime awareness (VIX-based weight shifting).
"""

import numpy as np
from typing import Dict, Any

import config


def compute_signal(
    gdelt_data: Dict[str, Any],
    reddit_data: Dict[str, Any],
    asset: str,
    vix_level: float | None = None,
) -> Dict[str, Any]:
    """
    Engineer the final sentiment signal from raw source data.

    Args:
        gdelt_data:   Output from gdelt_client.fetch_all_keywords()
        reddit_data:  Output from reddit_client.fetch_and_score()
        asset:        The asset/topic string
        vix_level:    Optional current VIX value for regime awareness

    Returns:
        Strict JSON-compatible dict matching the output schema.
    """
    gdelt_score = gdelt_data.get("gdelt_score", 0.0)
    reddit_score = reddit_data.get("reddit_score", 0.0)

    # ─── Regime-Aware Weights ───────────────────────────────────
    w_reddit = config.WEIGHT_REDDIT
    w_gdelt = config.WEIGHT_GDELT

    if config.ENABLE_REGIME_AWARENESS and vix_level is not None:
        if vix_level >= config.VIX_CRISIS_THRESHOLD:
            # Crisis: retail sentiment matters more
            w_reddit = 0.70
            w_gdelt = 0.30
        else:
            # Calm: institutional news matters more
            w_reddit = 0.50
            w_gdelt = 0.50

    # ─── Sentiment Score ────────────────────────────────────────
    sentiment_score = w_reddit * reddit_score + w_gdelt * gdelt_score
    sentiment_score = float(np.clip(sentiment_score, -1.0, 1.0))

    # ─── Panic Index ────────────────────────────────────────────
    # High when: sentiment strongly negative + polarization high
    #            + negative acceleration
    polarization = reddit_data.get("polarization_index", 0.0)
    acceleration = reddit_data.get("sentiment_acceleration", 0.0)

    neg_strength = max(0.0, -sentiment_score)           # 0 if positive
    accel_panic = max(0.0, -acceleration) * 5.0         # scale up
    polar_panic = min(polarization * 2.0, 1.0)          # cap at 1

    panic_index = float(np.clip(
        0.5 * neg_strength + 0.3 * polar_panic + 0.2 * accel_panic,
        0.0, 1.0,
    ))

    # ─── Divergence Score ───────────────────────────────────────
    divergence_score = round(abs(reddit_score - gdelt_score), 4)

    # ─── Trend Direction ────────────────────────────────────────
    gdelt_trend = gdelt_data.get("gdelt_trend", 0.0)
    combined_accel = 0.6 * acceleration + 0.4 * gdelt_trend

    if combined_accel > 0.005:
        trend_direction = "accelerating_positive"
    elif combined_accel < -0.005:
        trend_direction = "accelerating_negative"
    else:
        trend_direction = "stable"

    # ─── Confidence ─────────────────────────────────────────────
    gdelt_articles = gdelt_data.get("gdelt_article_count", 0)
    reddit_posts = reddit_data.get("post_count", 0)
    gdelt_vol = gdelt_data.get("gdelt_volatility", 0.0)

    # Data volume component (more data = higher confidence)
    volume_score = min((gdelt_articles + reddit_posts) / 200.0, 1.0)

    # Cross-source agreement (low divergence = higher confidence)
    agreement_score = max(0.0, 1.0 - divergence_score)

    # Stability of trend (low volatility = higher confidence)
    stability_score = max(0.0, 1.0 - min(gdelt_vol / 5.0, 1.0))

    confidence = float(np.clip(
        0.40 * volume_score + 0.35 * agreement_score + 0.25 * stability_score,
        0.0, 1.0,
    ))

    # ─── Explanation ────────────────────────────────────────────
    explanation = _build_explanation(
        asset, sentiment_score, reddit_score, gdelt_score,
        trend_direction, panic_index, divergence_score,
        gdelt_articles, reddit_posts, w_reddit, w_gdelt,
    )

    # ─── Final Output ──────────────────────────────────────────
    return {
        "asset": asset,
        "sentiment_score": round(sentiment_score, 4),
        "confidence": round(confidence, 4),
        "panic_index": round(panic_index, 4),
        "trend_direction": trend_direction,
        "source_breakdown": {
            "gdelt_score": round(gdelt_score, 4),
            "reddit_score": round(reddit_score, 4),
        },
        "divergence_score": round(divergence_score, 4),
        "data_points_used": {
            "gdelt_articles": gdelt_articles,
            "reddit_posts": reddit_posts,
        },
        "explanation_summary": explanation,
    }


def _build_explanation(
    asset: str,
    sentiment_score: float,
    reddit_score: float,
    gdelt_score: float,
    trend_direction: str,
    panic_index: float,
    divergence_score: float,
    gdelt_articles: int,
    reddit_posts: int,
    w_reddit: float,
    w_gdelt: float,
) -> str:
    """Generate a detailed multi-paragraph explanation."""
    # ── Overall tone ──
    tone = "positive" if sentiment_score > 0.05 else (
        "negative" if sentiment_score < -0.05 else "neutral"
    )
    strength = abs(sentiment_score)
    if strength > 0.4:
        intensity = "strongly"
    elif strength > 0.15:
        intensity = "moderately"
    elif strength > 0.05:
        intensity = "slightly"
    else:
        intensity = ""

    lines = []

    # ── Paragraph 1: Overview ──
    lines.append(
        f"OVERVIEW: The overall market sentiment for {asset} is "
        f"{intensity + ' ' if intensity else ''}{tone} with a composite "
        f"score of {sentiment_score:.4f} (range: -1 bearish to +1 bullish). "
        f"Confidence in this reading is based on {gdelt_articles} institutional "
        f"news articles and {reddit_posts} Reddit community posts."
    )

    # ── Paragraph 2: Source breakdown ──
    reddit_tone = "bullish" if reddit_score > 0.03 else (
        "bearish" if reddit_score < -0.03 else "mixed/neutral"
    )
    gdelt_tone = "positive" if gdelt_score > 0.03 else (
        "negative" if gdelt_score < -0.03 else "neutral"
    )
    lines.append(
        f"SOURCE BREAKDOWN: Reddit retail sentiment is {reddit_tone} "
        f"(score={reddit_score:.4f}, weight={w_reddit:.0%}). "
        f"GDELT institutional news tone is {gdelt_tone} "
        f"(score={gdelt_score:.4f}, weight={w_gdelt:.0%}). "
        f"The composite is computed as: "
        f"{w_reddit:.0%} × Reddit ({reddit_score:.4f}) + "
        f"{w_gdelt:.0%} × GDELT ({gdelt_score:.4f}) = {sentiment_score:.4f}."
    )

    # ── Paragraph 3: Divergence analysis ──
    if divergence_score > 0.3:
        lines.append(
            f"DIVERGENCE ALERT: Significant disconnect between retail and "
            f"institutional sentiment (divergence={divergence_score:.4f}). "
            f"This suggests the market crowd and news media have different "
            f"readings — a potential contrarian signal or an early indicator "
            f"of a sentiment shift."
        )
    elif divergence_score > 0.1:
        lines.append(
            f"DIVERGENCE: Moderate divergence ({divergence_score:.4f}) between "
            f"Reddit and GDELT. The two sources lean in somewhat different "
            f"directions but are not contradicting each other strongly."
        )
    else:
        lines.append(
            f"CONVERGENCE: Retail and institutional sentiment are well-aligned "
            f"(divergence={divergence_score:.4f}), increasing confidence "
            f"in the signal."
        )

    # ── Paragraph 4: Trend & momentum ──
    trend_text = trend_direction.replace("_", " ")
    lines.append(
        f"TREND: The current momentum is {trend_text}. "
        + (
            "Sentiment is gaining positive momentum — the market mood "
            "is improving over the analysis window."
            if "positive" in trend_direction else
            "Sentiment is deteriorating — negative momentum is building "
            "across sources."
            if "negative" in trend_direction else
            "Sentiment is relatively stable with no strong directional shift "
            "detected in the analysis window."
        )
    )

    # ── Paragraph 5: Panic assessment ──
    if panic_index > 0.7:
        lines.append(
            f"⚠ PANIC ALERT: The panic index is elevated at {panic_index:.4f}. "
            f"This indicates strong negative sentiment combined with high "
            f"polarization and accelerating bearish momentum. Exercise "
            f"extreme caution — crowd fear is dominant."
        )
    elif panic_index > 0.4:
        lines.append(
            f"CAUTION: The panic index is moderately elevated ({panic_index:.4f}). "
            f"There are signs of fear in the market but it has not reached "
            f"extreme levels. Monitor for escalation."
        )
    else:
        lines.append(
            f"CALM: The panic index is low ({panic_index:.4f}), indicating "
            f"no significant fear or distress in current market sentiment."
        )

    return "\n\n".join(lines)
