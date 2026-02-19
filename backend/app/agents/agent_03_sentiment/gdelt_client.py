"""
GDELT Tone API Client.

Retrieves macro/institutional news sentiment using the GDELT DOC 2.0 API
(mode=timelinetone) for a list of keywords within a specified time window.
"""

import time as _time
import requests
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any

import config

# ─── GDELT Retry / Timeout settings ────────────────────────────────
GDELT_TIMEOUT = 60          # seconds per request (increased from 30)
GDELT_MAX_RETRIES = 3       # total attempts per keyword
GDELT_RETRY_BACKOFF = 5     # seconds base backoff between retries


def _build_gdelt_url(keyword: str, start_date: str, end_date: str) -> str:
    """Build a GDELT DOC 2.0 API URL for timeline tone."""
    params = {
        "query": keyword,
        "mode": "timelinetone",
        "startdatetime": start_date,
        "enddatetime": end_date,
        "format": "json",
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{config.GDELT_BASE_URL}?{query_string}"


def _request_with_retry(url: str, keyword: str) -> requests.Response:
    """
    Send GET request with retry + exponential backoff.
    Raises the last exception if all retries fail.
    """
    last_err = None
    for attempt in range(1, GDELT_MAX_RETRIES + 1):
        try:
            print(f"[GDELT] Attempt {attempt}/{GDELT_MAX_RETRIES} for '{keyword}' "
                  f"(timeout={GDELT_TIMEOUT}s)...")
            resp = requests.get(url, timeout=GDELT_TIMEOUT)
            resp.raise_for_status()
            print(f"[GDELT] ✓ Success for '{keyword}' on attempt {attempt}")
            return resp
        except requests.exceptions.Timeout as e:
            last_err = e
            wait = GDELT_RETRY_BACKOFF * attempt
            print(f"[GDELT] ✗ Timeout for '{keyword}' (attempt {attempt}). "
                  f"Retrying in {wait}s...")
            _time.sleep(wait)
        except requests.exceptions.ConnectionError as e:
            last_err = e
            wait = GDELT_RETRY_BACKOFF * attempt
            print(f"[GDELT] ✗ Connection error for '{keyword}' (attempt {attempt}). "
                  f"Retrying in {wait}s...")
            _time.sleep(wait)
        except requests.exceptions.HTTPError as e:
            # Don't retry on 4xx client errors
            if e.response is not None and 400 <= e.response.status_code < 500:
                print(f"[GDELT] ✗ HTTP {e.response.status_code} for '{keyword}' — not retrying.")
                raise
            last_err = e
            wait = GDELT_RETRY_BACKOFF * attempt
            print(f"[GDELT] ✗ HTTP error for '{keyword}' (attempt {attempt}). "
                  f"Retrying in {wait}s...")
            _time.sleep(wait)
    raise last_err  # type: ignore


def fetch_tone_timeline(
    keyword: str, time_window_days: int
) -> Dict[str, Any]:
    """
    Fetch tone timeline from GDELT for a single keyword.

    Returns:
        Dict with raw_tones list, average_tone, tone_trend, tone_volatility,
        normalized_score, and article_count.
    """
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=time_window_days)
    start_str = start_dt.strftime("%Y%m%d%H%M%S")
    end_str = end_dt.strftime("%Y%m%d%H%M%S")

    url = _build_gdelt_url(keyword, start_str, end_str)

    try:
        resp = _request_with_retry(url, keyword)
        data = resp.json()
    except Exception as e:
        print(f"[GDELT] ✗ All retries failed for '{keyword}': {e}")
        return _empty_result()

    # Parse timeline tone data
    tones = _extract_tones(data)
    if not tones:
        return _empty_result()

    tone_array = np.array(tones)

    avg_tone = float(np.mean(tone_array))
    tone_vol = float(np.std(tone_array))
    tone_trend = _compute_linear_slope(tone_array)

    # Normalize to [-1, 1] — GDELT tone typically ranges from -10 to +10
    normalized = float(np.clip(avg_tone / 10.0, -1.0, 1.0))

    return {
        "keyword": keyword,
        "raw_tones": tones,
        "average_tone": round(avg_tone, 4),
        "tone_trend": round(tone_trend, 6),
        "tone_volatility": round(tone_vol, 4),
        "normalized_score": round(normalized, 4),
        "article_count": len(tones),
    }


def fetch_all_keywords(
    keywords: List[str], time_window_days: int
) -> Dict[str, Any]:
    """
    Aggregate GDELT tone data across all keywords.

    Returns:
        Composite GDELT result with aggregated metrics.
    """
    results = []
    total_articles = 0

    for kw in keywords:
        res = fetch_tone_timeline(kw, time_window_days)
        results.append(res)
        total_articles += res["article_count"]

    if total_articles == 0:
        return {
            "gdelt_score": 0.0,
            "gdelt_trend": 0.0,
            "gdelt_volatility": 0.0,
            "gdelt_article_count": 0,
            "keyword_breakdown": results,
        }

    # Weighted average by article count
    weighted_score = sum(
        r["normalized_score"] * r["article_count"] for r in results
    )
    weighted_trend = sum(
        r["tone_trend"] * r["article_count"] for r in results
    )
    weighted_vol = sum(
        r["tone_volatility"] * r["article_count"] for r in results
    )

    gdelt_score = weighted_score / total_articles if total_articles else 0.0
    gdelt_trend = weighted_trend / total_articles if total_articles else 0.0
    gdelt_vol = weighted_vol / total_articles if total_articles else 0.0

    return {
        "gdelt_score": round(float(np.clip(gdelt_score, -1.0, 1.0)), 4),
        "gdelt_trend": round(gdelt_trend, 6),
        "gdelt_volatility": round(gdelt_vol, 4),
        "gdelt_article_count": total_articles,
        "keyword_breakdown": results,
    }


# ─── Helpers ────────────────────────────────────────────────────────


def _extract_tones(data: Any) -> List[float]:
    """Extract tone values from GDELT API JSON response."""
    tones = []
    try:
        if isinstance(data, dict) and "timeline" in data:
            for series in data["timeline"]:
                if "data" in series:
                    for point in series["data"]:
                        if "value" in point:
                            tones.append(float(point["value"]))
        elif isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict) and "value" in entry:
                    tones.append(float(entry["value"]))
    except (ValueError, TypeError):
        pass
    return tones


def _compute_linear_slope(arr: np.ndarray) -> float:
    """Compute the linear regression slope as a trend indicator."""
    if len(arr) < 2:
        return 0.0
    x = np.arange(len(arr), dtype=float)
    slope, _ = np.polyfit(x, arr, 1)
    return float(slope)


def _empty_result() -> Dict[str, Any]:
    return {
        "keyword": "",
        "raw_tones": [],
        "average_tone": 0.0,
        "tone_trend": 0.0,
        "tone_volatility": 0.0,
        "normalized_score": 0.0,
        "article_count": 0,
    }
