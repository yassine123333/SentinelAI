"""
GDELT Tone API Client.

Retrieves macro/institutional news sentiment using the GDELT DOC 2.0 API
(mode=timelinetone) for a list of keywords within a specified time window.

Performance notes:
  - Results are cached for 30 minutes keyed on (keyword, window, date-bucket)
    so repeated pipeline runs skip the HTTP round-trip entirely.
  - All keywords for a single run are fetched in parallel via a thread pool
    (GDELT is a public HTTP API, ThreadPoolExecutor is appropriate here).
  - Timeout is 20 s (GDELT responds in < 5 s on a healthy connection; 60 s
    was masking hangs).  Single retry on network errors; no retry on 4xx.
"""

import time as _time
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any

import numpy as np
import requests
from cachetools import TTLCache

import config

# ─── Settings ───────────────────────────────────────────────────────────────
GDELT_TIMEOUT       = 20    # seconds — reduced from 60
GDELT_MAX_RETRIES   = 2     # total attempts per keyword — reduced from 3
GDELT_RETRY_BACKOFF = 2     # seconds base backoff — reduced from 5
GDELT_MAX_WORKERS   = 4     # parallel threads for keyword fetches

# Cache: 30-minute TTL, max 256 entries (keyword × time-window combinations)
_GDELT_CACHE: TTLCache = TTLCache(maxsize=256, ttl=30 * 60)


# ─── URL builder ────────────────────────────────────────────────────────────

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


# ─── HTTP with retry ─────────────────────────────────────────────────────────

def _request_with_retry(url: str, keyword: str) -> requests.Response:
    """
    Send GET request with retry + fixed backoff.
    Raises the last exception if all retries fail.
    Does NOT retry on 4xx client errors (rate limit etc.).
    """
    last_err: Exception | None = None
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
            print(f"[GDELT] ✗ Timeout for '{keyword}' (attempt {attempt}).")
            if attempt < GDELT_MAX_RETRIES:
                _time.sleep(GDELT_RETRY_BACKOFF)
        except requests.exceptions.ConnectionError as e:
            last_err = e
            print(f"[GDELT] ✗ Connection error for '{keyword}' (attempt {attempt}).")
            if attempt < GDELT_MAX_RETRIES:
                _time.sleep(GDELT_RETRY_BACKOFF)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and 400 <= e.response.status_code < 500:
                print(f"[GDELT] ✗ HTTP {e.response.status_code} for '{keyword}' — not retrying.")
                raise
            last_err = e
            print(f"[GDELT] ✗ HTTP error for '{keyword}' (attempt {attempt}).")
            if attempt < GDELT_MAX_RETRIES:
                _time.sleep(GDELT_RETRY_BACKOFF)
    raise last_err  # type: ignore[misc]


# ─── Single keyword fetch (with cache) ──────────────────────────────────────

def fetch_tone_timeline(
    keyword: str, time_window_days: int
) -> Dict[str, Any]:
    """
    Fetch tone timeline from GDELT for a single keyword.
    Results are cached for 30 minutes.
    """
    # Cache key: keyword + window + current date (so results stay valid
    # throughout a trading session but refresh each day).
    date_bucket = datetime.date.today().isoformat()
    cache_key = (keyword, time_window_days, date_bucket)
    if cache_key in _GDELT_CACHE:
        print(f"[GDELT] Cache HIT for '{keyword}'")
        return _GDELT_CACHE[cache_key]

    end_dt = datetime.datetime.utcnow()
    start_dt = end_dt - datetime.timedelta(days=time_window_days)
    start_str = start_dt.strftime("%Y%m%d%H%M%S")
    end_str = end_dt.strftime("%Y%m%d%H%M%S")

    url = _build_gdelt_url(keyword, start_str, end_str)

    try:
        resp = _request_with_retry(url, keyword)
        data = resp.json()
    except Exception as e:
        print(f"[GDELT] ✗ All retries failed for '{keyword}': {e}")
        return _empty_result()

    tones = _extract_tones(data)
    if not tones:
        return _empty_result()

    tone_array = np.array(tones)
    avg_tone   = float(np.mean(tone_array))
    tone_vol   = float(np.std(tone_array))
    tone_trend = _compute_linear_slope(tone_array)
    normalized = float(np.clip(avg_tone / 10.0, -1.0, 1.0))

    result = {
        "keyword":          keyword,
        "raw_tones":        tones,
        "average_tone":     round(avg_tone, 4),
        "tone_trend":       round(tone_trend, 6),
        "tone_volatility":  round(tone_vol, 4),
        "normalized_score": round(normalized, 4),
        "article_count":    len(tones),
    }
    _GDELT_CACHE[cache_key] = result
    return result


# ─── All keywords — parallel fetch ──────────────────────────────────────────

def fetch_all_keywords(
    keywords: List[str], time_window_days: int
) -> Dict[str, Any]:
    """
    Aggregate GDELT tone data across all keywords.

    All keywords are fetched in parallel (up to GDELT_MAX_WORKERS threads).
    Each result is also cached, so a second pipeline run within 30 minutes
    completes instantly.
    """
    if not keywords:
        return _empty_aggregate([])

    results: list[Dict[str, Any]] = [{}] * len(keywords)

    with ThreadPoolExecutor(max_workers=min(GDELT_MAX_WORKERS, len(keywords))) as pool:
        future_to_idx = {
            pool.submit(fetch_tone_timeline, kw, time_window_days): i
            for i, kw in enumerate(keywords)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                print(f"[GDELT] ✗ Worker error for keyword[{idx}]: {exc}")
                results[idx] = _empty_result()

    return _empty_aggregate(results)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _empty_aggregate(results: list) -> Dict[str, Any]:
    total_articles = sum(r.get("article_count", 0) for r in results)
    if total_articles == 0:
        return {
            "gdelt_score":         0.0,
            "gdelt_trend":         0.0,
            "gdelt_volatility":    0.0,
            "gdelt_article_count": 0,
            "keyword_breakdown":   results,
        }
    weighted_score = sum(r["normalized_score"] * r["article_count"] for r in results)
    weighted_trend = sum(r["tone_trend"]        * r["article_count"] for r in results)
    weighted_vol   = sum(r["tone_volatility"]   * r["article_count"] for r in results)
    return {
        "gdelt_score":         round(float(np.clip(weighted_score / total_articles, -1.0, 1.0)), 4),
        "gdelt_trend":         round(weighted_trend / total_articles, 6),
        "gdelt_volatility":    round(weighted_vol   / total_articles, 4),
        "gdelt_article_count": total_articles,
        "keyword_breakdown":   results,
    }


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
        "keyword":          "",
        "raw_tones":        [],
        "average_tone":     0.0,
        "tone_trend":       0.0,
        "tone_volatility":  0.0,
        "normalized_score": 0.0,
        "article_count":    0,
    }
