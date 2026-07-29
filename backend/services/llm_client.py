"""
services/llm_client.py — LLM Guardrail & Fault/Severity Classifier
=====================================================================
Connects to the air-gapped vLLM server (Gemma 4) using the standard
OpenAI-compatible API to perform two functions:

  1. verify_and_correct_text() — Guardrail that:
       - Rejects non-English/Hindi/Hinglish input.
       - Fixes STT transcription errors (wrong words, garbled speech).
       - Rejects completely nonsensical complaints.
       - Returns the corrected text if valid.

  2. predict_fault_and_severity() — Classification that:
       - Predicts the fault_type from the known set of categories.
       - Predicts the severity from the known set of categories.
       - Replaces the old mDeBERTa-v3 zero-shot pipeline.

OFFLINE MODE:
  When settings.MOCK_LLM = True (default at home), no network calls are made.
  The functions return realistic mock data so the UI and logic can be built
  and tested without the air-gapped vLLM server.

  To switch to production mode:
    1. Set MOCK_LLM=False in .env or config.py
    2. Set VLLM_API_URL to the correct server URL in .env or config.py
"""

import json
import logging
from typing import Optional

from config import settings
from schemas import VALID_FAULT_TYPES, VALID_SEVERITIES

logger = logging.getLogger("services.llm_client")

# ---------------------------------------------------------------------------
# Lazy-import the openai package so the rest of the app still boots even if
# the package is not yet installed (e.g., in mock mode during development).
# ---------------------------------------------------------------------------
_openai_client = None

def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        try:
            import openai
            _openai_client = openai.OpenAI(
                base_url=settings.VLLM_API_URL,
                api_key=settings.VLLM_API_KEY,
            )
        except ImportError:
            logger.warning(
                "openai package not installed. Run: pip install openai. "
                "This is only required in production (MOCK_LLM=False)."
            )
            raise
    return _openai_client


# ---------------------------------------------------------------------------
# Internal helper — call the LLM and return the response text
# ---------------------------------------------------------------------------
import time

def _call_llm(system_prompt: str, user_prompt: str, temperature: float = 0.1, stage_name: str = "LLM") -> str:
    """Make a single call to the vLLM server. Returns the raw response string."""
    client = _get_openai_client()
    
    t_start = time.time()
    response = client.chat.completions.create(
        model=settings.VLLM_MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=256,
        response_format={"type": "json_object"},  # Forces valid JSON output
    )
    t_end = time.time()
    
    total_time_ms = (t_end - t_start) * 1000
    
    prompt_tokens = response.usage.prompt_tokens if response.usage else len(system_prompt) + len(user_prompt)
    response_tokens = response.usage.completion_tokens if response.usage else 0
    
    logger.info(
        "[%s] API Request Time: %.0f ms | Prompt Tokens: %s | Response Tokens: %s",
        stage_name, total_time_ms, prompt_tokens, response_tokens
    )
    
    return response.choices[0].message.content.strip()


# ===========================================================================
# PUBLIC FUNCTION 1: verify_and_correct_text
# ===========================================================================

_VERIFY_SYSTEM_PROMPT = """You are an expert IT support dispatcher for an Enterprise Help Desk.
Your job is to check if an incoming complaint text is valid and correct any Speech-to-Text (STT) transcription errors.
RULES:
1. ONLY accept complaints in English, Hindi, or Hinglish (a mix of Hindi and English). Reject any other language.
2. REJECT complaints that are completely nonsensical, random, or not related to any IT system or application problem (e.g. "what is the capital of France", "the dog ate my shoe").
3. ACCEPT and CORRECT complaints that are clearly about an IT issue but have garbled words due to STT errors (e.g. "my pasword is lok" should become "my password is locked").
4. Do NOT add information that was not present in the original text. Only fix obvious transcription errors.
5. Do NOT change the meaning of the complaint.
ACCEPTED LANGUAGES:
- English (any dialect or formality level)
- Hindi written in Roman script (e.g. "mera system on nahi ho raha")
- Hinglish — a natural mix of Hindi and English (e.g. "login nahi ho raha mujhe", "password reset karna hai")
- Do NOT reject text just because it contains Hindi words mixed with English — this is very common and MUST be accepted.
REJECTION RULES (reject ONLY if ALL of these are clearly true):
1. The text is in a completely unsupported language (e.g. French, Arabic, Chinese, Spanish) with NO English or Hindi words at all.
2. The text is completely unrelated to any IT system, software, hardware, network, login, or workplace application (e.g. "what is the capital of France", "the dog ate my shoe", "recipe for biryani").
3. The text is pure gibberish with no discernible meaning related to a technical problem (e.g. "asdf qwer zxcv", "blah blah blah").
DO NOT REJECT:
- Short complaints like "system slow", "login nahi ho raha", "network down" — these are VALID even if brief.
- Complaints with STT errors, garbled words, or repeated words — fix them instead.
- Complaints that mention an application name, even without much detail.
- Complaints in all-caps or all-lowercase.
- Complaints with punctuation errors or missing spaces.
STT CORRECTION RULES:
- Fix obvious homophones and misheard words caused by speech recognition:
    "pasword" → "password", "lok" → "locked", "acess" → "access",
    "loggin" → "login", "sistum" → "system", "notwerk" → "network",
    "cant" → "cannot", "wont" → "won't", "errror" → "error"
- Fix repeated words caused by STT stuttering: "my my system" → "my system"
- Fix missing spaces: "systemdown" → "system down", "cantlogin" → "can't login"
- Do NOT add information that was not present. Only fix obvious transcription errors.
- Do NOT change the meaning of the complaint.
RESPONSE FORMAT — You MUST respond with ONLY a valid JSON object:
If the complaint is valid:
{"status": "accepted", "corrected_text": "the corrected complaint text here"}
If the complaint is invalid:
{"status": "rejected", "reason": "A clear, brief, user-friendly reason why the complaint was rejected."}
EXAMPLES:
  "my pasword is lok" → {"status": "accepted", "corrected_text": "my password is locked"}
  "sistum nahi chal raha" → {"status": "accepted", "corrected_text": "system nahi chal raha"}
  "login nahi ho raha mujhe" → {"status": "accepted", "corrected_text": "login nahi ho raha mujhe"}
  "network slow hai sab ke liye" → {"status": "accepted", "corrected_text": "network slow hai sab ke liye"}
  "system slow" → {"status": "accepted", "corrected_text": "system slow"}
  "my my system is not working" → {"status": "accepted", "corrected_text": "my system is not working"}
  "what is the capital of France" → {"status": "rejected", "reason": "This does not appear to be an IT complaint. Please describe a technical issue."}
  "bonjour comment allez vous" → {"status": "rejected", "reason": "Please describe your complaint in English, Hindi, or Hinglish only."}
  "asdf qwer zxcv" → {"status": "rejected", "reason": "Could not understand your complaint. Please describe your technical issue clearly."}
Do NOT include any explanation, markdown, or text outside of the JSON object."""


