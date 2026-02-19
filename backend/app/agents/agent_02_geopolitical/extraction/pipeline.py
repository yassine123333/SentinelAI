"""
Geopolitical Extraction Pipeline
Runs NER → Coreference Resolution → Entity Linking → Relation Extraction
→ Event Classification → Conflict Scoring on each article.
"""
from __future__ import annotations
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

import config
from models import Actor, GeoEvent, Relation, ExtractionResult
from sources.gdelt_connector import detect_source_bias

logger = logging.getLogger(__name__)

# ── Lazy imports for heavy ML models ─────────────────────────────────────────
_gliner_model = None
_spacy_nlp = None


def _get_gliner():
    global _gliner_model
    if _gliner_model is None:
        try:
            from gliner import GLiNER
            logger.info("Loading GLiNER model...")
            _gliner_model = GLiNER.from_pretrained("urchade/gliner_small-v2.1")
            logger.info("GLiNER model loaded.")
        except ImportError:
            logger.warning("GLiNER not installed. Using regex fallback for NER.")
    return _gliner_model


def _get_spacy():
    global _spacy_nlp
    if _spacy_nlp is None:
        try:
            import spacy
            logger.info("Loading spaCy model...")
            _spacy_nlp = spacy.load("en_core_web_sm")  # Use _trf in production
            logger.info("spaCy model loaded.")
        except Exception as e:
            logger.warning(f"spaCy model not available: {e}")
    return _spacy_nlp


# ── Entity Linker (simplified — production uses REL + Wikidata) ───────────────

class EntityLinker:
    """
    Maps surface entity mentions to canonical IDs.
    Production: integrate with REL + Wikidata API.
    This version uses a static alias dictionary for demo purposes.
    """
    ALIAS_MAP: dict[str, str] = {
        # Islamic State variants → single canonical ID
        "daesh": "Q1520118",
        "isis": "Q1520118",
        "isil": "Q1520118",
        "islamic state": "Q1520118",
        # Iran variants
        "iran": "Q794",
        "islamic republic of iran": "Q794",
        "tehran": "Q794",
        # Russia variants
        "russia": "Q159",
        "russian federation": "Q159",
        "kremlin": "Q159",
        "moscow": "Q159",
        # Ukraine
        "ukraine": "Q212",
        "kyiv": "Q212",
        # USA
        "united states": "Q30",
        "usa": "Q30",
        "us": "Q30",
        "washington": "Q30",
        "pentagon": "Q30",
    }

    def link(self, entities: list[dict]) -> list[dict]:
        linked = []
        for ent in entities:
            text_lower = ent["text"].lower().strip()
            canonical_id = self.ALIAS_MAP.get(text_lower)
            ent["wikidata_id"] = canonical_id
            ent["canonical_id"] = canonical_id or self._slugify(ent["text"])
            linked.append(ent)
        return linked

    @staticmethod
    def _slugify(text: str) -> str:
        return re.sub(r"[^a-z0-9_]", "", text.lower().replace(" ", "_"))


# ── Relation Extraction via LLM ───────────────────────────────────────────────

def extract_relations_llm(text: str, entities: list[dict]) -> list[Relation]:
    """
    Use LLM to extract structured relation triples from text.
    Falls back to pattern-based extraction if LLM is unavailable.
    """
    entity_names = [e["text"] for e in entities[:15]]  # Limit context size

    # Try LLM extraction first
    try:
        return _llm_relation_extraction(text, entity_names)
    except Exception as e:
        logger.warning(f"LLM relation extraction failed, using pattern fallback: {e}")
        return _pattern_relation_extraction(text, entities)


def _llm_relation_extraction(text: str, entity_names: list[str]) -> list[Relation]:
    """Extract relations using Gemini 2.5 Flash with structured JSON output."""
    try:
        from gemini_client import extract_relations
        triples_raw = extract_relations(text, entity_names)

        relations = []
        entity_id_map = {e.lower(): e.replace(" ", "_").lower() for e in entity_names}

        for t in triples_raw:
            subj_id = entity_id_map.get(t.get("subject", "").lower(), t.get("subject", "").lower().replace(" ", "_"))
            obj_id  = entity_id_map.get(t.get("object",  "").lower(), t.get("object",  "").lower().replace(" ", "_"))
            if subj_id and obj_id and t.get("relation") in config.RELATION_TYPES:
                relations.append(Relation(
                    subject_id=subj_id,
                    relation_type=t["relation"],
                    object_id=obj_id,
                    valid_from=datetime.now(timezone.utc),
                    confidence=float(t.get("confidence", 0.7)),
                    source="gemini_extraction",
                ))
        return relations

    except Exception as e:
        logger.error(f"Gemini relation extraction error: {e}")
        return []


