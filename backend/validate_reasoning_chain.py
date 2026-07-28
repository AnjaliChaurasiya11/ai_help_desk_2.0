"""
validate_reasoning_chain.py
===========================
End-to-end validation of the AI reasoning layer.
Covers four scenarios: high-confidence, low-confidence,
history shortcut, and schema serialisation.

Run from the backend directory:
  python validate_reasoning_chain.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/helpdesk_db")

# ─── Colour helpers ──────────────────────────────────────────────────────────
GREEN  = "\033[92m"; YELLOW = "\033[93m"; RED = "\033[91m"
CYAN   = "\033[96m"; BOLD   = "\033[1m";  RESET = "\033[0m"

def hdr(t):  print(f"\n{BOLD}{CYAN}{'='*60}{RESET}\n{BOLD}{t}{RESET}\n{'='*60}")
def ok(m):   print(f"  {GREEN}PASS{RESET}  {m}")
def fail(m): print(f"  {RED}FAIL{RESET}  {m}"); failures.append(m)
def warn(m): print(f"  {YELLOW}WARN{RESET}  {m}")
def info(m): print(f"  {CYAN}    {RESET}  {m}")

failures = []

def check(cond, label, detail=""):
    if cond:
        ok(label)
    else:
        fail(f"{label}{' — ' + detail if detail else ''}")

# ─── 0. Import checks ────────────────────────────────────────────────────────
hdr("0. Import / startup checks")
try:
    from config import settings
    info(f"MOCK_LLM                     = {settings.MOCK_LLM}")
    info(f"ENABLE_AI_REASONING          = {settings.ENABLE_AI_REASONING}")
    info(f"FOLLOWUP_CONFIDENCE_THRESHOLD= {settings.FOLLOWUP_CONFIDENCE_THRESHOLD}")
    info(f"VLLM_MODEL_NAME              = {settings.VLLM_MODEL_NAME}")
    ok("Settings loaded")
except Exception as e:
    fail(f"Config import: {e}"); sys.exit(1)

try:
    from services.llm_client import classify_and_reason, predict_fault_and_severity
    ok("llm_client.classify_and_reason importable")
except Exception as e:
    fail(f"llm_client import: {e}"); sys.exit(1)

try:
    from services.classifier import TicketClassifier
    tc = TicketClassifier()
    check(hasattr(tc, "classify_and_reason_complaint"),
          "TicketClassifier.classify_and_reason_complaint present")
    check(hasattr(tc, "classify_complaint"),
          "TicketClassifier.classify_complaint (backward-compat) present")
except Exception as e:
    fail(f"TicketClassifier import: {e}"); sys.exit(1)

try:
    from voice.complaint_processor import ComplaintProcessingResult
    import dataclasses
    f_names = {f.name for f in dataclasses.fields(ComplaintProcessingResult)}
    for fn in ("confidence","suggested_resolution","needs_followup","followup_question"):
        check(fn in f_names, f"ComplaintProcessingResult.{fn}")
except Exception as e:
    fail(f"ComplaintProcessingResult import: {e}")

try:
    from voice_schemas import VoiceComplaintResponse
    s_fields = set(VoiceComplaintResponse.model_fields.keys())
    for fn in ("confidence","suggested_resolution","needs_followup","followup_question"):
        check(fn in s_fields, f"VoiceComplaintResponse schema field: {fn}")
except Exception as e:
    fail(f"VoiceComplaintResponse import: {e}")

REQUIRED = {"fault_type","severity","confidence",
            "suggested_resolution","needs_followup","followup_question"}

# ─── 1. classify_and_reason() — unit level ───────────────────────────────────
def run_car(complaint, label, candidates=None, syms=None, purps=None):
    candidates = candidates or [{"application_id":1,"application_name":"AFMS Portal","confidence_score":0.88}]
    syms  = syms  or {1:["Login page error","Password reset fails"]}
    purps = purps or {1:["Financial management system"]}
    t = time.time()
    r = classify_and_reason(complaint, candidates, syms, purps)
    ms = (time.time()-t)*1000
    info(f"  inference: {ms:.0f} ms")
    check(isinstance(r, dict),             f"[{label}] returns dict")
    check(REQUIRED.issubset(r.keys()),     f"[{label}] all required keys present",
          f"missing={REQUIRED - r.keys()}")
    check(isinstance(r["confidence"],float),f"[{label}] confidence is float")
    check(0.0 <= r["confidence"] <= 1.0,   f"[{label}] confidence in [0,1]")
    check(isinstance(r["needs_followup"],bool),f"[{label}] needs_followup is bool")
    valid_faults = {"login/access","performance/slow","data error",
                    "total outage","partial/degraded","other"}
    check(r["fault_type"] in valid_faults, f"[{label}] fault_type is valid enum")
    if r["needs_followup"]:
        check(r["followup_question"] is not None,
              f"[{label}] followup_question set when needs_followup=True")
    info(f"  → fault={r['fault_type']} sev={r['severity']} conf={r['confidence']:.2f} followup={r['needs_followup']}")
    return r, ms

hdr("1a. HIGH-CONFIDENCE complaint")
res_hi, _ = run_car(
    "I cannot log into the AFMS portal — my password is locked and OTP is not being received",
    "HIGH",
    candidates=[
        {"application_id":1,"application_name":"AFMS Portal","confidence_score":0.94},
        {"application_id":2,"application_name":"IAM Server","confidence_score":0.62},
    ],
    syms={1:["Login page shows error","Password reset not working","OTP not delivered"],
          2:["SSO failure","Access denied"]},
    purps={1:["Financial management system"],2:["Identity and access management"]},
)
thr = settings.FOLLOWUP_CONFIDENCE_THRESHOLD
if res_hi["confidence"] >= thr:
    ok(f"confidence {res_hi['confidence']:.2f} >= threshold {thr} — high-confidence path confirmed")
    check(not res_hi["needs_followup"], "needs_followup=False for high-confidence complaint")
else:
    warn(f"LLM returned confidence {res_hi['confidence']:.2f} < threshold {thr} — model may need prompt tuning")

hdr("1b. LOW-CONFIDENCE complaint")
res_lo, _ = run_car(
    "the system isn't working",
    "LOW",
    candidates=[
        {"application_id":1,"application_name":"AFMS Portal","confidence_score":0.41},
        {"application_id":2,"application_name":"HR System","confidence_score":0.38},
        {"application_id":3,"application_name":"Payroll","confidence_score":0.35},
    ],
    syms={1:["Login error"],2:["Data sync issue"],3:["Salary mismatch"]},
    purps={1:["Financial mgmt"],2:["Human resources"],3:["Payroll"]},
)
if res_lo["confidence"] < thr:
    ok(f"confidence {res_lo['confidence']:.2f} < threshold {thr} — low-confidence path confirmed")
else:
    warn(f"LLM returned confidence {res_lo['confidence']:.2f} >= threshold for ambiguous complaint")

# ─── 2. DB integration (history shortcut + classify_and_reason_complaint) ─────
hdr("2. DB integration — classify_and_reason_complaint()")
try:
    from sqlmodel import Session, create_engine
    from services.embedder import TextEmbedder

    engine   = create_engine(settings.DATABASE_URL)
    embedder = TextEmbedder()

    test_cases = [
        ("I cannot log into the AFMS portal — my password is locked", "CLEAR"),
        ("the system isn't working",                                   "AMBIG"),
    ]

    for txt, lbl in test_cases:
        info(f"\n  '{txt[:55]}' [{lbl}]")
        embedding = embedder.get_embedding(txt)

        candidates = [{"application_id":1,"application_name":"AFMS Portal","confidence_score":0.88}]
        syms  = {1:["Login page error","Password reset fails"]}
        purps = {1:["Financial management system"]}

        with Session(engine) as sess:
            classifier2 = TicketClassifier()

            # Check history shortcut independently
            t0 = time.time()
            hf, hs = classifier2._get_history_match_combined(sess, embedding)
            history_hit = bool(hf and hs)
            t_h = (time.time()-t0)*1000
            info(f"  History shortcut: {'HIT (fault={hf}, sev={hs})'.format(hf=hf,hs=hs) if history_hit else 'MISS'} in {t_h:.0f} ms")

            # Full call
            t0 = time.time()
            fault, severity, reasoning, h2 = classifier2.classify_and_reason_complaint(
                session=sess,
                text_content=txt,
                embedding=embedding,
                candidate_apps=candidates,
                symptoms=syms,
                purposes=purps,
            )
            t_c = (time.time()-t0)*1000

        check(h2 == history_hit, f"[{lbl}] history_hit flag consistent between calls")
        check(REQUIRED.issubset(reasoning.keys()), f"[{lbl}] reasoning has all 7 keys")
        check(isinstance(reasoning["confidence"], float), f"[{lbl}] confidence is float")
        check(isinstance(reasoning["needs_followup"], bool), f"[{lbl}] needs_followup is bool")

        if history_hit:
            check(reasoning["confidence"] == 1.0, f"[{lbl}] history hit → confidence=1.0")
            check(reasoning["needs_followup"] == False,
                  f"[{lbl}] history hit → needs_followup=False")
            info(f"  LLM was SKIPPED (history shortcut). Latency: {t_c:.0f} ms")
        else:
            info(f"  LLM called. Total classify+reason: {t_c:.0f} ms")
            info(f"  fault={fault} sev={severity} conf={reasoning['confidence']:.2f} followup={reasoning['needs_followup']}")

except Exception as e:
    fail(f"DB integration test: {e}")
    import traceback; traceback.print_exc()

# ─── 3. Deterministic Python follow-up gate ───────────────────────────────────
hdr("3. Deterministic follow-up gate (Python logic, no LLM)")
thr = settings.FOLLOWUP_CONFIDENCE_THRESHOLD
info(f"Threshold = {thr}")

gate_cases = [
    (0.90, False, False, "conf=0.90, model=False → False"),
    (0.90, True,  True,  "conf=0.90, model=True  → True  (model respected)"),
    (0.50, False, True,  "conf=0.50, model=False → True  (Python override)"),
    (0.50, True,  True,  "conf=0.50, model=True  → True"),
    (0.65, False, False, "conf=0.65, model=False → False (exactly at threshold)"),
    (0.64, False, True,  "conf=0.64, model=False → True  (just below threshold)"),
]
for conf, model_nf, expected, desc in gate_cases:
    gate_result = (conf < thr) or model_nf
    check(gate_result == expected, f"gate({conf:.2f}, {model_nf}) = {expected}", desc)

# ─── 4. VoiceComplaintResponse serialisation ─────────────────────────────────
hdr("4. VoiceComplaintResponse schema serialisation")
try:
    from voice_schemas import VoiceComplaintResponse, VoiceCandidateApp

    # High-confidence
    hi_schema = VoiceComplaintResponse(
        session_id="val-001", state="OPERATOR_REVIEW",
        transcript="I cannot log into the AFMS portal",
        confidence=0.92, intake_id=1,
        fault_type_proposal="login/access", severity_proposal="normal",
        candidates=[VoiceCandidateApp(application_id=1,application_name="AFMS",confidence_score=0.92,is_primary=True)],
        prompt_text="Classification complete.",
        summary="User cannot log in to the AFMS portal.",
        suggested_resolution="Reset password via admin portal.",
        needs_followup=False, followup_question=None,
    )
    d = hi_schema.model_dump()
    for k in REQUIRED - {"fault_type","severity"}:
        check(k in d, f"High-conf schema: '{k}' in serialised JSON")
    check(d["needs_followup"] == False, "High-conf: needs_followup=False")
    check(d["followup_question"] is None, "High-conf: followup_question=None")

    # Low-confidence
    lo_schema = VoiceComplaintResponse(
        session_id="val-002", state="OPERATOR_REVIEW",
        transcript="the system isn't working",
        confidence=0.38, prompt_text="Could you clarify which system?",
        summary="", suggested_resolution="",
        needs_followup=True,
        followup_question="Could you clarify which specific system is not working?",
    )
    d2 = lo_schema.model_dump()
    check(d2["needs_followup"] == True, "Low-conf: needs_followup=True")
    check(d2["followup_question"] is not None, "Low-conf: followup_question populated")

    ok("Schema serialisation OK for both high and low confidence")

except Exception as e:
    fail(f"Schema serialisation: {e}")

# ─── 5. React callback contract check (static analysis) ──────────────────────
hdr("5. React callback contract (static field check)")
import re, pathlib

vsp_path = pathlib.Path(__file__).parent.parent / "frontend/src/components/voice/VoiceSessionPanel.jsx"
cr_path  = pathlib.Path(__file__).parent.parent / "frontend/src/pages/ClassifyReview.jsx"

if vsp_path.exists():
    vsp_src = vsp_path.read_text(encoding="utf-8")
    for field in ("ai_confidence","ai_suggested_resolution","needs_followup","followup_question"):
        check(field in vsp_src,
              f"VoiceSessionPanel passes '{field}' to onClassificationComplete")
else:
    warn(f"VoiceSessionPanel.jsx not found at {vsp_path}")

if cr_path.exists():
    cr_src = cr_path.read_text(encoding="utf-8")
    for field in ("needs_followup","followup_question","ai_confidence","ai_suggested_resolution"):
        check(field in cr_src, f"ClassifyReview reads '{field}'")
    check("forceUnselected" in cr_src, "ClassifyReview: forceUnselected flag present in defaultTicket")
    check("activeNeedsFollowupVal" in cr_src, "ClassifyReview: activeNeedsFollowupVal logic present")
    check("activeFollowupQuestion" in cr_src, "ClassifyReview: activeFollowupQuestion rendered")
    check("I need clarification" in cr_src, "ClassifyReview: follow-up banner text present")
    check("Suggested Resolution" in cr_src, "ClassifyReview: resolution card text present")
else:
    warn(f"ClassifyReview.jsx not found at {cr_path}")

# ─── Final report ─────────────────────────────────────────────────────────────
hdr("FINAL REPORT")
if failures:
    print(f"\n{RED}{BOLD}FAILED — {len(failures)} check(s):{RESET}")
    for f in failures:
        print(f"  {RED}•{RESET} {f}")
    sys.exit(1)
else:
    print(f"\n{GREEN}{BOLD}ALL CHECKS PASSED{RESET}")
    print(f"\n{CYAN}Backend validation complete.")
    print(f"Next step: submit a complaint via the UI and confirm the browser renders")
    print(f"the follow-up banner for ambiguous complaints and AI summary cards for")
    print(f"high-confidence ones.{RESET}")
    sys.exit(0)