def verify_and_correct_text(raw_text: str) -> dict:
    """
    Passes the raw complaint text through the LLM guardrail.

    Returns a dict with one of two shapes:
      - {"status": "accepted", "corrected_text": "..."}
      - {"status": "rejected", "reason": "..."}
    """
    # ── MOCK MODE ────────────────────────────────────────────────────────────
    if settings.MOCK_LLM:
        logger.info("[LLM MOCK] verify_and_correct_text called — returning mock response.")
        text_lower = raw_text.lower().strip()

        # Simulate a rejection for obviously nonsensical input
        NONSENSE_TRIGGERS = [
            "capital of", "what is", "who is", "dog ate",
            "weather", "recipe", "movie", "song", "cricket",
        ]
        if any(trigger in text_lower for trigger in NONSENSE_TRIGGERS):
            return {
                "status": "rejected",
                "reason": "[MOCK] This does not appear to be an IT helpdesk complaint. Please describe a technical issue with a system or application.",
            }

        # Simulate a language rejection for clearly non-English/Hindi text
        # (Basic check: if it contains characters from other scripts)
        NON_SUPPORTED_SCRIPTS = ["مرحبا", "你好", "こんにちは", "bonjour", "hola"]
        if any(word in text_lower for word in NON_SUPPORTED_SCRIPTS):
            return {
                "status": "rejected",
                "reason": "[MOCK] Please describe your complaint in English, Hindi, or Hinglish only.",
            }

        # Otherwise accept and return the text as-is with a mock fix note
        corrected = raw_text.strip()
        # Simulate a common STT fix: 'pasword' -> 'password', 'lok' -> 'locked'
        corrected = corrected.replace("pasword", "password").replace(" lok ", " locked ")
        return {"status": "accepted", "corrected_text": corrected}

    # ── PRODUCTION MODE ──────────────────────────────────────────────────────
    logger.info("[LLM] Calling vLLM to verify complaint text.")
    try:
        raw_response = _call_llm(_VERIFY_SYSTEM_PROMPT, raw_text, stage_name="Complaint Verification LLM")
        result = json.loads(raw_response)

        # Validate the response structure
        if "status" not in result:
            raise ValueError("LLM response missing 'status' field.")
        if result["status"] == "accepted" and "corrected_text" not in result:
            raise ValueError("LLM accepted complaint but missing 'corrected_text'.")
        if result["status"] == "rejected" and "reason" not in result:
            raise ValueError("LLM rejected complaint but missing 'reason'.")

        return result

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        # If the LLM returns malformed JSON, log it and fail open (accept the text as-is)
        # to avoid blocking legitimate complaints due to a model error.
        logger.error("[LLM] Malformed response from vLLM during verification: %s", e)
        return {"status": "accepted", "corrected_text": raw_text}
    except Exception as e:
        logger.error("[LLM] Unexpected error calling vLLM for verification: %s", e)
        return {"status": "accepted", "corrected_text": raw_text}


# ===========================================================================
# PUBLIC FUNCTION 1.5: analyze_complaint_category
# ===========================================================================

