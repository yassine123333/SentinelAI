"""
RAG Input Parser — Understands and extracts essential information.

Handles both structured JSON input and free-text natural language input.
Uses Groq for NLU (Natural Language Understanding) when the input is
unstructured, extracting asset, keywords, and time window.
"""

import json
import os
import re
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional


EXTRACTION_PROMPT = """You are an input parser for a Market Sentiment Intelligence system.

Given the user's message, extract the following fields:
- asset: The primary financial asset or topic (e.g., "BTC", "AAPL", "Gold", "Oil")
- keywords: A list of relevant search keywords for news and social media (3-6 keywords)
- time_window_days: Number of days to look back for data (integer, default 7)

Rules:
- If the user mentions a crypto, stock, commodity, or macro topic, extract it as the asset.
- Generate keywords that would match relevant news and social media posts.
- Include the asset's full name and ticker/abbreviation as keywords.
- If the user specifies a time range (e.g., "last 3 days"), extract it.
- If unclear, default time_window_days to 7.

Return ONLY valid JSON in this format:
{
  "asset": "<string>",
  "keywords": ["<kw1>", "<kw2>", ...],
  "time_window_days": <integer>,
  "extracted_entities": ["<entity1>", ...],
  "intent": "<sentiment_analysis | market_check | news_scan | general>"
}

Do not include markdown. Return JSON only."""

COMPARISON_EXTRACTION_PROMPT = """You are an input parser for a Market Sentiment Intelligence system.

The user wants to COMPARE multiple financial assets. Extract ALL assets mentioned.

Return ONLY valid JSON in this format:
{
  "assets_list": [
    { "ticker": "<TICKER>", "name": "<Full Name>", "keywords": ["<kw1>", "<kw2>", ...] },
    { "ticker": "<TICKER>", "name": "<Full Name>", "keywords": ["<kw1>", "<kw2>", ...] }
  ],
  "time_window_days": <integer>,
  "extracted_entities": ["<entity1>", ...]
}

Do not include markdown. Return JSON only."""

_GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")


