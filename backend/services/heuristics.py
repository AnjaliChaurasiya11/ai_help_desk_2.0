"""
services/heuristics.py — Pre-Classification Complaint Sufficiency Scorer
=========================================================================
Provides a deterministic, scoring-based check that runs before the LLM
receives a complaint. If the complaint lacks enough context to classify
accurately, `evaluate_complaint_sufficiency` returns is_insufficient=True
along with a structured reason and the extracted entities so the caller
can populate a ConversationState without re-parsing the text.

Design principles:
  - No hard word-count rule.
  - All term lists are module-level constants — edit only this section.
  - Application names are accepted as a pre-fetched, cached argument to
    avoid a database query on every request.
  - Score >= SUFFICIENCY_THRESHOLD is required:
      * Target alone (score 2) is NOT sufficient.
      * Target + at least one symptom/action/error (score >= 3) IS sufficient.
  - GENERIC_TARGETS is split into HARDWARE_TARGETS / NETWORK_TARGETS /
    SOFTWARE_TARGETS so callers can determine target_type without re-matching.
"""

import logging
import re                        # imported for future regex patterns; kept for consistency
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


# ===========================================================================
# CONFIGURABLE TERM LISTS
# Edit these sets to tune the heuristic without touching any logic below.
# ===========================================================================

# Physical device keywords → target_type = "hardware"
HARDWARE_TARGETS: frozenset = frozenset({
    "laptop", "computer", "pc", "desktop", "workstation",
    "printer", "scanner", "device", "tablet", "phone", "mobile",
    "monitor", "keyboard", "mouse", "headset",
})

# Network/connectivity keywords → target_type = "network"
NETWORK_TARGETS: frozenset = frozenset({
    "wifi", "wi-fi", "network", "internet", "intranet", "vpn",
    "lan", "wan", "router", "switch", "firewall", "bandwidth",
})

# Generic software/system keywords → target_type = "software"
# Used only when no registered application name is matched.
SOFTWARE_TARGETS: frozenset = frozenset({
    "portal", "system", "application", "app", "software",
    "email", "outlook", "browser", "server", "website", "platform",
    "tool", "module", "dashboard", "interface",
})

# Observable fault/symptom keywords — evidence the user has described a problem.
SYMPTOM_TERMS: frozenset = frozenset({
    "error", "fail", "failed", "failing", "failure",
    "slow", "down", "not working", "not loading", "not opening",
    "spinning", "crash", "crashed", "broken", "offline",
    "unavailable", "stuck", "hangs", "hang", "freeze", "frozen",
    "unresponsive", "issue", "problem", "cannot", "can't", "unable",
    "won't", "doesn't work", "stopped", "dead", "blank", "missing",
    "inaccessible", "no access", "blocked",
})

# User-action verbs — evidence the user has described what they were doing.
ACTION_TERMS: frozenset = frozenset({
    "login", "log in", "log-in", "sign in", "sign-in",
    "click", "clicked", "open", "opened", "download", "upload",
    "access", "accessing", "trying to", "attempted", "submit",
    "submitted", "save", "saving", "update", "updating",
    "connect", "connecting", "run", "running", "install",
    "installing", "load", "loading", "refresh", "reset",
    "change", "edit", "delete", "print",
})

# Specific error details — codes, patterns that narrow the fault precisely.
ERROR_PATTERNS: frozenset = frozenset({
    "404", "500", "403", "401", "408", "503",
    "timeout", "timed out", "blue screen", "bsod",
    "error code", "exception", "traceback", "http",
    "unauthorized", "forbidden", "internal server",
    "ssl", "certificate", "dns", "ip address",
})

# Minimum score required for a complaint to be considered sufficient.
# Scoring rubric:
#   Identifiable target  → +2
#   Observable symptom   → +1
#   User action/context  → +1
#   Specific error       → +1
# A score of 3 means the user must mention a target AND at least one
# additional piece of context (symptom, action, or error code).
SUFFICIENCY_THRESHOLD: int = 3


# ===========================================================================
# PUBLIC API
# ===========================================================================