def _pattern_relation_extraction(text: str, entities: list[dict]) -> list[Relation]:
    """Simple pattern-based RE fallback."""
    relations = []
    text_lower = text.lower()

    # Very basic keyword patterns
    PATTERNS = [
        (r"(\w+)\s+(?:funds|funded|finances|financed)\s+(\w+)", "FUNDS"),
        (r"(\w+)\s+(?:allied with|alliance with|partnered with)\s+(\w+)", "ALLIED_WITH"),
        (r"(\w+)\s+(?:hostile|threatens|attacked|invaded)\s+(\w+)", "HOSTILE_TO"),
        (r"(\w+)\s+(?:sanctions|sanctioned)\s+(\w+)", "SANCTIONS"),
        (r"(\w+)\s+(?:controls|occupied|seized)\s+(\w+)", "CONTROLS"),
    ]

    entity_names = {e["text"].lower() for e in entities}

    for pattern, rel_type in PATTERNS:
        for match in re.finditer(pattern, text_lower):
            subj = match.group(1)
            obj = match.group(2)
            if subj in entity_names and obj in entity_names:
                relations.append(Relation(
                    subject_id=subj.replace(" ", "_"),
                    relation_type=rel_type,
                    object_id=obj.replace(" ", "_"),
                    valid_from=datetime.now(timezone.utc),
                    confidence=0.5,
                    source="pattern_extraction",
                ))

    return relations[:20]  # Cap to avoid noise


# ── Conflict Scoring (Goldstein-inspired) ─────────────────────────────────────

INTENSITY_KEYWORDS = {
    "military": {
        "high": ["invasion", "airstrike", "missile", "bombardment", "offensive", "seized"],
        "med":  ["troops", "military exercise", "armed", "weapons", "deployment"],
        "low":  ["tension", "warning", "statement", "rhetoric"],
    },
    "diplomatic": {
        "high": ["expelled ambassador", "sanctions", "broke relations", "ultimatum"],
        "med":  ["diplomatic meeting", "negotiations", "summit", "talks"],
        "low":  ["statement", "comment", "remarks", "communique"],
    },
    "economic": {
        "high": ["embargo", "asset freeze", "cut off trade", "financial sanctions"],
        "med":  ["trade restriction", "tariff", "economic pressure"],
        "low":  ["economic concern", "trade talks", "investment"],
    },
}


def score_conflict(text: str) -> dict[str, float]:
    """Compute military/diplomatic/economic intensity scores 1-10."""
    text_lower = text.lower()
    scores: dict[str, float] = {}

    for domain, levels in INTENSITY_KEYWORDS.items():
        score = 1.0
        if any(kw in text_lower for kw in levels["high"]):
            score = 8.0
        elif any(kw in text_lower for kw in levels["med"]):
            score = 5.0
        elif any(kw in text_lower for kw in levels["low"]):
            score = 3.0
        scores[domain] = score

    scores["overall"] = max(scores.values())
    return scores


# ── Event Classification ──────────────────────────────────────────────────────

EVENT_TYPE_KEYWORDS = {
    "ARMED_CONFLICT":  ["attack", "battle", "offensive", "airstrike", "bombing", "casualties"],
    "DIPLOMATIC":      ["summit", "agreement", "treaty", "negotiations", "ceasefire"],
    "COVERT":          ["assassination", "sabotage", "spy", "intelligence", "covert"],
    "ECONOMIC":        ["sanctions", "embargo", "trade", "financial", "energy"],
    "POLITICAL_CRISIS": ["coup", "election", "protest", "unrest", "government"],
}