_CATEGORY_SYSTEM_PROMPT = """You are an IT Help Desk INTAKE GATEKEEPER, not a troubleshooter.
Your ONLY job is to decide whether a complaint has enough information to CREATE A TICKET.
Do NOT attempt to diagnose the problem. Do NOT ask troubleshooting questions.

A complaint is COMPLETE if it has ALL THREE minimum intake fields:
  1. An identifiable IT issue (login failure, slowness, data error, outage, crash, etc.)
  2. An identifiable application or system (or hardware/network reference like "laptop", "wifi")
  3. Enough description to classify the fault type (even a single descriptive word is enough)

A complaint is INCOMPLETE if and ONLY if it is MISSING one of those three fields.

CRITICAL — PROHIBITED QUESTIONS (never ask these):
  ❌ "When did you last successfully log in?"
  ❌ "Have you tried restarting or resetting your password?"
  ❌ "What error message did you see?"
  ❌ "How long has this been happening?"
  These are for the support agent AFTER ticket creation, not for the intake gate.

ALLOWED follow-up questions (only if a mandatory intake field is missing):
  ✅ "Which application or system are you referring to?" — when no system is identifiable
  ✅ "Can you describe the problem you are experiencing?" — when the issue is completely unclear

ALWAYS COMPLETE — do NOT ask follow-up for these:
  "I cannot log in to the Medical Records System." → complete
  "Travel claim rejected without any reason." → complete
  "HRMS mobile app is not syncing." → complete
  "Training feedback form is not submitting." → complete
  "Intranet crashes on mobile browser." → complete
  "Login nahi ho raha HRMS me" → complete
  "SAP login failing" → complete
  "my password is locked" → complete (password implies login system)
  "network is down" → complete
  "laptop won't turn on" → complete

INCOMPLETE ONLY when a mandatory field is missing:
  "Sir system kaam nahi kar raha" → incomplete → ask "Which application or system are you referring to?"
  "I am getting some error" → incomplete → ask "Which application are you using?"
  "it broke" → incomplete → ask "Which application or system broke?"

You MUST respond with ONLY a valid JSON object in this exact format:
{"category": "complete" | "incomplete" | "invalid", "followup_question": "<intake field question or null>", "followup_reason": "<missing_application | missing_issue | not_an_it_complaint | null>"}

Rules:
- followup_question MUST be null when category is "complete".
- followup_question MUST NOT be a diagnostic or troubleshooting question.
- "invalid" is for non-IT complaints and gibberish only (e.g. "hello", "recipe for biryani").
Do NOT include any explanation, markdown, or text outside of the JSON object."""

def analyze_complaint_category(raw_text: str, previous_question: Optional[str] = None) -> dict:
    if settings.MOCK_LLM:
        logger.info("[LLM MOCK] analyze_complaint_category called.")
        text_lower = raw_text.lower().strip()
        if text_lower in ["hello", "hi", "okay", "thanks", "yes", "no"]:
            return {"category": "invalid", "followup_question": "Please describe your IT issue.", "followup_reason": "not_an_it_complaint"}
        if len(text_lower.split()) < 4 and not any(app in text_lower for app in ["hrms", "sap", "portal", "system"]):
            if previous_question:
                return {"category": "incomplete", "followup_question": "What were you trying to do when the problem occurred, and which screen or portal were you using?", "followup_reason": "missing_application"}
            return {"category": "incomplete", "followup_question": "Which application or system are you referring to?", "followup_reason": "missing_application"}
        return {"category": "complete", "followup_question": None, "followup_reason": None}

    logger.info("[LLM] Calling vLLM to analyze complaint category.")
    try:
        if previous_question:
            # Build a context-aware user prompt that includes the prior question
            # so the LLM knows what has already been asked and must ask differently
            user_prompt = (
                f"COMPLAINT TEXT (includes previous clarification merged in):\n{raw_text}\n\n"
                f"PREVIOUS CLARIFICATION QUESTION THAT WAS ALREADY ASKED:\n{previous_question}\n\n"
                f"INSTRUCTION: If you determine the complaint is still incomplete, you MUST ask a "
                f"DIFFERENT clarification question from a completely different angle. "
                f"Do NOT repeat or rephrase the previous question. "
                f"Instead, try asking about: what screen they were on, what they were trying to do, "
                f"what error message appeared, or which specific function they were using."
            )
        else:
            user_prompt = raw_text

        raw_response = _call_llm(_CATEGORY_SYSTEM_PROMPT, user_prompt, stage_name="Complaint Category LLM")
        result = json.loads(raw_response)

        category = result.get("category", "complete")
        if category not in ["complete", "incomplete", "invalid"]:
            category = "complete"

        return {
            "category": category,
            "followup_question": result.get("followup_question"),
            "followup_reason": result.get("followup_reason")
        }
    except Exception as e:
        logger.error("[LLM] Unexpected error analyzing complaint category: %s", e)
        return {"category": "complete", "followup_question": None, "followup_reason": None}


# ===========================================================================
# PUBLIC FUNCTION 1.6: verify_and_categorize_complaint  (MERGED — performance)
# ===========================================================================
# Fuses verify_and_correct_text() + analyze_complaint_category() into ONE
# LLM call.  Enabled when settings.MERGED_VERIFY_CATEGORY = True.
# Disable flag for regression rollback.
# ===========================================================================

