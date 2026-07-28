"""
services/conversation_state.py — Shared Conversation Primitives
================================================================
Defines the three core abstractions used by the unified complaint pipeline:

  ConversationState  — Structured snapshot of what has been extracted from
                       one or more complaint turns (heuristic + LLM results).

  PipelineResult     — The unified return type of services.pipeline.process_complaint().
                       Both the manual intake adapter and the voice adapter consume this.

  ConversationManager — Utility class for follow-up question generation and
                        clarification merging.  Designed for easy extension into
                        a full multi-turn ConversationManager in Phase 4 (LiveKit).

Design principles:
  - No DB imports — purely in-memory dataclasses.  The caller decides persistence.
  - ConversationManager is a class (not module functions) so Phase 4 can subclass
    it and add turn-loop logic without touching the pipeline.
  - All fields have defaults so the objects can be constructed incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


# ===========================================================================
# ConversationState
# ===========================================================================

@dataclass
class ConversationState:
    """
    Structured representation of what has been extracted from a complaint.

    Lifecycle:
      1. Created and populated by the heuristic evaluator (target, symptom, etc.).
      2. Enriched by the LLM when the complaint is sufficient
         (fault_type, severity, confidence, summary, suggested_resolution).

    target_type values:
      "software"  — a registered application name was matched
      "hardware"  — a physical device keyword was matched (laptop, printer, …)
      "network"   — a connectivity keyword was matched (wifi, vpn, …)
      "unknown"   — no identifiable target found

    followup_reason values (set when needs_followup=True via heuristic path):
      "missing_target"   — symptom/action present but no target system identified
      "missing_symptom"  — target found but no description of what's wrong
      "missing_context"  — complaint has no recognisable signals at all
      "rejected"         — guardrail rejected the text (not an IT complaint / gibberish)
    """

    # Raw complaint text after guardrail correction
    complaint_text: str = ""

    # ── Heuristic-extracted entities ──────────────────────────────────────
    target: Optional[str] = None         # e.g. "SAP", "wifi", "laptop"
    target_type: str = "unknown"         # "software" | "hardware" | "network" | "unknown"
    symptom: Optional[str] = None        # first matched symptom term
    action: Optional[str] = None         # first matched action term
    error_details: Optional[str] = None  # first matched error-pattern term
    heuristic_score: int = 0

    # ── Sufficiency gate result ───────────────────────────────────────────
    is_sufficient: bool = False
    needs_followup: bool = False
    followup_reason: Optional[str] = None   # see docstring above
    followup_question: Optional[str] = None  # human-readable question to display/speak

    # ── LLM classification results (populated only when sufficient) ───────
    fault_type: Optional[str] = None
    severity: Optional[str] = None
    confidence: float = 0.0
    suggested_resolution: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain dict (safe for JSON serialisation)."""
        return asdict(self)


# ===========================================================================
# PipelineResult
# ===========================================================================

@dataclass
class PipelineResult:
    """
    The unified return type of services.pipeline.process_complaint().

    status values:
      "complete"               — complaint was classified; ticket proposal is ready
      "pending_clarification"  — complaint was insufficient; follow-up question set
      "rejected"               — guardrail rejected the text

    Both the manual intake router and the voice adapter consume this object.
    Each adapter is responsible for mapping it to its own response schema.
    """

    status: str                                          # "complete" | "pending_clarification" | "rejected"
    state: ConversationState

    corrected_text: str = ""
    intake_id: Optional[int] = None
    fault_type: Optional[str] = None
    severity: Optional[str] = None
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    potential_duplicates: List[Dict[str, Any]] = field(default_factory=list)
    is_repeat_caller: bool = False
    history_hit: bool = False
    clarification_attempts: int = 0


# ===========================================================================
# ConversationManager
# ===========================================================================

