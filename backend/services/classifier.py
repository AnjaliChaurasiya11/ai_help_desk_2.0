import os
from typing import Optional, List, Tuple
from sqlmodel import Session
from sqlalchemy import text
from models import ClassificationConfig
from services.llm_client import predict_fault_and_severity

import logging
logger = logging.getLogger("services.classifier")


class TicketClassifier:
    """
    Handles zero-shot categorization for Fault Types (R-11) and Severity Ranks (R-12)
    using a Hybrid Strategy:
      1. History-based k-NN lookup via pgvector (preserved — critical for learning loop).
      2. LLM-based classification fallback via the air-gapped vLLM server (Gemma 4).
         (Replaces the old mDeBERTa-v3 zero-shot pipeline.)
    """

    def __init__(self):
        # No local model to load anymore. The LLM client is used for fallback.
        pass

    # ------------------------------------------------------------------
    # Internal: combined history lookup — ONE DB round-trip for both labels
    # ------------------------------------------------------------------
    def _get_history_match_combined(
        self,
        session: Session,
        embedding: List[float],
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Searches learning_examples for a highly-confident past ticket (cosine
        distance < 0.08, i.e. similarity > 92%) and returns BOTH
        (confirmed_fault_type, confirmed_severity) in a single DB query.

        Returns (None, None) if no close enough match is found.
        Replaces the two separate _get_history_match() calls that previously
        each executed an independent pgvector query for the same row.
        """
        embedding_str = "[" + ",".join(map(str, embedding)) + "]"
        query = text("""
            SELECT confirmed_fault_type, confirmed_severity,
                   (text_embedding <=> :embedding) AS distance
            FROM learning_examples
            ORDER BY distance ASC LIMIT 1
        """)

        result = session.execute(query, {"embedding": embedding_str}).first()
        if result and result.distance is not None and float(result.distance) < 0.08:
            return result.confirmed_fault_type or None, result.confirmed_severity or None

        return None, None

    # ------------------------------------------------------------------
    # Internal: kept for backward compatibility with legacy callers
    # ------------------------------------------------------------------
    def _get_history_match(self, session: Session, embedding: List[float], category: str) -> Optional[str]:
        """
        Single-category history lookup.  Kept for any callers outside this
        class that still use the old per-category API.  Internally delegates
        to the combined query.
        """
        fault_match, severity_match = self._get_history_match_combined(session, embedding)
        if category == "fault_type":
            return fault_match
        elif category == "severity":
            return severity_match
        return None

    # ------------------------------------------------------------------
    # NEW primary API — single LLM call, both labels
    # ------------------------------------------------------------------
    def classify_complaint(
        self,
        session: Session,
        text_content: Optional[str],
        embedding: List[float],
    ) -> Tuple[str, str]:
        """
        **Preferred entry point for the complaint pipeline.**

        Performs ONE combined classification and returns (fault_type, severity).

        Strategy:
          1. Execute a single pgvector query against learning_examples.
             If both labels are found with high confidence, return immediately —
             no LLM call at all.
          2. If history doesn't cover both labels, call predict_fault_and_severity()
             ONCE and use its result to fill in whichever labels are still missing.

        This eliminates the duplicate LLM call that was previously incurred when
        classify_fault_type() and classify_severity() were called sequentially,
        each triggering a separate Ollama round-trip.
        """
        if text_content is None or not text_content.strip():
            return "other", "normal"

        cleaned = text_content.strip()

        # Step 1: single DB lookup — may resolve both labels without any LLM call
        fault_from_history, severity_from_history = self._get_history_match_combined(session, embedding)

        if fault_from_history and severity_from_history:
            logger.info(
                "[AI] classify_complaint: both labels from history "
                "(fault=%s, severity=%s) — LLM skipped",
                fault_from_history, severity_from_history,
            )
            return fault_from_history, severity_from_history

        # Step 2: ONE LLM call for whichever labels are still unresolved
        logger.info(
            "[AI] classify_complaint: calling LLM once for combined classification "
            "(history_fault=%s, history_severity=%s)",
            fault_from_history, severity_from_history,
        )
        llm_result = predict_fault_and_severity(cleaned)

        fault_type = fault_from_history or llm_result.get("fault_type", "other")
        severity   = severity_from_history or llm_result.get("severity", "normal")

        return fault_type, severity

    # ------------------------------------------------------------------
    # Backward-compatible single-label APIs (unchanged public interface)
    # ------------------------------------------------------------------
    def classify_fault_type(self, session: Session, text_content: Optional[str], embedding: List[float]) -> str:
        """
        Hybrid classification for fault_type.
        Preserved for backward compatibility — callers that only need fault_type
        may continue using this method.  Internally uses the combined history
        query but still calls the LLM if no history match is found.
        """
        if text_content is None or not text_content.strip():
            return "other"

        # 1. Try history match first (preserves the learning loop)
        history_match, _ = self._get_history_match_combined(session, embedding)
        if history_match:
            logger.info("[AI] History match found for fault_type: %s", history_match)
            return history_match

        # 2. Fallback to LLM classification
        logger.info("[AI] No history match. Calling LLM for fault_type classification.")
        result = predict_fault_and_severity(text_content.strip())
        return result.get("fault_type", "other")

    def classify_severity(self, session: Session, text_content: Optional[str], embedding: List[float]) -> str:
        """
        LLM-based classification for severity.
        History matching is skipped for severity because vector embeddings cluster
        topically (by subject matter), not by urgency, making them a poor signal.
        Preserved for backward compatibility.
        """
        if text_content is None or not text_content.strip():
            return "normal"

        # Always use LLM for severity (no history check — consistent with old strategy)
        logger.info("[AI] Calling LLM for severity classification.")
        result = predict_fault_and_severity(text_content.strip())
        return result.get("severity", "normal")