_VERIFY_AND_CATEGORIZE_SYSTEM_PROMPT = """You are an IT Help Desk INTAKE GATEKEEPER, not a troubleshooter.
You perform TWO tasks in a single pass. Your ONLY job is to decide whether a complaint has enough
information to CREATE A TICKET — not to diagnose the problem.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 1 — VALIDATE and CORRECT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- ACCEPT complaints in English, Hindi, or Hinglish. REJECT all other languages.
- REJECT complaints that are completely nonsensical or have zero relation to IT (e.g. "what is the capital of France", "recipe for biryani").
- CORRECT obvious STT errors (e.g. "pasword" → "password", "lok" → "locked"). Do NOT add new information.
- Short complaints ARE valid: "system slow", "login nahi ho raha" are acceptable.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 2 — INTAKE COMPLETENESS CHECK (minimum ticket fields only)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A complaint is COMPLETE if it has ALL THREE of these minimum intake fields:
  1. An identifiable IT issue (login failure, slowness, data error, outage, etc.)
  2. An identifiable application or system (or a hardware/network reference like "laptop", "wifi")
  3. Enough description to classify the fault type (even a single descriptive word is enough)

A complaint is INCOMPLETE if it is MISSING one of those three fields — and ONLY then.

CRITICAL RULES — READ BEFORE DECIDING:
❌ DO NOT ask diagnostic or troubleshooting questions. NEVER ask:
   - "When did you last successfully log in?"
   - "Have you tried restarting?"
   - "What error message did you see?"
   - "How long has this been happening?"
   These are questions for the support agent AFTER the ticket is created.

✅ You MAY only ask for MISSING INTAKE FIELDS:
   - If no application/system is named: "Which application or system are you referring to?"
   - If the issue is completely unrecognisable: "Can you describe the problem you are experiencing?"

SHORT COMPLAINTS THAT ARE ALWAYS COMPLETE (do NOT ask follow-up):
  "I cannot log in to the Medical Records System." → complete (has system + issue)
  "Travel claim rejected without any reason." → complete (has system context + issue)
  "HRMS mobile app is not syncing." → complete (has application + issue)
  "Training feedback form is not submitting." → complete (has system + issue)
  "Intranet crashes on mobile browser." → complete (has system + issue)
  "Login nahi ho raha HRMS me" → complete (has application + issue)
  "SAP login failing" → complete (has application + issue)
  "my password is locked" → complete — "password" implies login system, ask nothing
  "network is down" → complete (has system + issue)
  "laptop won't turn on" → complete (has hardware + issue)

INCOMPLETE EXAMPLES — only ask if truly missing:
  "Sir system kaam nahi kar raha" → incomplete, ask "Which application or system are you referring to?"
  "I am getting some error" → incomplete, ask "Which application are you using?"
  "it broke" → incomplete, ask "Which application or system broke?"

NEVER incomplete:
  Any complaint that names a recognisable application AND describes a recognisable IT symptom.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPONSE FORMAT — output ONLY a valid JSON object, no markdown:
{"status": "accepted" | "rejected", "corrected_text": "<corrected text or null>", "category": "complete" | "incomplete" | "invalid", "followup_question": "<intake field question or null>", "followup_reason": "<missing_application | missing_issue | not_an_it_complaint | null>"}

Rules:
- If status is "rejected" → category="invalid", put user-facing reason in followup_question.
- If status is "accepted" and category is "complete" or "incomplete" → corrected_text must be populated.
- followup_question must be null when category is "complete".
- followup_question must NEVER be a diagnostic/troubleshooting question.
Do NOT include any explanation, markdown, or text outside of the JSON object."""


