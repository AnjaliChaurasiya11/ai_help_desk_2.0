import os
from typing import Optional, List, Tuple
from sqlmodel import Session
from sqlalchemy import text
from models import ClassificationConfig
from services.llm_client import predict_fault_and_severity, classify_and_reason

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

    # ------------------------------------------------------------------
    # NEW context-aware entry point — used by the voice pipeline when
    # ENABLE_AI_REASONING=True.  Returns history_hit so the caller can
    # skip symptom/purpose enrichment queries when the shortcut fires.
    # ------------------------------------------------------------------
    def classify_and_reason_complaint(
        self,
        session: Session,
        text_content: Optional[str],
        embedding: List[float],
        candidate_apps: List[dict],
        symptoms: dict,
        purposes: dict,
    ) -> tuple:
        """
        Context-aware classification + reasoning in a single LLM call.

        Returns:
          (fault_type: str, severity: str, reasoning: dict, history_hit: bool)

        reasoning dict keys:
          fault_type, severity, confidence, summary,
          suggested_resolution, needs_followup, followup_question

        history_hit=True means no LLM was called; caller should treat
        confidence as 1.0 and skip followup logic.
        """
        if not text_content or not text_content.strip():
            default_reasoning = {
                "fault_type": "other", "severity": "normal",
                "confidence": 1.0, "summary": "",
                "suggested_resolution": "", "needs_followup": False,
                "followup_question": None,
            }
            return "other", "normal", default_reasoning, False

        cleaned = text_content.strip()

        # Phase A: history shortcut — DB only, no LLM, no extra queries
        fault_from_history, severity_from_history = self._get_history_match_combined(session, embedding)

        if fault_from_history and severity_from_history:
            logger.info(
                "[AI] classify_and_reason_complaint: history hit "
                "(fault=%s, severity=%s) — LLM + enrichment skipped",
                fault_from_history, severity_from_history,
            )
            reasoning = {
                "fault_type": fault_from_history,
                "severity": severity_from_history,
                "confidence": 1.0,
                "summary": "",
                "suggested_resolution": "",
                "needs_followup": False,
                "followup_question": None,
            }
            return fault_from_history, severity_from_history, reasoning, True

        # Phase B: single context-aware LLM call
        logger.info(
            "[AI] classify_and_reason_complaint: history miss — calling LLM with context "
            "(candidates=%d, apps_with_symptoms=%d)",
            len(candidate_apps), len(symptoms),
        )
        result = classify_and_reason(cleaned, candidate_apps, symptoms, purposes)

        fault_type = fault_from_history or result.get("fault_type", "other")
        severity   = severity_from_history or result.get("severity", "normal")

        # Ensure top-level labels are consistent with the result dict
        result["fault_type"] = fault_type
        result["severity"]   = severity

        return fault_type, severity, result, False

