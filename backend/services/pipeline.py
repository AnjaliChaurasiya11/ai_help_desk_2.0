"""
services/pipeline.py — Unified Complaint Processing Pipeline
=============================================================
Single entry-point for ALL complaint processing in the system.

Both the manual REST endpoint (routers/tickets.py) and the voice endpoint
(voice/complaint_processor.py) call process_complaint() — they are thin
adapters that translate inputs/outputs for their transport layer.

Pipeline execution order
------------------------
  [1]  Guardrail          — LLM text correction + language / validity check
  [2]  Category Analysis  — LLM decides complete / incomplete / invalid
  [3a] Invalid path       — Reject immediately
  [3b] Incomplete path    — Save pending_clarification Intake; return follow-up question. Check attempts.
  [3c] Complete path:
       [4] Embedding      — Vector representation of corrected complaint
       [5] Dup/repeat check — pgvector similarity against recent open tickets
       [6] History shortcut — Previous classified complaint lookup (no LLM, no retrieval)
       [7] Retrieval       — Semantic search for candidate applications (skipped on hit)
       [8] LLM reasoning   — classify_and_reason() (skipped on history hit)
       [9] Dep expansion   — Expand dependency graph from primary candidate
      [10] Save Intake     — Persist with status="complete"
  [11] Return PipelineResult

Key guarantee: retrieval (step 7) and LLM (step 8) are NEVER executed for
insufficient complaints. This prevents wasted computation and avoids confusing
application candidates being shown alongside a "needs clarification" response.
"""

import logging
import datetime as dt_lib
from datetime import timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

from sqlalchemy import text
from sqlmodel import Session

from models import Application, Intake
from services.embedder import TextEmbedder
from services.classifier import TicketClassifier
from services.search import ApplicationSearchEngine
from services.dependencies import ApplicationDependencyEngine
from services.conversation_state import ConversationState, PipelineResult, ConversationManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy-loaded AI service singletons (shared across all callers)
# ---------------------------------------------------------------------------

_embedder: Optional[TextEmbedder] = None
_classifier: Optional[TicketClassifier] = None
_search_engine: Optional[ApplicationSearchEngine] = None
_dependency_engine: Optional[ApplicationDependencyEngine] = None


def _get_services() -> Tuple[TextEmbedder, TicketClassifier, ApplicationSearchEngine, ApplicationDependencyEngine]:
    global _embedder, _classifier, _search_engine, _dependency_engine
    if _embedder is None:
        _embedder = TextEmbedder()
        _classifier = TicketClassifier()
        _search_engine = ApplicationSearchEngine()
        _dependency_engine = ApplicationDependencyEngine()
    return _embedder, _classifier, _search_engine, _dependency_engine


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _fetch_app_context(
    db_session: Session,
    app_ids: List[int],
) -> Tuple[Dict[int, List[str]], Dict[int, List[str]]]:
    """
    Fetch symptom and purpose text for the given application IDs.
    Used to enrich the LLM prompt when ENABLE_AI_REASONING=True.
    Returns (symptoms_dict, purposes_dict) keyed by application_id.
    """
    symptoms: Dict[int, List[str]] = {}
    purposes: Dict[int, List[str]] = {}
    for app_id in app_ids:
        sym_rows = db_session.execute(
            text("SELECT symptom_text FROM application_symptoms WHERE application_id = :aid LIMIT 3"),
            {"aid": app_id},
        ).fetchall()
        symptoms[app_id] = [r.symptom_text for r in sym_rows]

        pur_rows = db_session.execute(
            text("SELECT purpose_text FROM application_purposes WHERE application_id = :aid LIMIT 2"),
            {"aid": app_id},
        ).fetchall()
        purposes[app_id] = [r.purpose_text for r in pur_rows]

    return symptoms, purposes