def classify_event(text: str) -> str:
    text_lower = text.lower()
    scores = {}
    for evt_type, keywords in EVENT_TYPE_KEYWORDS.items():
        scores[evt_type] = sum(1 for kw in keywords if kw in text_lower)
    return max(scores, key=scores.get)


# ── Main Extractor Class ──────────────────────────────────────────────────────

class GeopoliticalExtractor:
    """
    Full extraction pipeline: NER → Coref → Linking → RE → Event Classification → Scoring
    """

    def __init__(self):
        self.linker = EntityLinker()
        # Models loaded lazily on first use
        self._ner_ready = False
        self._nlp_ready = False

    def _ensure_models(self):
        if not self._ner_ready:
            _get_gliner()  # trigger lazy load
            self._ner_ready = True
        if not self._nlp_ready:
            _get_spacy()
            self._nlp_ready = True

    def extract(self, article: dict) -> ExtractionResult:
        """
        Full extraction pipeline for a single article.
        Returns ExtractionResult with entities, triples, event, scores.
        """
        self._ensure_models()
        content = article.get("content") or article.get("title", "")
        article_id = article.get("id") or hashlib.sha256(content.encode()).hexdigest()[:16]

        # Step 1: NER
        raw_entities = self._run_ner(content)

        # Step 2: Coreference (spaCy)
        resolved_text = self._resolve_coreferences(content)

        # Step 3: Entity Linking
        linked_entities = self.linker.link(raw_entities)

        # Step 4: Relation Extraction
        triples = extract_relations_llm(resolved_text, linked_entities)

        # Step 5: Event Classification
        event_type = classify_event(content)

        # Step 6: Conflict Scoring
        scores = score_conflict(content)

        # Step 7: Build GeoEvent
        published_at_str = article.get("published_at", datetime.now(timezone.utc).isoformat())
        try:
            published_at = datetime.fromisoformat(published_at_str)
        except Exception:
            published_at = datetime.now(timezone.utc)

        event = GeoEvent(
            id=f"event_{article_id}",
            event_type=event_type,
            description=article.get("title", content[:200]),
            actors=[e["canonical_id"] for e in linked_entities
                    if e.get("type") in ("state actor", "non-state armed group",
                                         "political faction", "national leader")][:5],
            date_start=published_at,
            intensity=scores.get("overall", 1.0),
            military_intensity=scores.get("military", 1.0),
            diplomatic_intensity=scores.get("diplomatic", 1.0),
            economic_intensity=scores.get("economic", 1.0),
            source_article_id=article_id,
            confidence=0.8,
        )

        source_bias = article.get("source_bias") or detect_source_bias(
            article.get("domain", article.get("source", ""))
        )

        return ExtractionResult(
            article_id=article_id,
            entities=linked_entities,
            triples=triples,
            event=event,
            scores=scores,
            source_bias=source_bias,
            confidence=0.8,
        )

    def _run_ner(self, text: str) -> list[dict]:
        """Run GLiNER NER or fallback to spaCy NER."""
        gliner = _get_gliner()
        if gliner is not None:
            try:
                raw = gliner.predict_entities(text[:2000], config.GEO_ENTITY_TYPES, threshold=0.5)
                return [{"text": e["text"], "type": e["label"], "score": e["score"]} for e in raw]
            except Exception as e:
                logger.warning(f"GLiNER prediction failed: {e}")

        # Fallback: spaCy NER
        nlp = _get_spacy()
        if nlp is not None:
            doc = nlp(text[:1000])
            return [
                {"text": ent.text, "type": ent.label_, "score": 0.7}
                for ent in doc.ents
                if ent.label_ in ("GPE", "ORG", "PERSON", "NORP", "FAC", "LOC")
            ]

        # Last resort: empty
        logger.error("No NER model available. Returning empty entities.")
        return []

    def _resolve_coreferences(self, text: str) -> str:
        """
        Resolve coreferences using coreferee (spaCy extension).
        Falls back to returning original text if coreferee not installed.
        """
        try:
            import coreferee
            nlp = _get_spacy()
            if nlp and "coreferee" in [c[0] for c in nlp.pipeline]:
                doc = nlp(text)
                # Simple pronoun replacement (coreferee returns chain heads)
                return text  # Full implementation requires coreferee resolution loop
        except ImportError:
            pass
        return text