def verify_and_categorize_complaint(
    raw_text: str,
    previous_question: Optional[str] = None,
) -> dict:
    """
    Single merged LLM call replacing verify_and_correct_text() + analyze_complaint_category().

    Returns a dict with keys:
      status           : "accepted" | "rejected"
      corrected_text   : str | None
      category         : "complete" | "incomplete" | "invalid"
      followup_question: str | None
      followup_reason  : str | None
    """
    # ── MOCK MODE ────────────────────────────────────────────────────────────
    if settings.MOCK_LLM:
        logger.info("[LLM MOCK] verify_and_categorize_complaint called.")
        text_lower = raw_text.lower().strip()
        NONSENSE = ["capital of", "what is", "who is", "dog ate", "weather", "recipe", "movie", "song", "cricket"]
        if any(t in text_lower for t in NONSENSE):
            return {"status": "rejected", "corrected_text": None, "category": "invalid",
                    "followup_question": "[MOCK] This does not appear to be an IT complaint.", "followup_reason": "not_an_it_complaint"}
        if text_lower in ["hello", "hi", "okay", "thanks", "yes", "no"]:
            return {"status": "rejected", "corrected_text": None, "category": "invalid",
                    "followup_question": "Please describe your IT issue.", "followup_reason": "not_an_it_complaint"}
        corrected = raw_text.strip().replace("pasword", "password").replace(" lok ", " locked ")
        if len(text_lower.split()) < 4 and not any(app in text_lower for app in ["hrms", "sap", "portal", "system", "medical", "record"]):
            fq = "What were you trying to do when the problem occurred, and which screen or portal were you using?" if previous_question else "Which application or system are you referring to?"
            return {"status": "accepted", "corrected_text": corrected, "category": "incomplete",
                    "followup_question": fq, "followup_reason": "missing_application"}
        return {"status": "accepted", "corrected_text": corrected, "category": "complete",
                "followup_question": None, "followup_reason": None}

    # ── PRODUCTION MODE ──────────────────────────────────────────────────────
    logger.info("[LLM] Calling vLLM for merged verify+categorize.")
    try:
        if previous_question:
            user_prompt = (
                f"COMPLAINT TEXT:\n{raw_text}\n\n"
                f"PREVIOUS CLARIFICATION QUESTION ALREADY ASKED:\n{previous_question}\n\n"
                f"INSTRUCTION: If you determine the complaint is still incomplete, ask a "
                f"DIFFERENT question from a completely different angle. Do NOT repeat or rephrase the previous question."
            )
        else:
            user_prompt = raw_text

        raw_response = _call_llm(
            _VERIFY_AND_CATEGORIZE_SYSTEM_PROMPT,
            user_prompt,
            stage_name="Verify+Category LLM",
        )
        result = json.loads(raw_response)

        status = result.get("status", "accepted")
        category = result.get("category", "complete")
        if category not in ["complete", "incomplete", "invalid"]:
            category = "complete"

        return {
            "status":            status,
            "corrected_text":    result.get("corrected_text") or raw_text,
            "category":          category,
            "followup_question": result.get("followup_question"),
            "followup_reason":   result.get("followup_reason"),
        }

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error("[LLM] Malformed response in verify_and_categorize_complaint: %s", e)
        # Fail open: treat as accepted+complete so a valid complaint is never blocked
        return {"status": "accepted", "corrected_text": raw_text, "category": "complete",
                "followup_question": None, "followup_reason": None}
    except Exception as e:
        logger.error("[LLM] Unexpected error in verify_and_categorize_complaint: %s", e)
        return {"status": "accepted", "corrected_text": raw_text, "category": "complete",
                "followup_question": None, "followup_reason": None}

# ===========================================================================
# PUBLIC FUNCTION 2: predict_fault_and_severity
# ===========================================================================

def _build_extract_svc_system_prompt() -> str:
    return """You are a precise data extraction assistant for an Enterprise Help Desk.
Your task is to extract the caller's service number from the given STT transcript.

Rules:
1. The service number format is exactly 3 digits followed by 1 letter (e.g. "123A", "456B", "999Z").
2. The user might use the NATO phonetic military alphabet to spell out the letter (e.g., "1 2 3 Alpha" means "123A"). You must seamlessly translate phonetic alphabets into their corresponding single letters.
3. The Speech-to-Text engine might transcribe numbers or letters in Hindi/Devanagari phonetics (e.g., "वान टू थ्री एक्स" or "Ek do teen A"). You MUST seamlessly translate these phonetic numbers and letters back into English digits and letters (e.g., "वान" -> "1", "एक्स" -> "X").
4. Ignore all conversational filler, background noise, or self-corrections. If the user corrects themselves, extract the final intended service number.
5. You must format the extracted service number exactly with NO spaces or dashes.
6. If no valid service number can be identified in the text, return null.

You MUST respond with ONLY a valid JSON object in this exact format:
{"service_number": "123A"}
OR
{"service_number": null}

Do NOT include any explanation, markdown, or text outside of the JSON object."""

def extract_service_number(raw_text: str) -> Optional[str]:
    """
    Uses the LLM to intelligently extract a service number from a raw STT transcript.
    """
    if settings.MOCK_LLM:
        logger.info("[LLM MOCK] extract_service_number called.")
        import re
        
        # Super basic mock translation for Hindi numbers for local testing
        translations = {
            "वान": "1", "टू": "2", "थ्री": "3", "फोर": "4", "फाइव": "5",
            "सिक्स": "6", "सेवन": "7", "एट": "8", "नाइन": "9", "जीरो": "0",
            "एक्स": "X", "ए": "A", "बी": "B", "सी": "C"
        }
        mock_text = raw_text
        for hindi, eng in translations.items():
            mock_text = mock_text.replace(hindi, eng)
            
        cleaned = mock_text.upper().replace(" ", "").replace("-", "")
        match = re.search(r'\d{3}[A-Z]', cleaned)
        return match.group(0) if match else None

    logger.info("[LLM] Calling vLLM to extract service number.")
    system_prompt = _build_extract_svc_system_prompt()
    try:
        raw_response = _call_llm(system_prompt, raw_text, stage_name="Service Number Extraction LLM")
        result = json.loads(raw_response)
        
        svc_no = result.get("service_number")
        if not svc_no:
            return None
            
        import re
        svc_no = str(svc_no).upper().replace(" ", "").replace("-", "")
        if re.match(r'^\d{3}[A-Z]$', svc_no):
            return svc_no
        return None
    except Exception as e:
        logger.error("[LLM] Unexpected error extracting service number: %s", e)
        return None