class ConversationManager:
    """
    Utility class responsible for conversational aspects of complaint processing.

    Current scope (Phase 3):
      • Generate targeted follow-up questions from a ConversationState.
      • Merge a clarification answer into the original complaint text.

    Future scope (Phase 4 — LiveKit multi-turn):
      • Own the full conversation turn loop.
      • Decide when the conversation is complete (all required slots filled).
      • Manage multi-turn state across multiple STT utterances.
      • Route completed state back to the pipeline for classification.

    The class structure (rather than bare module-level functions) ensures
    Phase 4 can extend or override behaviour without another pipeline refactor.
    """

    # Follow-up question templates.
    # Key: (followup_reason, target_type) — both strings.
    # Lookup order: (reason, type) → (reason, "unknown") → _GENERIC_FALLBACK
    _TEMPLATES: Dict[tuple, str] = {

        # ── missing_context: nothing identifiable at all ──────────────────
        ("missing_context", "unknown"): (
            "I need a bit more detail. Which application or device is affected, "
            "and what is happening when you try to use it?"
        ),

        # ── missing_target: symptom present but no system identified ──────
        ("missing_target", "unknown"): (
            "Which application or system are you referring to?"
        ),
        ("missing_target", "software"): (
            "Which application are you referring to?"
        ),
        ("missing_target", "hardware"): (
            "Which device is affected — for example, your laptop, desktop, or printer?"
        ),
        ("missing_target", "network"): (
            "Which network connection is the problem with — WiFi, VPN, or your wired connection?"
        ),

        # ── missing_symptom: target found but nothing about what's wrong ──
        ("missing_symptom", "software"): (
            "What exactly is happening with {target}? "
            "For example, is it slow, showing an error, or completely unavailable?"
        ),
        ("missing_symptom", "hardware"): (
            "What is happening with your {target}? "
            "For example, is it not turning on, running slowly, or showing an error?"
        ),
        ("missing_symptom", "network"): (
            "What is happening with the {target}? "
            "For example, is it completely down, slow, or intermittent?"
        ),
        ("missing_symptom", "unknown"): (
            "Can you describe what is happening? "
            "For example, is it showing an error, not loading, or completely unavailable?"
        ),
    }

    _GENERIC_FALLBACK = (
        "Could you provide a bit more detail about the issue you are experiencing?"
    )

    @classmethod
    def build_followup_question(cls, state: ConversationState) -> str:
        """
        Generate a targeted follow-up question from a ConversationState.

        Used when the heuristic path determines the complaint is insufficient,
        meaning the LLM has NOT been called yet and cannot generate its own
        follow-up question.

        Args:
            state: A ConversationState with needs_followup=True.

        Returns:
            A human-readable question string suitable for display or TTS.
        """
        reason = state.followup_reason or "missing_context"
        target_type = state.target_type or "unknown"

        template = (
            cls._TEMPLATES.get((reason, target_type))
            or cls._TEMPLATES.get((reason, "unknown"))
            or cls._GENERIC_FALLBACK
        )

        # Fill in {target} placeholder if the template uses it
        if "{target}" in template:
            display_target = state.target or "the system"
            template = template.format(target=display_target)

        return template

    @staticmethod
    def merge_clarification(
        original_text: str,
        clarification: str,
        state: ConversationState,
    ) -> str:
        """
        Merge a follow-up clarification answer into the original complaint text.

        Produces a combined text that process_complaint() can re-evaluate.
        The simple period-separated concatenation is intentional so the heuristic
        scorer can re-score the combined complaint without special-casing.

        Phase 4 note: this can be made smarter (slot-filling, template injection)
        by overriding in a subclass once multi-turn conversation data is available.

        Args:
            original_text:  The original (possibly corrected) complaint text.
            clarification:  The operator's / caller's clarification answer.
            state:          The ConversationState from the first turn (for context).

        Returns:
            A merged complaint string ready for process_complaint().
        """
        original = original_text.rstrip(". ")
        clarification = clarification.strip()
        return f"{original}. {clarification}"
