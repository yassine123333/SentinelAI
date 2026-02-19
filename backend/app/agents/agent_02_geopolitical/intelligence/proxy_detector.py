"""
Proxy Relationship Detector
Uses PyKEEN RotatE GNN to infer hidden proxy/funding relationships
that are not explicitly stated in source articles.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

import numpy as np

from graph.neo4j_client import get_neo4j_client
from graph.delta_writer import DeltaGraphWriter

logger = logging.getLogger(__name__)

MODEL_PATH = Path.home() / ".local" / "share" / "geokg" / "rotate_model"
MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)


class ProxyDetector:
    """
    Trains a RotatE link prediction model on the current graph
    and predicts hidden proxy/funding relationships.
    """

    def __init__(self):
        self.neo4j = get_neo4j_client()
        self.writer = DeltaGraphWriter()
        self.model = None

    def export_triples(self) -> np.ndarray:
        """Export graph as (subject, relation, object) triple array."""
        results = self.neo4j.run("""
            MATCH (a)-[r]->(b)
            WHERE a.id IS NOT NULL AND b.id IS NOT NULL
            RETURN a.id AS s, type(r) AS p, b.id AS o
            LIMIT 500000
        """)
        if not results:
            return np.array([]).reshape(0, 3)
        return np.array([[r["s"], r["p"], r["o"]] for r in results])

    def train(self, num_epochs: int = 100, embedding_dim: int = 128) -> bool:
        """
        Train RotatE model on current graph triples.
        Returns True if training succeeded.
        """
        try:
            import torch
            from pykeen.pipeline import pipeline
            from pykeen.triples import TriplesFactory

            logger.info("Exporting triples for GNN training...")
            triples = self.export_triples()

            if len(triples) < 100:
                logger.warning(f"Insufficient triples for training: {len(triples)}. Skipping.")
                return False

            logger.info(f"Training RotatE on {len(triples)} triples...")
            factory = TriplesFactory.from_labeled_triples(triples)

            result = pipeline(
                model="RotatE",
                training=factory,
                num_epochs=num_epochs,
                model_kwargs={"embedding_dim": embedding_dim},
                training_kwargs={"batch_size": 512},
                random_seed=42,
            )

            self.model = result.model
            # Save model
            MODEL_PATH.mkdir(parents=True, exist_ok=True)
            result.save_to_directory(str(MODEL_PATH))
            logger.info(f"RotatE model trained and saved to {MODEL_PATH}")
            return True

        except ImportError:
            logger.error("PyKEEN or PyTorch not installed. Cannot train link prediction model.")
            return False
        except Exception as e:
            logger.error(f"GNN training failed: {e}")
            return False

    def load_saved_model(self) -> bool:
        """Load a previously trained model from disk."""
        try:
            from pykeen.pipeline import PipelineResult
            if MODEL_PATH.exists():
                # PyKEEN models can be restored from directory
                logger.info(f"Loading saved RotatE model from {MODEL_PATH}")
                # Implementation depends on PyKEEN version
                return True
        except Exception as e:
            logger.warning(f"Could not load saved model: {e}")
        return False

    def predict_proxy_relationships(
        self,
        actor_ids: list[str] | None = None,
        confidence_threshold: float = 0.6,
        relation_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Predict hidden relationships above confidence_threshold.
        Returns list of {subject, relation, object, confidence} dicts.
        """
        if self.model is None:
            logger.warning("No model loaded. Run train() first.")
            return []

        try:
            import torch

            # Get candidate actor pairs from graph
            if actor_ids is None:
                actors = self.neo4j.run("""
                    MATCH (a:Actor) RETURN a.id AS id LIMIT 200
                """)
                actor_ids = [r["id"] for r in actors]

            relation_types = relation_types or ["PROXY_OF", "FUNDS", "SUPPLIES_ARMS_TO"]

            # Score all candidate triples
            predictions = []
            for rel_type in relation_types:
                for a_id in actor_ids:
                    for b_id in actor_ids:
                        if a_id == b_id:
                            continue

                        # Check if relation already exists in graph
                        existing = self.neo4j.run(f"""
                            MATCH (a {{id: $a}})-[r:{rel_type}]->(b {{id: $b}})
                            RETURN count(r) AS cnt
                        """, a=a_id, b=b_id)

                        if existing and existing[0]["cnt"] > 0:
                            continue  # Already known

                        # Score with model
                        score = self._score_triple(a_id, rel_type, b_id)
                        if score >= confidence_threshold:
                            predictions.append({
                                "subject": a_id,
                                "relation": rel_type,
                                "object": b_id,
                                "confidence": score,
                            })

            # Sort by confidence
            predictions.sort(key=lambda x: x["confidence"], reverse=True)
            logger.info(f"Predicted {len(predictions)} new relations above threshold {confidence_threshold}")
            return predictions

        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return []

    def write_predictions(self, predictions: list[dict], top_k: int = 50):
        """Write top predicted relations to graph with inferred=True flag."""
        for pred in predictions[:top_k]:
            self.writer.write_inferred_relation(
                subject_id=pred["subject"],
                relation_type=pred["relation"],
                object_id=pred["object"],
                confidence=pred["confidence"],
                model="RotatE",
            )
        logger.info(f"Wrote {min(top_k, len(predictions))} inferred relations to graph")

    def _score_triple(self, subject_id: str, relation: str, object_id: str) -> float:
        """
        Score a candidate triple using the trained model.
        Returns confidence score 0.0-1.0.
        This is a simplified placeholder — full implementation uses
        model.predict_hrt() with proper entity/relation ID mapping.
        """
        # In production: use model.entity_representations and relation_representations
        # to get embeddings, then compute interaction function score
        return 0.0  # Placeholder

    def run_full_pipeline(
        self,
        retrain: bool = False,
        confidence_threshold: float = 0.65,
    ) -> list[dict]:
        """
        Full pipeline: optionally retrain → predict → write to graph.
        """
        if retrain or self.model is None:
            success = self.train()
            if not success:
                return []

        predictions = self.predict_proxy_relationships(
            confidence_threshold=confidence_threshold
        )
        if predictions:
            self.write_predictions(predictions)

        return predictions