# ---------------------------------------------------------------------------
# Classification system prompt — built ONCE at module import and reused.
# These lists never change at runtime, so there is no reason to rebuild the
# f-string on every LLM call.
# ---------------------------------------------------------------------------
def _build_classify_system_prompt() -> str:
    """Build the classification prompt. Called once at module load."""
    fault_list = ", ".join([f'"{f}"' for f in VALID_FAULT_TYPES])
    severity_list = ", ".join([f'"{s}"' for s in VALID_SEVERITIES])
    return f"""You are an expert IT support dispatcher for an Enterprise Help Desk.

Your job is to classify a complaint text into exactly ONE fault_type and ONE severity.

VALID FAULT TYPES (choose exactly one):
{fault_list}

FAULT TYPE DEFINITIONS:
- "login/access": Cannot log in, password issues, account locked, OTP not working, SSO failure, access denied.
- "performance/slow": Application is slow, lagging, timing out, hanging, loading forever.
- "data error": Wrong data displayed, incorrect figures, salary mismatch, record not found, data corruption.
- "total outage": Application completely down, server unreachable, 404/500 errors, no one can access.
- "partial/degraded": Some features work but others are broken, partial functionality, specific page/button not working.
- "other": Does not clearly fit into any of the above categories.

VALID SEVERITIES (choose exactly one):
{severity_list}

SEVERITY DEFINITIONS:
- "critical": Entire base or mission-critical systems are down, many users affected, operational impact.
  Keywords: "sab ke liye", "poora base", "nobody can", "all users", "emergency", "mission", "urgent"
- "high": An important workflow is broken for multiple users or a team.
  Keywords: "team", "hamare sab", "everyone in my unit", "many users", "multiple people"
- "normal": A single user has a routine issue with one system.
  This is the DEFAULT — use when no clear indicator of critical/high/low is present.
- "low": Minor cosmetic or non-blocking issue.
  Keywords: "cosmetic", "minor", "spelling", "colour", "UI", "not important", "whenever possible"

IMPORTANT RULES:
- If the complaint is in Hindi or Hinglish, still classify it correctly.
- If you are not sure about severity, default to "normal".
- If you are not sure about fault_type, default to "other".
- Never return a fault_type or severity outside the valid lists.

FEW-SHOT EXAMPLES:
  "my password is locked and I cannot log in" → {{"fault_type": "login/access", "severity": "normal"}}
  "login nahi ho raha mujhe" → {{"fault_type": "login/access", "severity": "normal"}}
  "the payroll system is down for everyone on base" → {{"fault_type": "total outage", "severity": "critical"}}
  "poora AFMS system band ho gaya hai" → {{"fault_type": "total outage", "severity": "critical"}}
  "system bahut slow chal raha hai" → {{"fault_type": "performance/slow", "severity": "normal"}}
  "meri salary mismatch hai, wrong amount show ho raha" → {{"fault_type": "data error", "severity": "normal"}}
  "the submit button on the leave portal is not working" → {{"fault_type": "partial/degraded", "severity": "normal"}}
  "network is very slow for entire squadron" → {{"fault_type": "performance/slow", "severity": "high"}}
  "minor spelling error on the dashboard" → {{"fault_type": "partial/degraded", "severity": "low"}}

You MUST respond with ONLY a valid JSON object in this exact format:
{{"fault_type": "<one of the valid fault types>", "severity": "<one of the valid severities>"}}

Do NOT include any explanation, markdown, or text outside of the JSON object."""


# Module-level cached prompt — built exactly once.
_CLASSIFY_SYSTEM_PROMPT: str = _build_classify_system_prompt()



def predict_fault_and_severity(complaint_text: str) -> dict:
    """
    Uses the LLM to predict fault_type and severity for a complaint.

    Returns a dict with this shape:
      {"fault_type": "login/access", "severity": "normal"}
    """
    # ── MOCK MODE ────────────────────────────────────────────────────────────
    if settings.MOCK_LLM:
        logger.info("[LLM MOCK] predict_fault_and_severity called — returning mock response.")
        text_lower = complaint_text.lower()

        # Simple keyword matching to make the mock somewhat realistic
        fault_type = "other"
        if any(w in text_lower for w in ["login", "password", "access", "sso", "lock", "otp"]):
            fault_type = "login/access"
        elif any(w in text_lower for w in ["slow", "hang", "timeout", "loading", "lagging"]):
            fault_type = "performance/slow"
        elif any(w in text_lower for w in ["wrong", "incorrect", "mismatch", "data", "salary", "balance"]):
            fault_type = "data error"
        elif any(w in text_lower for w in ["down", "not opening", "unreachable", "crash"]):
            fault_type = "total outage"
        elif any(w in text_lower for w in ["some", "partial", "page", "button"]):
            fault_type = "partial/degraded"

        severity = "normal"
        if any(w in text_lower for w in ["emergency", "critical", "mission", "urgent", "all users"]):
            severity = "critical"
        elif any(w in text_lower for w in ["many", "everyone", "team", "all", "multiple"]):
            severity = "high"
        elif any(w in text_lower for w in ["cosmetic", "minor", "spelling", "ui", "colour"]):
            severity = "low"

        return {"fault_type": fault_type, "severity": severity}

    # ── PRODUCTION MODE ──────────────────────────────────────────────────────
    logger.info("[LLM] Calling vLLM to classify fault_type and severity.")
    try:
        raw_response = _call_llm(_CLASSIFY_SYSTEM_PROMPT, complaint_text, stage_name="Fault Classification LLM")
        result = json.loads(raw_response)

        # Validate the response values are from the allowed sets
        fault_type = result.get("fault_type", "other")
        severity = result.get("severity", "normal")

        if fault_type not in VALID_FAULT_TYPES:
            logger.warning("[LLM] Invalid fault_type returned '%s'. Defaulting to 'other'.", fault_type)
            fault_type = "other"
        if severity not in VALID_SEVERITIES:
            logger.warning("[LLM] Invalid severity returned '%s'. Defaulting to 'normal'.", severity)
            severity = "normal"

        return {"fault_type": fault_type, "severity": severity}

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error("[LLM] Malformed response from vLLM during classification: %s", e)
        return {"fault_type": "other", "severity": "normal"}
    except Exception as e:
        logger.error("[LLM] Unexpected error calling vLLM for classification: %s", e)
        return {"fault_type": "other", "severity": "normal"}