def _enrich_candidates(
    session: Session,
    raw_candidates: List[Dict[str, Any]],
    complaint_text: str = "",
) -> List[Dict[str, Any]]:
    """Convert raw search results into dicts with full application metadata.

    After building the list, applies an explicit-name-match boost: if the
    complaint text contains an application's name verbatim (case-insensitive),
    its score is boosted by +0.35 (capped at 1.0) so that explicitly-mentioned
    applications always rank ahead of pure vector-similarity matches.
    """
    enriched = []
    for cand in raw_candidates:
        app_obj = session.get(Application, cand["application_id"])
        if app_obj:
            enriched.append({
                "application_id":   app_obj.id,
                "application_name": app_obj.name,
                "confidence_score": round(cand["score"], 4),
                "is_primary":       False,   # will be set after re-sorting
                "expansion_reason": None,
            })

    # ── Explicit name-mention boost ───────────────────────────────────────────
    if complaint_text:
        text_lower = complaint_text.lower()
        for cand in enriched:
            if cand["application_name"].lower() in text_lower:
                boosted = min(1.0, cand["confidence_score"] + 0.35)
                logger.info(
                    "[pipeline] Name-match boost: '%s' %.4f → %.4f",
                    cand["application_name"], cand["confidence_score"], boosted,
                )
                cand["confidence_score"] = boosted

        # Re-sort so the boosted candidate surfaces first
        enriched.sort(key=lambda c: c["confidence_score"], reverse=True)

    # Mark the top result as primary
    for i, cand in enumerate(enriched):
        cand["is_primary"] = (i == 0)

    return enriched


