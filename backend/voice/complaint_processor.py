"""
voice/complaint_processor.py — Shared Complaint Processing Pipeline
===================================================================
Executes the Phase 1 AI pipeline for a transcribed complaint. Shared
between the REST API (routers/voice.py POST /complaint) and the
LiveKit WebRTC audio adapter (livekit_bridge/adapter.py), so both
transports run the exact same classify -> Intake -> candidates logic.

Responsibilities:
- LLM guardrail (verify_and_correct_text)
- Embedding extraction
- Application candidate search & dependency expansion
- Fault type & severity classification
  · History shortcut: pgvector DB query (no LLM, no extra queries)
  · LLM fallback: classify_and_reason() — single context-aware call
    with symptoms/purposes enrichment (ENABLE_AI_REASONING=True)
    or predict_fault_and_severity() two-field call (False)
- Deterministic follow-up gate (confidence < FOLLOWUP_CONFIDENCE_THRESHOLD)
- Intake record creation
- Voice session state transition
- Prompt generation
"""

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from sqlalchemy import text
from sqlmodel import Session

from config import settings
from models import Application, Intake
from voice.session import VoiceSessionManager, SessionState
from voice.prompts import render_dynamic_prompt
from services.llm_client import verify_and_correct_text
from services.embedder import TextEmbedder
from services.classifier import TicketClassifier
from services.search import ApplicationSearchEngine
from services.dependencies import ApplicationDependencyEngine
from voice_schemas import VoiceCandidateApp

logger = logging.getLogger("voice.complaint_processor")

# Lazy-loaded singletons — same instances used across every call, matching
# the pattern already used for _stt_engine/_tts_engine in routers/voice.py.
_embedder: Optional[TextEmbedder] = None
_classifier: Optional[TicketClassifier] = None
_search_engine: Optional[ApplicationSearchEngine] = None
_dependency_engine: Optional[ApplicationDependencyEngine] = None


def _get_services():
    global _embedder, _classifier, _search_engine, _dependency_engine
    if _embedder is None:
        _embedder = TextEmbedder()
        _classifier = TicketClassifier()
        _search_engine = ApplicationSearchEngine()
        _dependency_engine = ApplicationDependencyEngine()
    return _embedder, _classifier, _search_engine, _dependency_engine


def _fetch_app_context(
    db_session: Session,
    app_ids: List[int],
) -> tuple[Dict[int, List[str]], Dict[int, List[str]]]:
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


@dataclass
class ComplaintProcessingResult:
    """The structured result returned to the caller (REST or LiveKit adapter)."""
    status: str                 # "rejected" or "accepted"
    prompt_text: str            # TTS/display response text
    corrected_transcript: str
    intake_id: Optional[int] = None
    fault_type: Optional[str] = None
    severity: Optional[str] = None
    candidates: List[VoiceCandidateApp] = field(default_factory=list)
    timings: dict = field(default_factory=dict)

    # Reasoning layer fields (populated when ENABLE_AI_REASONING=True)
    summary: Optional[str] = None
    confidence: float = 0.0
    suggested_resolution: Optional[str] = None
    needs_followup: bool = False
    followup_question: Optional[str] = None