# ===========================================================================
# PUBLIC FUNCTION 3: classify_and_reason (context-aware single LLM call)
# ===========================================================================

_CLASSIFY_AND_REASON_SYSTEM_PROMPT = """You are an expert IT support engineer and dispatcher for an Enterprise Help Desk.

Your job is to classify incoming IT complaints with precision and intellectual honesty.
Treat retrieved applications as hypotheses generated by semantic search, not as confirmed answers. Retrieval provides evidence, not proof. A highly ranked candidate should increase your confidence only when the complaint itself supports that conclusion.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO USE RETRIEVED APPLICATION CANDIDATES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The CANDIDATE HYPOTHESES section lists applications retrieved by SEMANTIC SIMILARITY to the complaint.
They are HYPOTHESES, not answers. Treat them as suggestions to evaluate, not as confirmation.

CRITICAL: A high retrieval score does NOT mean the application is correct.
Semantic search finds applications that share vocabulary with the complaint — but a vague complaint
like "nothing loads" matches many applications. A high-scoring candidate should only increase your
confidence if the complaint text itself provides corroborating detail (e.g., the user named the
application, described a specific action, or mentioned a feature unique to that application).

Do NOT let retrieved candidates substitute for a clear complaint.
If the complaint is vague, it remains vague even if retrieval returns a high-confidence match.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VALID FAULT TYPES (choose exactly one)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"login/access"     — Cannot log in, password issues, account locked, OTP not working, SSO failure, access denied.
"performance/slow" — Application is slow, lagging, timing out, hanging, loading forever.
"data error"       — Wrong data displayed, incorrect figures, salary mismatch, record not found, data corruption.
"total outage"     — Application completely down, server unreachable, 404/500 errors, no one can access.
"partial/degraded" — Some features work, others broken; specific page or button not working.
"other"            — Does not clearly fit into any of the above categories.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VALID SEVERITIES (choose exactly one)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"critical" — Entire base or mission-critical systems are down; many users affected.
"high"     — An important workflow is broken for multiple users or a team.
"normal"   — A single user has a routine issue. DEFAULT when unclear.
"low"      — Minor cosmetic or non-blocking issue.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FIELD DEFINITIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- fault_type: One of the valid fault types above.

- severity: One of the valid severities above. Default to \"normal\" when unclear.

- confidence:
  A float 0.0–1.0 representing how certain you are of your fault_type and severity classification.
  Base confidence on the COMPLAINT TEXT, not on retrieval scores.
  Be conservative. Use 0.4–0.55 for genuinely vague complaints.
  Use 0.7–0.9 only when the complaint is specific and candidates strongly corroborate it.

- suggested_resolution:
  A concrete first-response action drawn from candidate symptoms and purposes.
  If the complaint is too vague to suggest a specific action, suggest asking for more detail first.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FEW-SHOT EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

--- CLEAR COMPLAINT ---
Complaint: "I cannot log into the AFMS portal, my password is locked."
Result: {"fault_type": "login/access", "severity": "normal", "confidence": 0.92, "suggested_resolution": "Reset the user account password via the SSO admin console and verify OTP delivery."}

--- HINGLISH ---
Complaint: "Login nahi ho raha mujhe AFMS portal mein, password lock ho gaya."
Result: {"fault_type": "login/access", "severity": "normal", "confidence": 0.89, "suggested_resolution": "Reset account credentials via the SSO admin panel and verify OTP is being sent to the correct number."}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINAL RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Never inflate confidence because a candidate was retrieved — retrieval is a hint, not a fact.
- If the complaint is in Hindi or Hinglish, apply the same standards.
- Keep suggested_resolution short and actionable.

RESPONSE FORMAT — output ONLY a valid JSON object. No markdown, no explanation, no extra text:
{"fault_type": "...", "severity": "...", "confidence": 0.0, "suggested_resolution": "..."}"""



