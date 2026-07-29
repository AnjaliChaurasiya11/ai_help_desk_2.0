"""
voice/prompts.py — Prompt Management (Phase 2)
=================================================
Manages static pre-recorded audio prompts and dynamic text templates
for TTS synthesis.

Requirements Covered:
  R-36: Pre-recorded prompts (greeting, retry, goodbye)
  R-37: Dynamic TTS prompts (service number, ticket number)

Design Decisions:
  - Static prompts are WAV files stored in backend/voice/static_prompts/.
    These are served directly as binary responses — zero TTS latency.
  - Dynamic prompts use string templates with placeholders, rendered at
    runtime and fed to the TTS engine.
  - Bilingual templates (English + Hindi/Hinglish) for inclusive UX.
  - Prompt keys are constants so the router and session manager never
    hardcode strings.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger("voice.prompts")

# ─────────────────────────────────────────────────────────────────────
# Static prompt file paths
# ─────────────────────────────────────────────────────────────────────

# Directory containing pre-recorded WAV files
STATIC_PROMPTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_prompts")
)

# Prompt keys → filenames
STATIC_PROMPTS = {
    "greeting":            "greeting.wav",
    "ask_service_number":  "ask_service_number.wav",
    "ask_complaint":       "ask_complaint.wav",
    "retry_service":       "retry_service_number.wav",
    "fallback_operator":   "fallback_operator.wav",
    "goodbye":             "goodbye.wav",
    "confirm_yes_no":      "confirm_yes_no.wav",
    "processing":          "processing.wav",
    "heard_as":            "heard_as.wav",         # "I heard your service number as"
    "is_that_correct":     "is_that_correct.wav",  # "Is that correct?"
    "ask_another_complaint": "ask_another_complaint.wav",  # R-42: loop for a second ticket
    "unable_to_identify":  "unable_to_identify.wav",       # Max clarification attempts exhausted
}


def get_static_prompt_path(key: str) -> Optional[str]:
    """
    Get the full filesystem path of a pre-recorded prompt WAV file.

    Returns None if the key is unknown or the file doesn't exist.
    """
    filename = STATIC_PROMPTS.get(key)
    if not filename:
        logger.warning("Unknown static prompt key: '%s'", key)
        return None

    path = os.path.join(STATIC_PROMPTS_DIR, filename)
    if not os.path.isfile(path):
        logger.warning("Static prompt file missing: %s", path)
        return None

    return path


def get_static_prompt_bytes(key: str) -> Optional[bytes]:
    """Load a pre-recorded prompt WAV file into memory."""
    path = get_static_prompt_path(key)
    if path is None:
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except IOError as exc:
        logger.error("Failed to read prompt '%s': %s", key, exc)
        return None


# ─────────────────────────────────────────────────────────────────────
# Dynamic prompt templates
# ─────────────────────────────────────────────────────────────────────

DYNAMIC_TEMPLATES = {
    # Service number confirmation (R-31)
    "confirm_service_number": (
        "I heard your service number as {service_number}. Is that correct? Please say yes or no."
    ),

    # Complaint transcript read-back
    "confirm_complaint": (
        "Your complaint is: {complaint_text}. Is that correct?"
    ),

    # Application identification confirmation
    "confirm_application": (
        "Your complaint appears to be related to the {application_name} application. Is that correct?"
    ),

    # Ticket created — read back number (R-38)
    "ticket_created": (
        "Your ticket has been created. "
        "Your ticket number is: {ticket_number}. "
        "Please make a note of this number."
    ),

    # Retry — service number not understood
    "retry_service_number": (
        "Sorry, I could not understand your service number. "
        "Please try again. Attempt {attempt} of {max_attempts}."
    ),

    # Fallback to operator
    "fallback_to_operator": (
        "We were unable to verify your service number. "
        "An operator will now assist you."
    ),

    # Classification summary for operator
    "classification_summary": (
        "Predicted application: {application_name}. "
        "Fault type: {fault_type}. "
        "Severity: {severity}."
    ),
}


def render_dynamic_prompt(key: str, **kwargs) -> str:
    """
    Render a dynamic prompt template with the given keyword arguments.

    Parameters
    ----------
    key : str
        Template key from DYNAMIC_TEMPLATES.
    **kwargs
        Template placeholders (e.g., service_number="2893456P").

    Returns
    -------
    str
        The rendered prompt text, ready for TTS synthesis.

    Raises
    ------
    KeyError
        If the template key is unknown.
    """
    template = DYNAMIC_TEMPLATES.get(key)
    if template is None:
        raise KeyError(f"Unknown dynamic prompt template: '{key}'")

    try:
        return template.format(**kwargs)
    except KeyError as exc:
        logger.error(
            "Missing placeholder in prompt '%s': %s  (provided: %s)",
            key, exc, list(kwargs.keys()),
        )
        raise


# ─────────────────────────────────────────────────────────────────────
# Fallback text for when static files are missing
# ─────────────────────────────────────────────────────────────────────

FALLBACK_TEXT = {
    "greeting": (
        "Please state your service number."
    ),
    "ask_service_number": "Please state your service number.",
    "ask_complaint": "Please describe your problem. You may start speaking now.",
    "retry_service": "Sorry, I could not catch your service number. Please say it again.",
    "fallback_operator": "We were unable to verify your service number. An operator will now assist you.",
    "goodbye": "Thank you. Your ticket has been created. Please note your ticket number.",
    "confirm_yes_no": "Please say yes or no.",
    "processing": "Please wait. Your request is being processed.",
    "ask_another_complaint": "Do you have another complaint to report? Please say yes or no.",
    # Shown / spoken when the system cannot identify the complaint after all clarification attempts.
    # Keep this wording empathetic and action-oriented so the caller knows what happens next.
    "unable_to_identify": (
        "I was unable to identify your complaint after multiple attempts. "
        "I am routing you to an operator who will assist you directly."
    ),
}


def get_prompt_text(key: str) -> str:
    """
    Get the text content of a prompt (for TTS fallback when static
    WAV files are not available).
    """
    return FALLBACK_TEXT.get(key, "")


# ─────────────────────────────────────────────────────────────────────
# Live Call prompts — conversational, phone-call-friendly variants
# Used exclusively by the LiveKit adapter path. The REST/web path
# continues to use the templates above, keeping both paths independent.
# ─────────────────────────────────────────────────────────────────────

LIVE_CALL_FALLBACK_TEXT: dict = {
    # Opening greeting — warm and brief
    "greeting": (
        "AI Help Desk. How can I assist you today?"
    ),

    # First thing asked after the greeting succeeds
    "ask_service_number": (
        "Please go ahead and tell me your service number."
    ),

    # After service number is confirmed — transition to complaint
    "ask_complaint": (
        "Got it. What's the issue you'd like to report?"
    ),

    # Couldn't catch a valid service number — try again
    "retry_service": (
        "Sorry, I didn't catch that. Could you repeat your service number?"
    ),

    # Max retries exceeded — routing away
    "fallback_operator": (
        "I'm having trouble verifying your service number. "
        "I'll connect you to a support agent right away."
    ),

    # Call wrap-up
    "goodbye": (
        "Your ticket has been logged. Have a good day."
    ),

    # Unclear yes/no — ask again
    "confirm_yes_no": (
        "Sorry — could you just say yes or no?"
    ),

    # Processing hold
    "processing": (
        "One moment."
    ),

    # Ask another complaint loop
    "ask_another_complaint": (
        "Is there anything else you'd like to report?"
    ),

    # Could not identify complaint after all attempts
    "unable_to_identify": (
        "I'm having trouble understanding the issue. "
        "I'll transfer you to a support agent who can help."
    ),
}

LIVE_CALL_DYNAMIC_TEMPLATES: dict = {
    # Read back the service number for confirmation
    "confirm_service_number": (
        "Just to confirm, I have your service number as {service_number} — is that right?"
    ),

    # Retry with attempt counter
    "retry_service_number": (
        "I didn't quite catch that. Could you repeat your service number? "
        "That's attempt {attempt} of {max_attempts}."
    ),

    # Fallback to operator
    "fallback_to_operator": (
        "I wasn't able to verify your service number. "
        "Connecting you to an agent now."
    ),

    # Classification result read-back — concise summary
    "classification_summary": (
        "Thanks. I've logged your issue as a {fault_type} complaint, "
        "severity {severity}, under {application_name}. "
        "Your ticket is being created now."
    ),

    # Guardrail rejection — couldn't understand the complaint
    "complaint_rejected": (
        "{reason} Could you describe the problem again?"
    ),
}


def get_live_call_prompt(key: str) -> str:
    """
    Return the live-call-friendly text for a static prompt key.
    Falls back to the standard FALLBACK_TEXT if the key is not
    present in LIVE_CALL_FALLBACK_TEXT.
    """
    return LIVE_CALL_FALLBACK_TEXT.get(key) or FALLBACK_TEXT.get(key, "")


def render_live_call_prompt(key: str, **kwargs) -> str:
    """
    Render a live-call dynamic template.
    Falls back to render_dynamic_prompt() if the key is not in
    LIVE_CALL_DYNAMIC_TEMPLATES, so the adapter never breaks on
    an unknown key.
    """
    template = LIVE_CALL_DYNAMIC_TEMPLATES.get(key)
    if template is None:
        # Graceful fallback to the standard template
        return render_dynamic_prompt(key, **kwargs)
    try:
        return template.format(**kwargs)
    except KeyError as exc:
        logger.error(
            "Missing placeholder in live-call prompt '%s': %s  (provided: %s)",
            key, exc, list(kwargs.keys()),
        )
        raise

