"""
Reddit Sentiment Client.

Retrieves and scores public opinion from Reddit posts and comments
using Reddit's public JSON API (no authentication required).
Includes spam filtering, per-post sentiment scoring, and aggregate
metrics (average, acceleration, polarization).

Targets subreddits: r/wallstreetbets, r/stocks, r/cryptocurrency,
r/investing, r/economics, and keyword-based search.
"""

import re
import time
import hashlib
import requests
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

import config


# ─── Subreddit mapping by asset type ───────────────────────────────

_CRYPTO_SUBS = ["cryptocurrency", "Bitcoin", "CryptoMarkets", "ethtrader"]
_STOCK_SUBS = ["wallstreetbets", "stocks", "investing", "StockMarket"]
_MACRO_SUBS = ["economics", "finance", "wallstreetbets"]

_CRYPTO_TICKERS = {"BTC", "ETH", "SOL", "ADA", "XRP", "DOGE", "DOT", "AVAX", "MATIC", "LINK"}

# ─── Simple lexicon-based sentiment scorer ──────────────────────────

_POSITIVE_WORDS = {
    "bullish", "moon", "pump", "rally", "breakout", "buy", "long",
    "surge", "soar", "gain", "profit", "growth", "strong", "up",
    "optimistic", "recovery", "boom", "green", "opportunity", "huge",
    "amazing", "great", "excellent", "love", "best", "win", "winning",
    "higher", "rising", "uptrend", "accumulate", "undervalued",
    "diamond", "hands", "hold", "hodl", "rocket", "tendies",
}
_NEGATIVE_WORDS = {
    "bearish", "crash", "dump", "sell", "short", "drop", "plunge",
    "fear", "panic", "loss", "recession", "weak", "down", "risk",
    "pessimistic", "collapse", "red", "disaster", "terrible", "worst",
    "scam", "fraud", "rug", "bubble", "overvalued", "falling", "tank",
    "crisis", "warning", "danger", "decline", "lower", "downtrend",
    "bagholder", "puts", "rekt", "dead",
}


def _score_text(text: str) -> float:
    """Score a single text snippet in [-1, 1] via lexicon matching."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    pos = len(words & _POSITIVE_WORDS)
    neg = len(words & _NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return float(np.clip((pos - neg) / total, -1.0, 1.0))


# ─── Spam / duplicate filtering ────────────────────────────────────


def _dedup_posts(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove exact-duplicate and near-duplicate posts."""
    seen_hashes = set()
    unique = []
    for p in posts:
        text = p.get("text", "")
        clean = re.sub(r"https?://\S+", "", text.lower())
        clean = re.sub(r"\s+", " ", clean).strip()
        h = hashlib.md5(clean.encode()).hexdigest()
        if h not in seen_hashes and len(clean) > 15:
            seen_hashes.add(h)
            unique.append(p)
    return unique


def _is_spam(text: str) -> bool:
    """Heuristic spam detector for Reddit."""
    lower = text.lower()
    spam_signals = [
        "click here", "free giveaway", "dm me", "100x guaranteed",
        "join my discord", "join telegram", "guaranteed profit",
        "not financial advice but trust me", "send me",
    ]
    if any(s in lower for s in spam_signals):
        return True
    if len(text) < 10:
        return True
    return False


# ─── Reddit public JSON API ────────────────────────────────────────

_HEADERS = {
    "User-Agent": "SentimentAgent/1.0 (market sentiment analysis bot)",
}


def _get_subreddits_for_asset(asset: str) -> List[str]:
    """Determine relevant subreddits based on the asset."""
    upper = asset.upper()
    if upper in _CRYPTO_TICKERS or upper in {"CRYPTO", "BITCOIN", "ETHEREUM"}:
        return _CRYPTO_SUBS
    elif upper in {"GOLD", "OIL", "SILVER", "COMMODITIES"}:
        return _MACRO_SUBS
    else:
        return _STOCK_SUBS