def _build_reasoning_user_prompt(
    complaint_text: str,
    candidate_apps: list,
    symptoms: dict,
    purposes: dict,
) -> str:
    """Assemble the user-turn message injecting retrieved context compactly.

    The section header is deliberately labelled CANDIDATE HYPOTHESES to reinforce
    the system-prompt framing: retrieved applications are possibilities to evaluate,
    not authoritative answers. The retrieval score is preserved so the LLM can see
    how confident the search engine was, but the system prompt instructs it not to
    let that score substitute for clarity in the complaint text itself.

    Additionally, if the complaint text explicitly names one of the candidate
    applications, that fact is surfaced as a high-priority note so the LLM ties
    the suggested_resolution to the correct application.
    """
    word_count = len(complaint_text.split())
    text_lower = complaint_text.lower()

    # Apply config-driven prompt size limits
    max_candidates = getattr(settings, "CLASSIFY_MAX_CANDIDATES", 3)
    max_desc_chars = getattr(settings, "CLASSIFY_MAX_DESC_CHARS", 120)

    lines = [
        f"COMPLAINT:\n{complaint_text}",
        f"(complaint word count: {word_count})",
        "",
    ]

    # ── Explicit name detection ───────────────────────────────────────────────
    explicitly_named = [
        app for app in candidate_apps
        if app.get("application_name", "").lower() in text_lower
    ]
    if explicitly_named:
        named_app = explicitly_named[0].get("application_name", "")
        lines.append(
            f"⚠ EXPLICIT APPLICATION MENTION DETECTED: The complaint text directly names "
            f"'{named_app}'. Your suggested_resolution MUST be specific to this application. "
            f"Do NOT generate a generic resolution."
        )
        lines.append("")

    if candidate_apps:
        lines.append(
            "CANDIDATE HYPOTHESES — applications retrieved by semantic similarity."
        )
        lines.append(
            "Evaluate each against the complaint. Do not assume the top result is correct."
        )
        for i, app in enumerate(candidate_apps[:max_candidates], 1):
            name = app.get("application_name", app.get("name", "Unknown"))
            score = app.get("confidence_score", 0.0)
            app_id = app.get("application_id")
            line = f"  {i}. {name} (retrieval score: {score:.2f})"

            syms = symptoms.get(app_id, [])
            if syms:
                # Truncate each symptom to max_desc_chars to control token count
                sym_text = "; ".join(s[:max_desc_chars] for s in syms[:3])
                line += f"\n     Known symptoms: {sym_text}"

            purps = purposes.get(app_id, [])
            if purps:
                line += f"\n     Application purpose: {purps[0][:max_desc_chars]}"

            lines.append(line)
    else:
        lines.append("CANDIDATE HYPOTHESES: None found. Classify based on complaint text alone.")

    return "\n".join(lines)


def classify_and_reason(
    complaint_text: str,
    candidate_apps: list,
    symptoms: dict,
    purposes: dict,
) -> dict:
    """
    Context-aware classification + reasoning in a single LLM inference.

    Args:
        complaint_text: The corrected STT transcript.
        candidate_apps:  List of dicts [{application_id, application_name, confidence_score}, ...]
                         already enriched and sorted by search_candidates().
        symptoms:        Dict {app_id: [symptom_text, ...]} for the top candidates.
        purposes:        Dict {app_id: [purpose_text, ...]} for the top candidates.

    Returns a dict with keys:
        fault_type, severity, confidence, suggested_resolution
    """
    _FALLBACK = {
        "fault_type": "other",
        "severity": "normal",
        "confidence": 0.5,
        "suggested_resolution": "",
    }

    # ── MOCK MODE ────────────────────────────────────────────────────────────
    if settings.MOCK_LLM:
        logger.info("[LLM MOCK] classify_and_reason called — returning mock response.")
        base = predict_fault_and_severity(complaint_text)  # reuse existing mock logic
        text_lower = complaint_text.lower()
        confidence = 0.85
        if any(w in text_lower for w in ["not sure", "unclear", "maybe", "don't know"]):
            confidence = 0.45
        primary_app = candidate_apps[0].get("application_name", "the application") if candidate_apps else "the application"
        return {
            "fault_type": base["fault_type"],
            "severity": base["severity"],
            "confidence": confidence,
            "suggested_resolution": f"[MOCK] Escalate to the {primary_app} support team and verify system status.",
        }

    # ── PRODUCTION MODE ──────────────────────────────────────────────────────
    logger.info("[LLM] Calling vLLM for context-aware classify+reason.")
    user_prompt = _build_reasoning_user_prompt(complaint_text, candidate_apps, symptoms, purposes)
    try:
        raw_response = _call_llm(
            _CLASSIFY_AND_REASON_SYSTEM_PROMPT,
            user_prompt,
            temperature=0.1,
            stage_name="Classify+Reason LLM",
        )
        result = json.loads(raw_response)

        # Validate + sanitise each field
        fault_type = result.get("fault_type", "other")
        severity   = result.get("severity", "normal")
        if fault_type not in VALID_FAULT_TYPES:
            logger.warning("[LLM] classify_and_reason: invalid fault_type '%s', defaulting.", fault_type)
            fault_type = "other"
        if severity not in VALID_SEVERITIES:
            logger.warning("[LLM] classify_and_reason: invalid severity '%s', defaulting.", severity)
            severity = "normal"

        try:
            confidence = float(result.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.5

        return {
            "fault_type": fault_type,
            "severity": severity,
            "confidence": confidence,
            "suggested_resolution": str(result.get("suggested_resolution", "")),
        }

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error("[LLM] classify_and_reason: malformed response: %s", e)
        return _FALLBACK
    except Exception as e:
        logger.error("[LLM] classify_and_reason: unexpected error: %s", e)
        return _FALLBACK

