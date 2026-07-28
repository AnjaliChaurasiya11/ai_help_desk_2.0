"""
voice/complaint_processor.py — Voice Transport Adapter
=======================================================
Thin adapter between the voice transport layer (STT, TTS, session management)
and the shared complaint-processing pipeline (services/pipeline.py).

Responsibilities (voice-specific only):
  - Receive a raw STT transcript.
  - Delegate all AI processing to services.pipeline.process_complaint().
  - Translate the PipelineResult into a ComplaintProcessingResult for the
    voice REST router (routers/voice.py) and the LiveKit adapter.
  - Perform voice session state transitions.
  - Generate TTS prompt text.

What this file does NOT do:
  - Embedding / vector search
  - LLM calls
  - Heuristic scoring
  - Intake persistence  (all owned by the pipeline)

Phase 4 note:
  The LiveKit conversational calling path will call process_complaint_transcript()
  repeatedly — once per STT utterance — without modifying the shared pipeline.
  Only this adapter's session handling and TTS prompt generation need to change
  to support multi-turn calling.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

from sqlmodel import Session

from models import Intake
from voice.session import VoiceSessionManager, SessionState
from voice.prompts import render_dynamic_prompt
from services.pipeline import process_complaint
from voice_schemas import VoiceCandidateApp

logger = logging.getLogger("voice.complaint_processor")


# ===========================================================================
# Result returned to the voice REST router / LiveKit adapter
# ===========================================================================

@dataclass
class ComplaintProcessingResult:
    """The structured result returned to the caller (REST or LiveKit adapter)."""
    status: str                  # "rejected" | "accepted"
    prompt_text: str             # TTS/display response text
    corrected_transcript: str
    intake_id: Optional[int] = None
    fault_type: Optional[str] = None
    severity: Optional[str] = None
    candidates: List[VoiceCandidateApp] = field(default_factory=list)
    timings: dict = field(default_factory=dict)

    # Reasoning / conversation fields
    summary: Optional[str] = None
    confidence: float = 0.0
    suggested_resolution: Optional[str] = None
    needs_followup: bool = False
    followup_question: Optional[str] = None


# ===========================================================================
# Main entry point
# ===========================================================================

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

    Delegates all AI logic to services.pipeline.process_complaint() and wraps
    the result for the voice transport layer (TTS prompt, session transitions).

    Pipeline:
      STT transcript
          → process_complaint()   (guardrail, heuristic, retrieval, LLM)
          → session state transition
          → TTS prompt generation
          → ComplaintProcessingResult
    """
    t_start = time.time()

    # ── GET EXISTING INTAKE FOR CLARIFICATION ────────────────────────────────
    voice_session = session_manager.get_session(session_id)
    existing_intake_id = voice_session.intake_id if voice_session else None
    
    # Context accumulation: Merge new speech into previous complaint if we are in a clarification loop
    complaint_text = raw_transcript
    if existing_intake_id:
        from models import Intake
        from services.conversation_state import ConversationManager, ConversationState
        existing_intake = db_session.get(Intake, existing_intake_id)
        if existing_intake:
            complaint_text = ConversationManager.merge_clarification(
                original_text = existing_intake.raw_text,
                clarification = raw_transcript,
                state = ConversationState()
            )

    # ── SHARED PIPELINE ──────────────────────────────────────────────────────
    t_pipeline_start = time.time()
    result = process_complaint(
        session                = db_session,
        complaint_text         = complaint_text,
        complainant_service_no = complainant_service_no or "",
        operator_id            = operator_id,
        complainant_name       = complainant_name  or "",
        complainant_unit       = complainant_unit  or "",
        complainant_rank       = complainant_rank  or "",
        existing_intake_id     = existing_intake_id,
    )
    t_pipeline = (time.time() - t_pipeline_start) * 1000

    timings = {"Pipeline (total)": t_pipeline}

    # ── GUARDRAIL REJECTION ──────────────────────────────────────────────────
    if result.status == "rejected":
        reason = result.state.followup_question or "Complaint could not be understood."
        return ComplaintProcessingResult(
            status               = "rejected",
            prompt_text          = f"{reason} Please describe your IT issue again clearly.",
            corrected_transcript = raw_transcript,
            timings              = timings,
        )

    # ── CONVERT CANDIDATES TO VoiceCandidateApp ──────────────────────────────
    voice_candidates: List[VoiceCandidateApp] = [
        VoiceCandidateApp(
            application_id   = c["application_id"],
            application_name = c["application_name"],
            confidence_score = c["confidence_score"],
            is_primary       = c.get("is_primary", False),
        )
        for c in result.candidates
    ]

    # ── SESSION STATE TRANSITION ─────────────────────────────────────────────
    t_session_start = time.time()
    
    if result.status == "pending_clarification":
        next_state = SessionState.CAPTURING_COMPLAINT
    else:
        # For "complete" and "unable_to_identify", operator must review/submit
        next_state = SessionState.OPERATOR_REVIEW

    current_state = voice_session.state if voice_session else None

    if current_state == next_state:
        # Already in this state (e.g., CAPTURING_COMPLAINT). Update fields without transition.
        if voice_session:
            voice_session.complaint_text      = result.corrected_text
            voice_session.stt_confidence      = stt_confidence
            voice_session.stt_language        = stt_language
            voice_session.intake_id           = result.intake_id
            voice_session.fault_type_proposal = result.fault_type
            voice_session.severity_proposal   = result.severity
            voice_session.candidates          = [c.model_dump() for c in voice_candidates]
            voice_session.updated_at          = time.time()
    else:
        session_manager.transition(
            session_id,
            next_state,
            complaint_text      = result.corrected_text,
            stt_confidence      = stt_confidence,
            stt_language        = stt_language,
            intake_id           = result.intake_id,
            fault_type_proposal = result.fault_type,
            severity_proposal   = result.severity,
            candidates          = [c.model_dump() for c in voice_candidates],
        )
    timings["Session transition"] = (time.time() - t_session_start) * 1000

    # ── TTS PROMPT GENERATION ────────────────────────────────────────────────
    t_tts_start = time.time()
    state = result.state

    if state.needs_followup and state.followup_question:
        # Override TTS prompt with the follow-up question
        prompt_text = state.followup_question
        logger.info(
            "[voice.CP] Follow-up triggered (reason=%s, confidence=%.2f) — "
            "overriding TTS prompt.",
            state.followup_reason, state.confidence,
        )
    else:
        # Generate summary prompt from classification results
        app_name = voice_candidates[0].application_name if voice_candidates else "Unknown"
        prompt_text = render_dynamic_prompt(
            "classification_summary",
            complaint_text   = result.corrected_text[:100],
            application_name = app_name,
            fault_type       = result.fault_type or "other",
            severity         = result.severity   or "normal",
        )

    timings["TTS prompt build"] = (time.time() - t_tts_start) * 1000
    timings["Total (adapter)"]  = (time.time() - t_start) * 1000

    return ComplaintProcessingResult(
        status               = "accepted",
        prompt_text          = prompt_text,
        corrected_transcript = result.corrected_text,
        intake_id            = result.intake_id,
        fault_type           = result.fault_type,
        severity             = result.severity,
        candidates           = voice_candidates,
        timings              = timings,
        confidence           = state.confidence,
        suggested_resolution = state.suggested_resolution,
        needs_followup       = state.needs_followup,
        followup_question    = state.followup_question,
    )