def _fetch_subreddit_posts(
    subreddit: str, keyword: str, time_window_days: int, limit: int = 25
) -> List[Dict[str, Any]]:
    """Fetch posts from a subreddit's search endpoint (public JSON)."""
    time_filter = "day" if time_window_days <= 1 else (
        "week" if time_window_days <= 7 else "month"
    )

    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {
        "q": keyword,
        "sort": "relevance",
        "t": time_filter,
        "limit": limit,
        "restrict_sr": "on",
    }

    try:
        resp = requests.get(url, headers=_HEADERS, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[Reddit] Error fetching r/{subreddit} for '{keyword}': {e}")
        return []

    posts = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        text = f"{title} {selftext}".strip()

        if not text:
            continue

        created_utc = post.get("created_utc", 0)
        # Filter by actual time window
        cutoff = (datetime.now(timezone.utc) - timedelta(days=time_window_days)).timestamp()
        if created_utc < cutoff:
            continue

        posts.append({
            "text": text[:1000],  # Cap text length
            "created_at": datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat(),
            "score": post.get("score", 0),
            "num_comments": post.get("num_comments", 0),
            "subreddit": subreddit,
            "permalink": post.get("permalink", ""),
        })

    return posts


def _fetch_reddit_search(
    keyword: str, time_window_days: int, limit: int = 25
) -> List[Dict[str, Any]]:
    """Fetch posts from Reddit's global search (public JSON)."""
    time_filter = "day" if time_window_days <= 1 else (
        "week" if time_window_days <= 7 else "month"
    )

    url = "https://www.reddit.com/search.json"
    params = {
        "q": keyword,
        "sort": "relevance",
        "t": time_filter,
        "limit": limit,
    }

    try:
        resp = requests.get(url, headers=_HEADERS, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[Reddit] Error in global search for '{keyword}': {e}")
        return []

    posts = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        text = f"{title} {selftext}".strip()

        if not text:
            continue

        created_utc = post.get("created_utc", 0)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=time_window_days)).timestamp()
        if created_utc < cutoff:
            continue

        posts.append({
            "text": text[:1000],
            "created_at": datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat(),
            "score": post.get("score", 0),
            "num_comments": post.get("num_comments", 0),
            "subreddit": post.get("subreddit", "unknown"),
            "permalink": post.get("permalink", ""),
        })

    return posts


# ─── Public interface ───────────────────────────────────────────────


def fetch_and_score(
    keywords: List[str],
    time_window_days: int,
    asset: str = "",
) -> Dict[str, Any]:
    """
    Fetch Reddit posts for all keywords, clean, score, and aggregate.

    Returns:
        Dict with reddit_score, sentiment_acceleration, polarization_index,
        post_count.
    """
    all_posts: List[Dict[str, Any]] = []

    # Determine relevant subreddits
    subreddits = _get_subreddits_for_asset(asset or keywords[0])

    for kw in keywords:
        # Search targeted subreddits
        for sub in subreddits[:3]:  # Top 3 most relevant
            posts = _fetch_subreddit_posts(sub, kw, time_window_days, limit=config.REDDIT_MAX_RESULTS)
            all_posts.extend(posts)
            time.sleep(1.2)  # Respect Reddit rate limits

        # Also do a global search
        global_posts = _fetch_reddit_search(kw, time_window_days, limit=config.REDDIT_MAX_RESULTS)
        all_posts.extend(global_posts)
        time.sleep(1.2)

    # ── Clean ──
    all_posts = _dedup_posts(all_posts)
    all_posts = [p for p in all_posts if not _is_spam(p.get("text", ""))]

    if not all_posts:
        return {
            "reddit_score": 0.0,
            "sentiment_acceleration": 0.0,
            "polarization_index": 0.0,
            "post_count": 0,
        }

    # ── Score each post (weighted by engagement) ──
    scores = []
    timestamps = []
    for p in all_posts:
        base_score = _score_text(p.get("text", ""))

        # Weight by engagement: high-upvote posts matter more
        upvotes = max(p.get("score", 1), 1)
        engagement_weight = min(1.0 + np.log10(upvotes) * 0.1, 2.0)
        weighted_score = float(np.clip(base_score * engagement_weight, -1.0, 1.0))

        scores.append(weighted_score)
        try:
            ts = datetime.fromisoformat(
                p["created_at"].replace("Z", "+00:00")
            )
            timestamps.append(ts.timestamp())
        except Exception:
            timestamps.append(0.0)

    scores_arr = np.array(scores)
    ts_arr = np.array(timestamps)

    # ── Aggregate metrics ──
    avg_sentiment = float(np.mean(scores_arr))

    # Polarization = variance of scores
    polarization = float(np.var(scores_arr))

    # Acceleration = slope of sentiment over time
    acceleration = 0.0
    if len(scores_arr) >= 2 and np.std(ts_arr) > 0:
        order = np.argsort(ts_arr)
        sorted_scores = scores_arr[order]
        x = np.arange(len(sorted_scores), dtype=float)
        try:
            slope, _ = np.polyfit(x, sorted_scores, 1)
            acceleration = float(slope)
        except Exception:
            acceleration = 0.0

    # Normalize final score to [-1, 1]
    reddit_score = float(np.clip(avg_sentiment, -1.0, 1.0))

    # Keep top posts by engagement for content-based explanation
    top_posts = sorted(all_posts, key=lambda p: p.get("score", 0), reverse=True)[:10]

    return {
        "reddit_score": round(reddit_score, 4),
        "sentiment_acceleration": round(acceleration, 6),
        "polarization_index": round(polarization, 4),
        "post_count": len(all_posts),
        "top_posts": top_posts,
    }