def _check_duplicates(
    session: Session,
    embedding: List[float],
    complainant_service_no: str,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Semantic duplicate and repeat-caller check against recent open tickets.
    Returns (potential_duplicates, is_repeat_caller).
    """
    embedding_str = "[" + ",".join(map(str, embedding)) + "]"
    time_limit = dt_lib.datetime.now(timezone.utc) - timedelta(hours=4)

    duplicate_query = text("""
        SELECT t.ticket_number, t.complainant_service_no, l.raw_text, t.status,
               (l.text_embedding <=> :embedding) AS distance
        FROM tickets t
        JOIN learning_examples l ON t.ticket_number = l.ticket_number
        WHERE t.status != 'resolved'
          AND t.created_at >= :time_limit
          AND (l.text_embedding <=> :embedding) < 0.20
        ORDER BY distance ASC
        LIMIT 5
    """)
    dupes = session.execute(
        duplicate_query, {"embedding": embedding_str, "time_limit": time_limit}
    ).fetchall()

    potential_duplicates: List[Dict[str, Any]] = []
    is_repeat = False

    for row in dupes:
        is_same = (row.complainant_service_no == complainant_service_no)
        dist = float(row.distance)
        if is_same and dist < 0.20:
            is_repeat = True
        if (is_same and dist < 0.20) or (not is_same and dist < 0.10):
            snippet = row.raw_text[:80] + "..." if len(row.raw_text) > 80 else row.raw_text
            potential_duplicates.append({
                "ticket_number":           row.ticket_number,
                "complainant_service_no":  row.complainant_service_no,
                "text_snippet":            snippet,
                "status":                  row.status,
                "is_same_user":            is_same,
            })

    return potential_duplicates, is_repeat


def _expand_dependencies(
    session: Session,
    dependency_engine: ApplicationDependencyEngine,
    enriched_candidates: List[Dict[str, Any]],
    fault_type: str,
) -> List[Dict[str, Any]]:
    """Append dependency-expanded candidates to the list."""
    primary = enriched_candidates[0] if enriched_candidates else None
    if not primary:
        return enriched_candidates

    dep_ids = dependency_engine.expand_dependencies(
        db_session=session,
        primary_app_id=primary["application_id"],
        fault_type=fault_type,
    )
    existing_ids = {c["application_id"] for c in enriched_candidates}
    for d_id in dep_ids:
        if d_id not in existing_ids:
            d_app = session.get(Application, d_id)
            if d_app:
                enriched_candidates.append({
                    "application_id":   d_id,
                    "application_name": d_app.name,
                    "confidence_score": 0.0,
                    "is_primary":       False,
                    "expansion_reason": f"Cascade from {fault_type}",
                })
    return enriched_candidates


def _save_intake(
    session: Session,
    complaint_text: str,
    status: str,
    operator_id: str,
    complainant_service_no: str,
    complainant_name: str,
    complainant_unit: str,
    complainant_rank: str,
    existing_intake_id: Optional[int] = None,
    last_followup_question: Optional[str] = None,
) -> Intake:
    """
    Persist an Intake record.

    If existing_intake_id is provided (clarification flow), update that record
    in-place (raw_text ← merged text, status ← new status).
    Otherwise create a new record.
    """
    if existing_intake_id is not None:
        intake = session.get(Intake, existing_intake_id)
        if intake is None:
            raise ValueError(f"Intake {existing_intake_id} not found for clarification update.")
        intake.raw_text = complaint_text
        intake.status   = status
        if status == "pending_clarification":
            intake.clarification_attempts += 1
        if last_followup_question is not None:
            intake.last_followup_question = last_followup_question
        session.add(intake)
    else:
        intake = Intake(
            raw_text               = complaint_text,
            operator_id            = operator_id,
            complainant_service_no = complainant_service_no or None,
            complainant_name       = complainant_name  or None,
            complainant_unit       = complainant_unit  or None,
            complainant_rank       = complainant_rank  or None,
            status                 = status,
            clarification_attempts = 1 if status == "pending_clarification" else 0,
            last_followup_question = last_followup_question,
        )
        session.add(intake)

    session.commit()
    session.refresh(intake)
    return intake


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_complaint(
    session: Session,
    complaint_text: str,
    complainant_service_no: str,
    operator_id: str = "system",
    complainant_name: str = "",
    complainant_unit: str = "",
    complainant_rank: str = "",
    existing_intake_id: Optional[int] = None,
) -> PipelineResult:
    """
    Execute the full complaint-processing pipeline.

    This is the single source of truth for AI-assisted complaint classification.
    Both the manual intake endpoint and the voice complaint endpoint call this
    function; they are thin adapters responsible only for input normalisation
    and response formatting.

    Args:
        session:               Active SQLModel session.
        complaint_text:        Raw complaint string (pre-guardrail).
        complainant_service_no: Caller's service number for repeat detection.
        operator_id:           ID of the operator submitting the complaint.
        complainant_name/unit/rank: Caller metadata stored on the Intake.
        existing_intake_id:    When provided (clarification flow), update this
                               Intake record instead of creating a new one.

    Returns:
        PipelineResult with status one of:
          "rejected"              — guardrail blocked the text
          "pending_clarification" — insufficient complaint; follow-up question set
          "complete"              — classification finished; ticket proposal ready
    """
    from config import settings
    from services.llm_client import verify_and_correct_text, analyze_complaint_category

    embedder, classifier, search_engine, dependency_engine = _get_services()

    # Get existing intake attempts and previous follow-up question (if any)
    attempts = 0
    previous_question: Optional[str] = None
    if existing_intake_id:
        existing_intake = session.get(Intake, existing_intake_id)
        if existing_intake:
            attempts = existing_intake.clarification_attempts
            previous_question = existing_intake.last_followup_question

    # ── [1] GUARDRAIL ────────────────────────────────────────────────────────
    guardrail_result = verify_and_correct_text(complaint_text)
    if guardrail_result["status"] == "rejected":
        reason_text = guardrail_result.get("reason", "Complaint could not be processed.")
        state = ConversationState(
            complaint_text  = complaint_text,
            needs_followup  = False,
            is_sufficient   = False,
            followup_reason = "rejected",
            followup_question = reason_text,
        )
        logger.info("[pipeline] Guardrail rejected: %s", reason_text)
        return PipelineResult(
            status         = "rejected",
            state          = state,
            corrected_text = complaint_text,
        )

    corrected_text = guardrail_result.get("corrected_text", complaint_text)

    # ── [2] CATEGORY ANALYSIS ─────────────────────────
    category_result = analyze_complaint_category(corrected_text, previous_question=previous_question)
    cat = category_result.get("category", "complete")

    # ── [3a] INVALID PATH ───────────────────────
    if cat == "invalid":
        reason_text = category_result.get("followup_question") or "Please describe your IT issue."
        state = ConversationState(
            complaint_text  = corrected_text,
            needs_followup  = False,
            is_sufficient   = False,
            followup_reason = "invalid_category",
            followup_question = reason_text,
        )
        logger.info("[pipeline] Invalid category rejected: %s", reason_text)
        return PipelineResult(
            status         = "rejected",
            state          = state,
            corrected_text = corrected_text,
        )

    # ── [3b] INCOMPLETE PATH ───────────────────────
    if cat == "incomplete":
        if attempts >= settings.MAX_CLARIFICATION_ATTEMPTS:
            state = ConversationState(
                complaint_text  = corrected_text,
                needs_followup  = False,
                is_sufficient   = False,
                followup_reason = "max_attempts_reached",
                followup_question = None,
            )
            intake = _save_intake(
                session                = session,
                complaint_text         = corrected_text,
                status                 = "unable_to_identify",
                operator_id            = operator_id,
                complainant_service_no = complainant_service_no,
                complainant_name       = complainant_name,
                complainant_unit       = complainant_unit,
                complainant_rank       = complainant_rank,
                existing_intake_id     = existing_intake_id,
            )
            logger.info("[pipeline] Clarification attempts exhausted. Status: unable_to_identify.")
            return PipelineResult(
                status              = "unable_to_identify",
                state               = state,
                corrected_text      = corrected_text,
                intake_id           = intake.id,
                clarification_attempts = intake.clarification_attempts,
            )

        followup_q = category_result.get("followup_question", "Can you provide more details about the system or application?")
        state = ConversationState(
            complaint_text  = corrected_text,
            is_sufficient   = False,
            needs_followup  = True,
            followup_reason = category_result.get("followup_reason", "incomplete_complaint"),
            followup_question = followup_q,
        )
        intake = _save_intake(
            session                = session,
            complaint_text         = corrected_text,
            status                 = "pending_clarification",
            operator_id            = operator_id,
            complainant_service_no = complainant_service_no,
            complainant_name       = complainant_name,
            complainant_unit       = complainant_unit,
            complainant_rank       = complainant_rank,
            existing_intake_id     = existing_intake_id,
            last_followup_question = followup_q,
        )
        logger.info("[pipeline] Incomplete complaint — follow-up: %r", state.followup_question)
        return PipelineResult(
            status              = "pending_clarification",
            state               = state,
            corrected_text      = corrected_text,
            intake_id           = intake.id,
            clarification_attempts = intake.clarification_attempts,
            fault_type          = "other",
            severity            = "normal",
        )

    # ── [3c] COMPLETE PATH (cat == "complete") ──────────────────────────────

    # ── [4] EMBEDDING ────────────────────────────────────────────────────────
    embedding = embedder.get_embedding(corrected_text)

    # ── [5] DUPLICATE / REPEAT CHECK ─────────────────────────────────────────
    potential_duplicates, is_repeat = _check_duplicates(
        session, embedding, complainant_service_no
    )

    # ── [6] HISTORY SHORTCUT ─────────────────────────────────────────────────
    history_fault, history_severity = classifier._get_history_match_combined(session, embedding)
    history_hit = bool(history_fault and history_severity)

    reasoning: Dict[str, Any] = {}
    enriched_candidates: List[Dict[str, Any]] = []

    # ── [7] RETRIEVAL ─────────────────────────────────────────────────
    # Always run retrieval to populate UI candidates, even if LLM is skipped
    raw_candidates    = search_engine.search_candidates(session, embedding)
    enriched_candidates = _enrich_candidates(session, raw_candidates, corrected_text)

    if history_hit:
        fault_type = history_fault
        severity   = history_severity
        reasoning  = {
            "confidence": 1.0,
            "suggested_resolution": "",
        }
        logger.info(
            "[pipeline] History hit (fault=%s, severity=%s) — LLM skipped.",
            fault_type, severity,
        )
    else:
        # ── [8] LLM CLASSIFICATION + REASONING ───────────────────────────
        if settings.ENABLE_AI_REASONING:
            top_ids = [c["application_id"] for c in enriched_candidates[:3]]
            symptoms, purposes = _fetch_app_context(session, top_ids)

            fault_type, severity, reasoning, _ = classifier.classify_and_reason_complaint(
                session        = session,
                text_content   = corrected_text,
                embedding      = embedding,
                candidate_apps = enriched_candidates[:3],
                symptoms       = symptoms,
                purposes       = purposes,
            )
        else:
            fault_type, severity = classifier.classify_complaint(session, corrected_text, embedding)
            reasoning = {
                "confidence": 0.0,
                "suggested_resolution": None,
            }

    # ── [9] CONFIDENCE GATE ──────────────────────────────────────────────────
    # Removed: category analysis entirely determines if we need follow-up
    confidence = float(reasoning.get("confidence", 0.0))

    # ── [10] DEPENDENCY EXPANSION ────────────────────────────────────────────
    if enriched_candidates:
        enriched_candidates = _expand_dependencies(
            session, dependency_engine, enriched_candidates, fault_type
        )

    # ── Update ConversationState with classification results ─────────────────
    state = ConversationState(
        complaint_text  = corrected_text,
        is_sufficient   = True,
        needs_followup  = False,
        fault_type      = fault_type,
        severity        = severity,
        confidence      = confidence,
        suggested_resolution = reasoning.get("suggested_resolution"),
    )

    # ── [11] SAVE INTAKE ─────────────────────────────────────────────────────
    intake = _save_intake(
        session                = session,
        complaint_text         = corrected_text,
        status                 = "complete",
        operator_id            = operator_id,
        complainant_service_no = complainant_service_no,
        complainant_name       = complainant_name,
        complainant_unit       = complainant_unit,
        complainant_rank       = complainant_rank,
        existing_intake_id     = existing_intake_id,
    )

    return PipelineResult(
        status              = "complete",
        state               = state,
        corrected_text      = corrected_text,
        intake_id           = intake.id,
        fault_type          = fault_type,
        severity            = severity,
        candidates          = enriched_candidates,
        potential_duplicates = potential_duplicates,
        is_repeat_caller    = is_repeat,
        history_hit         = history_hit,
        clarification_attempts = 0,
    )


# ---------------------------------------------------------------------------
# Backward-compatibility shim
# ---------------------------------------------------------------------------
# Kept so any test or script that still imports run_ai_pipeline() continues
# to work.  Will be removed in a future cleanup pass.

def run_ai_pipeline(
    session: Session,
    complaint_text: str,
    complainant_service_no: str,
):
    """DEPRECATED — use process_complaint() instead."""
    import warnings
    warnings.warn(
        "run_ai_pipeline() is deprecated. Use process_complaint() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    result = process_complaint(
        session                = session,
        complaint_text         = complaint_text,
        complainant_service_no = complainant_service_no,
    )
    reasoning = {
        "confidence":          result.state.confidence,
        "suggested_resolution": result.state.suggested_resolution,
        "needs_followup":      result.state.needs_followup,
        "followup_question":   result.state.followup_question,
    }
    return (
        result.fault_type or "other",
        result.severity   or "normal",
        result.candidates,
        result.potential_duplicates,
        result.is_repeat_caller,
        reasoning,
    )
