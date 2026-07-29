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
from voice.prompts import render_dynamic_prompt, render_live_call_prompt, get_live_call_prompt
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
    ticket_number: Optional[str] = None        # TIC-YYYYMM-XXXX — set when auto-created
    fault_type: Optional[str] = None
    severity: Optional[str] = None
    application_name: Optional[str] = None     # Primary application display name
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
        reason = result.state.followup_question or "I wasn't able to understand that."
        return ComplaintProcessingResult(
            status               = "rejected",
            prompt_text          = render_live_call_prompt(
                                       "complaint_rejected", reason=reason
                                   ),
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
    elif result.status == "unable_to_identify":
        # Max clarification attempts exhausted — route to operator for manual handling.
        next_state = SessionState.OPERATOR_REVIEW
    else:  # "complete"
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

    # Initialise here so they are always defined regardless of which branch runs
    ticket_number: Optional[str] = None
    app_name: Optional[str] = None

    if state.needs_followup and state.followup_question:

        # Incomplete complaint — speak the follow-up question
        prompt_text = state.followup_question
        logger.info(
            "[voice.CP] Follow-up triggered (reason=%s, confidence=%.2f) — "
            "overriding TTS prompt.",
            state.followup_reason, state.confidence,
        )
    elif result.status == "unable_to_identify":
        # Three clarification attempts exhausted — inform the caller and route to operator
        prompt_text = get_live_call_prompt("unable_to_identify")
        logger.info(
            "[voice.CP] unable_to_identify after %d attempts — operator fallback TTS.",
            result.clarification_attempts,
        )
    else:
        # Complete classification — auto-create ticket and read back a brief confirmation
        app_name = voice_candidates[0].application_name if voice_candidates else "Unknown"
        primary_app_id = voice_candidates[0].application_id if voice_candidates else None

        # ── Auto-create the Ticket so the summary shows a real TIC-YYYYMM-XXXX ──
        try:
            from routers.tickets import _generate_ticket_number
            from models import Ticket, TicketHistory
            from sqlalchemy import text as sa_text

            intake_obj = db_session.get(Intake, result.intake_id) if result.intake_id else None
            if intake_obj and primary_app_id:
                ticket_number = _generate_ticket_number(db_session)
                ticket = Ticket(
                    ticket_number=ticket_number,
                    intake_id=intake_obj.id,
                    primary_application_id=primary_app_id,
                    status="open",
                    fault_type=result.fault_type,
                    severity=result.severity,
                    complainant_service_no=intake_obj.complainant_service_no,
                    complainant_rank=intake_obj.complainant_rank,
                    complainant_unit=intake_obj.complainant_unit,
                    assignee_id=None,
                    created_by_service_no=complainant_service_no or "voice-agent",
                )
                db_session.add(ticket)
                history = TicketHistory(
                    ticket_number=ticket_number,
                    changed_by="voice-agent",
                    old_status="",
                    new_status="open",
                    notes="Ticket auto-created by Live AI Support voice call.",
                )
                db_session.add(history)
                db_session.commit()
                logger.info(
                    "[voice.CP] Auto-created ticket %s for intake_id=%s",
                    ticket_number, result.intake_id,
                )
        except Exception as tc_exc:
            logger.error("[voice.CP] Failed to auto-create ticket: %s", tc_exc, exc_info=True)
            # Non-fatal: ticket_number stays None; summary will show intake ID as fallback

        prompt_text = render_live_call_prompt(
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
        ticket_number        = ticket_number if result.status not in ("rejected", "unable_to_identify", "pending_clarification") else None,
        fault_type           = result.fault_type,
        severity             = result.severity,
        application_name     = app_name if result.status not in ("rejected", "unable_to_identify", "pending_clarification") else None,
        candidates           = voice_candidates,
        timings              = timings,
        confidence           = state.confidence,
        suggested_resolution = state.suggested_resolution,
        needs_followup       = state.needs_followup,
        followup_question    = state.followup_question,
    )