class InputParser:
    """Parses and normalizes input for the Sentiment Agent."""

    def __init__(self, groq_api_key: str = "", **_kwargs):
        self._groq_key = groq_api_key

    def parse(self, raw_input: Any) -> Dict[str, Any]:
        """
        Parse any input format into a structured agent request.

        Accepts:
            - Dict with asset/keywords/time_window_days
            - JSON string
            - Free-text natural language query

        Returns:
            Normalized dict with: asset, keywords, time_window_days,
            input_hash, parsed_at, source_format, extracted_entities.
        """
        if isinstance(raw_input, dict):
            return self._from_structured(raw_input)

        raw_str = str(raw_input).strip()

        if raw_str.startswith("{"):
            try:
                parsed = json.loads(raw_str)
                return self._from_structured(parsed)
            except json.JSONDecodeError:
                pass

        return self._from_freetext(raw_str)

    def _from_structured(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a structured dict input."""
        asset = data.get("asset", "").strip()
        keywords = data.get("keywords", [])
        time_window = data.get("time_window_days", 7)

        if not asset:
            raise ValueError("Structured input must include 'asset'.")
        if not keywords:
            keywords = [asset]

        keywords = [str(k).strip() for k in keywords if str(k).strip()]

        return self._build_result(
            asset=asset,
            keywords=keywords,
            time_window_days=int(time_window),
            source_format="structured",
            extracted_entities=[asset],
            intent="sentiment_analysis",
            raw_input=data,
        )

    def _from_freetext(self, text: str) -> Dict[str, Any]:
        """Extract structured fields from free-text using Groq."""
        text_lower = text.lower()
        is_comparison = any(re.search(p, text_lower) for p in self._COMPARISON_PATTERNS)

        if is_comparison:
            comparison = self._quick_extract_comparison(text)
            if comparison:
                return comparison
            groq_comp = self._from_freetext_comparison(text)
            if groq_comp:
                return groq_comp

        quick = self._quick_extract(text)
        if quick:
            return quick

        # Fall back to Groq NLU
        try:
            extracted = self._call_groq(
                EXTRACTION_PROMPT,
                f"Extract market sentiment analysis intent from: {text}",
            )
            return self._build_result(
                asset=extracted.get("asset", "UNKNOWN"),
                keywords=extracted.get("keywords", [extracted.get("asset", text)]),
                time_window_days=extracted.get("time_window_days", 7),
                source_format="freetext_groq",
                extracted_entities=extracted.get("extracted_entities", []),
                intent=extracted.get("intent", "sentiment_analysis"),
                raw_input=text,
            )

        except Exception as e:
            print(f"[Parser] Groq extraction failed: {e}")
            return self._build_result(
                asset=text[:50],
                keywords=[text[:50]],
                time_window_days=7,
                source_format="freetext_fallback",
                extracted_entities=[],
                intent="general",
                raw_input=text,
            )

    def _from_freetext_comparison(self, text: str) -> Optional[Dict[str, Any]]:
        """Use Groq to extract multiple assets for comparison queries."""
        try:
            print("[Parser] Using Groq for multi-asset comparison extraction...")
            extracted = self._call_groq(
                COMPARISON_EXTRACTION_PROMPT,
                f"Extract all assets for comparison from: {text}",
            )
            assets_list = extracted.get("assets_list", [])

            if len(assets_list) < 2:
                return None

            days = extracted.get("time_window_days", 7)
            primary = assets_list[0]
            all_keywords = []
            all_entities = extracted.get("extracted_entities", [])
            for a in assets_list:
                all_keywords.extend(a.get("keywords", [a.get("ticker", "")]))
                if a.get("ticker") and a["ticker"] not in all_entities:
                    all_entities.append(a["ticker"])

            result = self._build_result(
                asset=primary.get("ticker", "UNKNOWN"),
                keywords=list(dict.fromkeys(all_keywords)),
                time_window_days=days,
                source_format="freetext_groq",
                extracted_entities=list(dict.fromkeys(all_entities)),
                intent="comparison",
                raw_input=text,
            )
            result["is_comparison"] = True
            result["assets_list"] = assets_list
            return result

        except Exception as e:
            print(f"[Parser] Groq comparison extraction failed: {e}")
            return None

    def _call_groq(self, system_prompt: str, user_message: str) -> Dict[str, Any]:
        """Call Groq API and return parsed JSON response."""
        from groq import Groq
        client = Groq(api_key=self._groq_key)
        resp = client.chat.completions.create(
            model=_GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=512,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3].strip()
        return json.loads(raw)

    # Known tickers / assets (class-level for reuse)
    KNOWN_ASSETS = {
        "BTC":    ("Bitcoin",   ["Bitcoin", "BTC", "crypto market"]),
        "ETH":    ("Ethereum",  ["Ethereum", "ETH", "crypto"]),
        "AAPL":   ("Apple",     ["Apple", "AAPL", "Apple stock"]),
        "GOOGL":  ("Google",    ["Google", "GOOGL", "Alphabet"]),
        "TSLA":   ("Tesla",     ["Tesla", "TSLA", "Elon Musk"]),
        "MSFT":   ("Microsoft", ["Microsoft", "MSFT", "Azure"]),
        "AMZN":   ("Amazon",    ["Amazon", "AMZN", "AWS"]),
        "GOLD":   ("Gold",      ["Gold", "XAU", "precious metals", "gold price"]),
        "OIL":    ("Oil",       ["crude oil", "WTI", "Brent", "oil price"]),
        "SPY":    ("S&P 500",   ["S&P 500", "SPY", "stock market"]),
        "SILVER": ("Silver",    ["Silver", "XAG", "silver price"]),
        "SOL":    ("Solana",    ["Solana", "SOL", "crypto"]),
        "NVDA":   ("Nvidia",    ["Nvidia", "NVDA", "GPU", "AI chips"]),
        "META":   ("Meta",      ["Meta", "META", "Facebook", "Metaverse"]),
    }

    _ASSET_ALIASES = {
        "petrol": "OIL", "petroleum": "OIL", "gasoline": "OIL",
        "gas": "OIL", "crude": "OIL", "brent": "OIL", "wti": "OIL",
        "bitcoin": "BTC", "btc": "BTC",
        "ethereum": "ETH", "ether": "ETH", "eth": "ETH",
        "gold": "GOLD", "xau": "GOLD",
        "silver": "SILVER", "xag": "SILVER",
        "apple": "AAPL", "aapl": "AAPL",
        "google": "GOOGL", "alphabet": "GOOGL",
        "tesla": "TSLA",
        "microsoft": "MSFT",
        "amazon": "AMZN",
        "nvidia": "NVDA",
        "solana": "SOL",
        "meta": "META", "facebook": "META",
        "s&p": "SPY", "spy": "SPY", "s&p 500": "SPY",
    }

    _COMPARISON_PATTERNS = [
        r"\bvs\.?\b", r"\bversus\b", r"\bcompare\b", r"\bcomparison\b",
        r"\bcompared\s+to\b", r"\bagainst\b", r"\bor\b.*\bwhich\b",
        r"\bwhich\s+(?:one|has|is)\b", r"\bbetween\b",
    ]

    def _quick_extract_comparison(self, text: str) -> Optional[Dict[str, Any]]:
        text_lower = text.lower()
        is_comparison = any(re.search(p, text_lower) for p in self._COMPARISON_PATTERNS)
        if not is_comparison:
            return None

        matched_tickers: set = set()
        matched = []

        text_upper = text.upper()
        for ticker, (name, kws) in self.KNOWN_ASSETS.items():
            if ticker in text_upper or name.upper() in text_upper:
                if ticker not in matched_tickers:
                    matched_tickers.add(ticker)
                    matched.append({"ticker": ticker, "name": name, "keywords": kws})

        words = set(re.findall(r"[a-z&]+(?:\s+\d+)?", text_lower))
        for alias, ticker in self._ASSET_ALIASES.items():
            if alias in words or alias in text_lower:
                if ticker not in matched_tickers:
                    matched_tickers.add(ticker)
                    name, kws = self.KNOWN_ASSETS[ticker]
                    matched.append({"ticker": ticker, "name": name, "keywords": kws})

        if len(matched) < 2:
            return None

        days = self._extract_days(text_lower)
        primary = matched[0]
        all_keywords = []
        all_entities = []
        for m in matched:
            all_keywords.extend(m["keywords"])
            all_entities.extend([m["ticker"], m["name"]])

        result = self._build_result(
            asset=primary["ticker"],
            keywords=list(dict.fromkeys(all_keywords)),
            time_window_days=days,
            source_format="freetext_rules",
            extracted_entities=list(dict.fromkeys(all_entities)),
            intent="comparison",
            raw_input=text,
        )
        result["is_comparison"] = True
        result["assets_list"] = matched
        return result

    def _quick_extract(self, text: str) -> Optional[Dict[str, Any]]:
        text_upper = text.upper()
        text_lower = text.lower()

        for ticker, (name, kws) in self.KNOWN_ASSETS.items():
            if ticker in text_upper or name.upper() in text_upper:
                return self._build_result(
                    asset=ticker, keywords=kws,
                    time_window_days=self._extract_days(text_lower),
                    source_format="freetext_rules",
                    extracted_entities=[ticker, name],
                    intent="sentiment_analysis", raw_input=text,
                )

        words = set(re.findall(r"[a-z&]+(?:\s+\d+)?", text_lower))
        for alias, ticker in self._ASSET_ALIASES.items():
            if alias in words or alias in text_lower:
                name, kws = self.KNOWN_ASSETS[ticker]
                return self._build_result(
                    asset=ticker, keywords=kws,
                    time_window_days=self._extract_days(text_lower),
                    source_format="freetext_rules",
                    extracted_entities=[ticker, name, alias],
                    intent="sentiment_analysis", raw_input=text,
                )

        return None

    @staticmethod
    def _extract_days(text: str) -> int:
        patterns = [
            (r"last\s+(\d+)\s*days?",             lambda m: int(m.group(1))),
            (r"past\s+(\d+)\s*days?",              lambda m: int(m.group(1))),
            (r"(\d+)\s*days?\s*(?:ago|back|window)", lambda m: int(m.group(1))),
            (r"(?:past|last)\s*week",              lambda _: 7),
            (r"(?:past|last)\s*month",             lambda _: 30),
            (r"today|24\s*h",                      lambda _: 1),
            (r"(?:past|last)\s*48\s*h",            lambda _: 2),
        ]
        for pattern, extractor in patterns:
            m = re.search(pattern, text)
            if m:
                return min(extractor(m), 30)
        return 7

    @staticmethod
    def _build_result(
        asset: str,
        keywords: List[str],
        time_window_days: int,
        source_format: str,
        extracted_entities: List[str],
        intent: str,
        raw_input: Any,
    ) -> Dict[str, Any]:
        input_str = json.dumps(raw_input) if isinstance(raw_input, dict) else str(raw_input)
        return {
            "asset":             asset,
            "keywords":          keywords,
            "time_window_days":  time_window_days,
            "input_hash":        hashlib.sha256(input_str.encode()).hexdigest()[:16],
            "parsed_at":         datetime.utcnow().isoformat(),
            "source_format":     source_format,
            "extracted_entities": extracted_entities,
            "intent":            intent,
        }