def process_complaint_transcript(
    db_session: Session,
    session_manager: VoiceSessionManager,
    session_id: str,
    raw_transcript: str,
    operator_id: str,
    complainant_service_no: Optional[str],
    complainant_name: Optional[str],
    complainant_unit: Optional[str],
    complainant_rank: Optional[str],
    stt_confidence: float = 1.0,
    stt_language: Optional[str] = None,
) -> ComplaintProcessingResult:
    """
    Run the full complaint pipeline for one transcribed utterance.

    Pipeline order (with ENABLE_AI_REASONING=True):
      1. LLM guardrail (verify_and_correct_text)
      2. Embedding
      3. History shortcut (pgvector) — if hit, skip LLM + symptom queries
      4. Application search (always runs — needed for candidates + dep expansion)
         a. If history HIT  → skip symptom/purpose extra queries
         b. If history MISS → fetch symptoms+purposes, call classify_and_reason()
      5. Deterministic follow-up gate (Python, confidence < threshold)
      6. Dependency expansion
      7. Intake creation
      8. Session state transition
      9. Prompt generation (or follow-up question override)

    With ENABLE_AI_REASONING=False:
      Step 4b calls classify_complaint() (old 2-field path) instead.
    """
    embedder, classifier, search_engine, dependency_engine = _get_services()

    # ── LLM GUARDRAIL — verify language + fix STT errors ──
    t_guardrail_start = time.time()
    guardrail_result = verify_and_correct_text(raw_transcript)
    t_guardrail = (time.time() - t_guardrail_start) * 1000

    if guardrail_result["status"] == "rejected":
        reason = guardrail_result.get("reason", "Complaint could not be understood.")
        return ComplaintProcessingResult(
            status="rejected",
            prompt_text=f"{reason} Please describe your IT issue again clearly.",
            corrected_transcript=raw_transcript,
            timings={"Guardrail (LLM)": t_guardrail},
        )

    # Use the LLM-corrected text for the rest of the pipeline
    complaint_text = guardrail_result.get("corrected_text", raw_transcript)

    # ── EMBEDDING ──────────────────────────────────────────────────────────────
    t_emb_start = time.time()
    embedding = embedder.get_embedding(complaint_text)
    t_emb = (time.time() - t_emb_start) * 1000

    # ── HISTORY SHORTCUT (DB only — no LLM, no extra queries) ─────────────────
    # We expose the check here so the pipeline can decide whether to fetch
    # symptom/purpose enrichment before branching to the LLM.
    t_history_start = time.time()
    fault_from_history, severity_from_history = classifier._get_history_match_combined(db_session, embedding)
    history_hit = bool(fault_from_history and severity_from_history)
    t_history_db = (time.time() - t_history_start) * 1000

    # ── APPLICATION SEARCH (always — needed for candidates + dep expansion) ────
    t_search_start = time.time()
    raw_candidates = search_engine.search_candidates(db_session, embedding)
    t_search = (time.time() - t_search_start) * 1000

    enriched_candidates: List[VoiceCandidateApp] = []
    for cand in raw_candidates:
        app_obj = db_session.get(Application, cand["application_id"])
        if app_obj:
            enriched_candidates.append(VoiceCandidateApp(
                application_id=app_obj.id,
                application_name=app_obj.name,
                confidence_score=round(cand["score"], 4),
                is_primary=(len(enriched_candidates) == 0),
            ))

    # ── CLASSIFICATION + REASONING ────────────────────────────────────────────
    t_classify_start = time.time()
    reasoning: dict = {}

    if settings.ENABLE_AI_REASONING:
        if history_hit:
            # History shortcut fired — skip symptoms/purposes queries AND LLM
            fault_type = fault_from_history
            severity   = severity_from_history
            reasoning  = {
                "fault_type": fault_type, "severity": severity,
                "confidence": 1.0, "summary": "",
                "suggested_resolution": "", "needs_followup": False,
                "followup_question": None,
            }
            logger.info(
                "[CP] History hit (fault=%s, severity=%s) — LLM + enrichment skipped.",
                fault_type, severity,
            )
        else:
            # Fetch symptom/purpose context for top candidates (enrichment queries)
            top_ids = [c.application_id for c in enriched_candidates[:3]]
            symptoms, purposes = _fetch_app_context(db_session, top_ids)

            fault_type, severity, reasoning, _ = classifier.classify_and_reason_complaint(
                session=db_session,
                text_content=complaint_text,
                embedding=embedding,
                candidate_apps=[c.model_dump() for c in enriched_candidates[:3]],
                symptoms=symptoms,
                purposes=purposes,
            )
    else:
        # ENABLE_AI_REASONING=False — use old 2-field path, no extra overhead
        fault_type, severity = classifier.classify_complaint(db_session, complaint_text, embedding)
        reasoning = {
            "confidence": 0.0, "summary": None,
            "suggested_resolution": None, "needs_followup": False,
            "followup_question": None,
        }

    t_classification = (time.time() - t_classify_start) * 1000

    # ── DETERMINISTIC FOLLOW-UP GATE ──────────────────────────────────────────
    # Python decides whether to ask a follow-up; the LLM's needs_followup flag
    # is advisory only.  If the LLM returns confidence < threshold we override.
    confidence = float(reasoning.get("confidence", 0.0))
    if not history_hit and settings.ENABLE_AI_REASONING:
        needs_followup = (
            confidence < settings.FOLLOWUP_CONFIDENCE_THRESHOLD
            or reasoning.get("needs_followup", False)
        )
    else:
        needs_followup = False  # never ask follow-up for history hits

    followup_question = reasoning.get("followup_question") if needs_followup else None

    # ── DEPENDENCY EXPANSION ───────────────────────────────────────────────────
    primary_candidate = enriched_candidates[0] if enriched_candidates else None
    t_dep_start = time.time()
    if primary_candidate:
        dep_ids = dependency_engine.expand_dependencies(
            db_session=db_session,
            primary_app_id=primary_candidate.application_id,
            fault_type=fault_type,
        )
        existing_ids = {c.application_id for c in enriched_candidates}
        for d_id in dep_ids:
            if d_id not in existing_ids:
                d_app = db_session.get(Application, d_id)
                if d_app:
                    enriched_candidates.append(VoiceCandidateApp(
                        application_id=d_id,
                        application_name=d_app.name,
                        confidence_score=0.0,
                        is_primary=False,
                    ))

    # ── CREATE INTAKE RECORD ───────────────────────────────────────────────────
    t_db_start = time.time()
    intake = Intake(
        raw_text=complaint_text,
        operator_id=operator_id,
        complainant_service_no=complainant_service_no,
        complainant_name=complainant_name,
        complainant_unit=complainant_unit,
        complainant_rank=complainant_rank,
    )
    db_session.add(intake)
    db_session.commit()
    db_session.refresh(intake)
    t_db = (time.time() - t_db_start) * 1000
    t_dep = (time.time() - t_dep_start) * 1000

    timings = {
        "Guardrail (LLM)":  t_guardrail,
        "Embedding":        t_emb,
        "History (DB)":     t_history_db,
        "Vector Search":    t_search,
        "Classification":   t_classification,
        "Dependencies":     t_dep,
        "Database":         t_db,
    }

    # ── SESSION STATE TRANSITION ───────────────────────────────────────────────
    session_manager.transition(
        session_id,
        SessionState.OPERATOR_REVIEW,
        complaint_text=complaint_text,
        stt_confidence=stt_confidence,
        stt_language=stt_language,
        intake_id=intake.id,
        fault_type_proposal=fault_type,
        severity_proposal=severity,
        candidates=[c.model_dump() for c in enriched_candidates],
    )

    # ── PROMPT GENERATION ──────────────────────────────────────────────────────
    app_name = primary_candidate.application_name if primary_candidate else "Unknown"

    if needs_followup and followup_question:
        # Override TTS prompt with the follow-up question
        prompt_text = followup_question
        logger.info(
            "[CP] Low confidence (%.2f < %.2f) — overriding prompt with follow-up question.",
            confidence, settings.FOLLOWUP_CONFIDENCE_THRESHOLD,
        )
    else:
        prompt_text = render_dynamic_prompt(
            "classification_summary",
            complaint_text=complaint_text[:100],
            application_name=app_name,
            fault_type=fault_type,
            severity=severity,
        )

    return ComplaintProcessingResult(
        status="accepted",
        prompt_text=prompt_text,
        corrected_transcript=complaint_text,
        intake_id=intake.id,
        fault_type=fault_type,
        severity=severity,
        candidates=enriched_candidates,
        timings=timings,
        summary=reasoning.get("summary"),
        confidence=confidence,
        suggested_resolution=reasoning.get("suggested_resolution"),
        needs_followup=needs_followup,
        followup_question=followup_question,
    )