def evaluate_complaint_sufficiency(
    text: str,
    cached_app_names: Optional[List[str]] = None,
) -> Dict:
    """
    Score the complaint and determine whether it is sufficient to classify.

    Args:
        text:             The raw complaint string.
        cached_app_names: A list of registered application names from the DB,
                          pre-fetched and cached by the caller.  Pass None or []
                          to skip registered-app matching.

    Returns a dict:
        {
            "is_insufficient": bool,
            "score":           int,
            "reason":          str | None,    # None when sufficient
                                               # "missing_target"
                                               # "missing_symptom"
                                               # "missing_context"
            # Extracted entities (for ConversationState population):
            "target":      str | None,         # matched term or app name
            "target_type": str,                # "software" | "hardware" | "network" | "unknown"
            "symptom":     str | None,         # first matched SYMPTOM_TERM
            "action":      str | None,         # first matched ACTION_TERM
            "error":       str | None,         # first matched ERROR_PATTERN
        }
    """
    lower = text.lower()

    score = 0
    has_target  = False
    has_symptom = False
    has_action  = False
    has_error   = False

    matched_target: Optional[str] = None
    target_type: str = "unknown"
    matched_symptom: Optional[str] = None
    matched_action: Optional[str] = None
    matched_error: Optional[str] = None

    # ── 1. Identifiable target (+2) ──────────────────────────────────────
    # Priority: registered app name > hardware > network > software

    if cached_app_names:
        for app_name in cached_app_names:
            if app_name.lower() in lower:
                has_target = True
                matched_target = app_name
                target_type = "software"
                break

    if not has_target:
        for term in HARDWARE_TARGETS:
            if term in lower:
                has_target = True
                matched_target = term
                target_type = "hardware"
                break

    if not has_target:
        for term in NETWORK_TARGETS:
            if term in lower:
                has_target = True
                matched_target = term
                target_type = "network"
                break

    if not has_target:
        for term in SOFTWARE_TARGETS:
            if term in lower:
                has_target = True
                matched_target = term
                target_type = "software"
                break

    if has_target:
        score += 2

    # ── 2. Observable symptom (+1) ────────────────────────────────────────
    for term in SYMPTOM_TERMS:
        if term in lower:
            has_symptom = True
            matched_symptom = term
            score += 1
            break

    # ── 3. User action / context (+1) ────────────────────────────────────
    for term in ACTION_TERMS:
        if term in lower:
            has_action = True
            matched_action = term
            score += 1
            break

    # ── 4. Specific error details (+1) ────────────────────────────────────
    for term in ERROR_PATTERNS:
        if term in lower:
            has_error = True
            matched_error = term
            score += 1
            break

    is_insufficient = score < SUFFICIENCY_THRESHOLD

    # Determine the most actionable reason for generating targeted follow-up questions.
    reason: Optional[str] = None
    if is_insufficient:
        if score == 0:
            reason = "missing_context"
        elif not has_target:
            reason = "missing_target"
        else:
            # Has target (score >= 2) but no symptom/action/error.
            reason = "missing_symptom"

    logger.debug(
        "[heuristics] text=%r  score=%d/%d  insufficient=%s  reason=%s  "
        "(target=%r type=%s symptom=%r action=%r error=%r)",
        text[:60], score, SUFFICIENCY_THRESHOLD,
        is_insufficient, reason,
        matched_target, target_type, matched_symptom, matched_action, matched_error,
    )

    return {
        "is_insufficient": is_insufficient,
        "score":           score,
        "reason":          reason,
        # Extracted entities — used to populate ConversationState
        "target":          matched_target,
        "target_type":     target_type,
        "symptom":         matched_symptom,
        "action":          matched_action,
        "error":           matched_error,
    }


# ===========================================================================
# APPLICATION NAME CACHE
# ===========================================================================

import time as _time
from sqlmodel import Session as _Session

_app_names_cache: Optional[List[str]] = None
_app_names_fetched_at: float = 0.0
_APP_NAMES_CACHE_TTL: int = 300  # seconds (5 minutes)


def get_cached_app_names(session: _Session) -> List[str]:
    """
    Return a list of all registered Application names from the DB.
    Results are cached for _APP_NAMES_CACHE_TTL seconds to avoid
    a DB round-trip on every complaint submission.
    """
    global _app_names_cache, _app_names_fetched_at

    now = _time.monotonic()
    if _app_names_cache is None or (now - _app_names_fetched_at) > _APP_NAMES_CACHE_TTL:
        from models import Application
        from sqlmodel import select
        rows = session.exec(select(Application.name)).all()
        _app_names_cache = list(rows)
        _app_names_fetched_at = now
        logger.info("[heuristics] App name cache refreshed: %d entries.", len(_app_names_cache))

    return _app_names_cache
