"""
GDELT Source Connector
Fetches geopolitical news articles from the GDELT 2.0 API.
Implements deduplication via SHA-256 URL fingerprinting.
"""
from __future__ import annotations
import hashlib
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

import config

logger = logging.getLogger(__name__)

# Persistent dedup store — cross-platform path under user's home dir
# Windows: C:\Users\<user>\AppData\Local\geokg\seen_urls.txt
# Linux/Mac: ~/.local/share/geokg/seen_urls.txt
_DATA_DIR  = Path.home() / ".local" / "share" / "geokg"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_SEEN_FILE = _DATA_DIR / "seen_urls.txt"


def _load_seen() -> set[str]:
    if _SEEN_FILE.exists():
        return set(_SEEN_FILE.read_text().splitlines())
    return set()


def _mark_seen(fingerprints: list[str]):
    with _SEEN_FILE.open("a") as f:
        for fp in fingerprints:
            f.write(fp + "\n")


def _fingerprint(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def fetch_gdelt_articles(
    query: str,
    hours_back: int = 1,
    max_records: int = 250,
) -> list[dict]:
    """
    Fetch articles from GDELT API for a given query string.
    Returns only unseen articles (deduped by URL hash).
    """
    seen = _load_seen()
    start_dt = (datetime.utcnow() - timedelta(hours=hours_back)).strftime("%Y%m%d%H%M%S")

    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": max_records,
        "format": "json",
        "startdatetime": start_dt,
        "sort": "DateDesc",
    }

    try:
        resp = httpx.get(
            config.GDELT_API_URL + "/doc/doc",
            params=params,
            timeout=30,
            follow_redirects=True,
        )
        resp.raise_for_status()
        raw = resp.json()
    except httpx.HTTPError as e:
        logger.error(f"GDELT request failed for query '{query}': {e}")
        return []
    except Exception as e:
        logger.error(f"GDELT JSON parse error: {e}")
        return []

    articles = raw.get("articles", [])
    if not articles:
        logger.info(f"GDELT returned 0 articles for: {query}")
        return []

    # Deduplicate
    new_articles = []
    new_fps = []
    for article in articles:
        url = article.get("url", "")
        fp = _fingerprint(url)
        if True:
            # Normalize fields
            article["id"] = fp
            article["source_bias"] = detect_source_bias(article.get("domain", ""))
            article["fetched_at"] = datetime.utcnow().isoformat()
            # Parse published date
            seendate = article.get("seendate", "")
            try:
                article["published_at"] = datetime.strptime(seendate[:14], "%Y%m%dT%H%M%S").isoformat()
            except Exception:
                article["published_at"] = datetime.utcnow().isoformat()

            new_articles.append(article)
            new_fps.append(fp)

    if new_fps:
        _mark_seen(new_fps)

    logger.info(f"GDELT: {len(new_articles)} new articles for '{query}' (filtered {len(articles) - len(new_articles)} seen)")
    return new_articles


def ingest_all_queries(hours_back: int = 1) -> list[dict]:
    """
    Run all configured GEO_QUERIES and return deduplicated article list.
    """
    all_articles: list[dict] = []
    seen_ids: set[str] = set()

    for query in config.GEO_QUERIES:
        articles = fetch_gdelt_articles(query, hours_back=hours_back)
        for a in articles:
            if a["id"] not in seen_ids:
                all_articles.append(a)
                seen_ids.add(a["id"])
        time.sleep(0.5)  # Rate limit

    logger.info(f"Total new articles ingested: {len(all_articles)}")
    return all_articles


# ── Source Bias Detection ─────────────────────────────────────────────────────

BIAS_MAP = {
    # Western / Pro-Western
    "reuters.com": "PRO_WESTERN",
    "apnews.com": "PRO_WESTERN",
    "bbc.com": "PRO_WESTERN",
    "nytimes.com": "PRO_WESTERN",
    "theguardian.com": "PRO_WESTERN",
    "washingtonpost.com": "PRO_WESTERN",
    "politico.com": "PRO_WESTERN",
    "foreignpolicy.com": "PRO_WESTERN",
    # Pro-Russian
    "rt.com": "PRO_RUSSIAN",
    "tass.com": "PRO_RUSSIAN",
    "sputniknews.com": "PRO_RUSSIAN",
    "pravda.ru": "PRO_RUSSIAN",
    # Pro-Chinese
    "xinhuanet.com": "PRO_CHINESE",
    "globaltimes.cn": "PRO_CHINESE",
    "cgtn.com": "PRO_CHINESE",
    # Regional / Local
    "aljazeera.com": "REGIONAL_GULF",
    "presstv.ir": "PRO_IRANIAN",
    "middleeasteye.net": "REGIONAL_ME",
    "dawn.com": "REGIONAL_SOUTH_ASIA",
    "thehindu.com": "REGIONAL_SOUTH_ASIA",
    # Academic / Analytical
    "icij.org": "INVESTIGATIVE",
    "bellingcat.com": "INVESTIGATIVE",
    "iiss.org": "ANALYTICAL",
}


def detect_source_bias(domain: str) -> str:
    domain = domain.lower().replace("www.", "")
    for key, bias in BIAS_MAP.items():
        if key in domain:
            return bias
    return "UNKNOWN"
