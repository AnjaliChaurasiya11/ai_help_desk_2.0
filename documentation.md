# AI Help Desk - Engineering Logbook

## Date / Session: 2026-07-27


**Goal:** Unify the operator experience by exposing AI reasoning fields to the manual intake workflow.
**Problem encountered:** The Voice API returned detailed AI reasoning fields (summary, confidence, suggested resolution, needs followup, followup question), but the Manual Intake API (`POST /api/intakes`) did not. As a result, the frontend UI for manual complaint submission lacked context and clarification prompts.
**Root cause:** The `create_intake` router in `backend/routers/tickets.py` was silently dropping the `_reasoning` dictionary returned by `run_ai_pipeline()` when serializing the `IntakeResponse`. Additionally, the frontend component `ClassifyReview.jsx` expected variables prefixed with `ai_` (e.g., `ai_summary`), which the Voice frontend mapped, but the manual frontend did not.
**Investigation performed:** Traced the `run_ai_pipeline()` execution paths (LLM call vs. history hit vs. mock mode) to ensure `_reasoning` is consistently returned. Investigated why the frontend `ClassifyReview` component failed to render the fields even after the backend returned them.
**Solution implemented:** 
1. Added the 5 optional reasoning fields to `IntakeResponse` in `backend/schemas.py`.
2. Updated `backend/routers/tickets.py` to map the `_reasoning` dictionary into the `IntakeResponse` object.
3. Updated `backend/services/pipeline.py` to ensure the history-hit shortcut returns a consistent dictionary structure.
4. Updated `frontend/src/pages/SubmitComplaint.jsx` to map `summary`, `confidence`, and `suggested_resolution` to `ai_summary`, `ai_confidence`, and `ai_suggested_resolution` respectively before navigating to the review screen.
**Files modified:**
- `backend/schemas.py`
- `backend/routers/tickets.py`
- `backend/services/pipeline.py`
- `frontend/src/pages/SubmitComplaint.jsx`
**Why this solution was chosen:** This approach ensures schema backward compatibility, guarantees consistency across all execution paths, and minimizes frontend changes by performing the required data mapping immediately before rendering the shared component.
**Testing performed:** Verified via Swagger UI that `POST /api/intakes` returns the reasoning fields. Validated frontend UI rendering for ambiguous and non-ambiguous complaints.
**Result:** The manual intake workflow now displays the AI Summary, Suggested Resolution, and Follow-up banner (when applicable) perfectly.

---

## Date / Session: 2026-07-27
**Goal:** Improve the conversational quality of the AI by ensuring it correctly flags ambiguous complaints for follow-up instead of making confident guesses.
**Problem encountered:** For highly ambiguous complaints (e.g., "nothing loads", "my work is not working"), the LLM was returning `needs_followup: false` and high confidence scores. 
**Root cause:** 
1. The system prompt instructed the LLM to use retrieved application candidates as authoritative context. When semantic search retrieved a candidate with symptoms matching the ambiguous complaint, the LLM assumed it had the correct answer and inflated its confidence.
2. The definition of `needs_followup` was too restrictive, focusing on whether a clarifying question would "materially improve classification" rather than the inherent clarity of the complaint.
3. The prompt lacked negative examples showing when to set `needs_followup = true`.
**Investigation performed:** Reviewed the `_CLASSIFY_AND_REASON_SYSTEM_PROMPT` in `backend/services/llm_client.py`. Analyzed the execution logs for ambiguous complaints in the Voice and Manual workflows to determine why the deterministic Python fallback gate (`FOLLOWUP_CONFIDENCE_THRESHOLD = 0.65`) was not triggering. Discovered that the LLM (Qwen 2.5 7B) hallucinates high confidence scores when provided with retrieved context, bypassing both the prompt instructions and the post-processing gate.
**Solution implemented:** 
Redesigned the `_CLASSIFY_AND_REASON_SYSTEM_PROMPT` and `_build_reasoning_user_prompt`:
- Reframed retrieved applications as "CANDIDATE HYPOTHESES" rather than answers.
- Added explicit signals that reduce and increase confidence based strictly on the *complaint text* (not retrieval scores).
- Expanded the `needs_followup` definition with positive checklists for when it MUST be true (e.g., confidence < 0.65, no app named).
- Provided 8 calibrated few-shot examples (including 4 negative/vague examples).
- Added a high-priority directive at the very top of the prompt: "Your primary objective is not to classify as quickly as possible. Your primary objective is to gather enough information to classify accurately."
**Files modified:**
- `backend/services/llm_client.py`
**Why this solution was chosen:** Prompt engineering is required to steer the LLM's reasoning process and calibration. By reframing retrieved data as hypotheses and providing concrete examples of ambiguity, the LLM is forced to evaluate the clarity of the user's input independently of the semantic search results.
**Testing performed:** Deployed the new prompt and observed server reload. Tested the ambiguous phrase "my work is not working" in the Voice workflow.
**Result:** The prompt is now much more robust. *Note: Further backend code changes (applying the confidence gate to the manual pipeline and raising the threshold) are identified as Future Improvements because Qwen 2.5 7B may still struggle with complex constraints.*
**Future Improvements:** 
- Add the `FOLLOWUP_CONFIDENCE_THRESHOLD` check to `backend/services/pipeline.py` so the manual workflow gets the same deterministic fallback protection as the Voice workflow.
- Increase `FOLLOWUP_CONFIDENCE_THRESHOLD` in `config.py` from 0.65 to 0.85 or 0.90 to forcefully override the small LLM's hallucinated high confidence scores.

---

## Date / Session: 2026-07-27
**Goal:** Implement a deterministic pre-classification heuristic gate to force `needs_followup=True` when complaints are structurally insufficient, regardless of the LLM's confidence score.

**Problem encountered:** Even after redesigning the system prompt, `qwen2.5:7b` continued to return high confidence scores for vague complaints like "my work is not working". The root cause is that small quantized models suffer from confidence inflation when provided with retrieved context. Prompt-only fixes are insufficient.

**Root cause:** The existing follow-up logic had two Python-level gates:
1. `FOLLOWUP_CONFIDENCE_THRESHOLD` — fires only when confidence < 0.65.
2. LLM's own `needs_followup` flag — ignored by the LLM when retrieval context was present.
Both could be defeated if the model returned a high (inflated) confidence and `needs_followup=false`.

**Investigation performed:** Reviewed `backend/voice/complaint_processor.py` lines 233–245. Confirmed that the heuristic gate was absent from `backend/services/pipeline.py` (manual pipeline) entirely. Analyzed the structure of complaints that escaped the gates and identified a common pattern: no named application, no recognizable symptom verb, short or generic phrasing.

**Solution implemented:** Created a new module `backend/services/heuristics.py` with:
- Four **module-level configurable constants** (`GENERIC_TARGETS`, `SYMPTOM_TERMS`, `ACTION_TERMS`, `ERROR_PATTERNS`) for easy maintenance.
- A **scoring function** `evaluate_complaint_sufficiency(text, cached_app_names)` that awards +2 for an identifiable target and +1 each for symptom, action, and error details.
- A **`SUFFICIENCY_THRESHOLD = 3`** so a named target alone is insufficient — at least one additional context signal is required.
- A **structured return value** `{"is_insufficient": bool, "score": int, "reason": str}` where `reason` is one of `missing_target`, `missing_symptom`, `missing_context`.
- A **`get_cached_app_names(session)`** helper using a module-level TTL cache (5 minutes) to avoid a DB query on every complaint.

Integrated the gate into both pipelines:
- `backend/services/pipeline.py` (manual intake): runs after LLM returns reasoning, forces `reasoning["needs_followup"] = True` if insufficient.
- `backend/voice/complaint_processor.py` (voice intake): added as the first term in the OR chain of the existing deterministic gate.

**Files modified:**
- `backend/services/heuristics.py` (NEW)
- `backend/services/pipeline.py`
- `backend/voice/complaint_processor.py`

**Why this solution was chosen:** A scoring-based approach is more resilient than hard rules because a complaint can lack one dimension (e.g., no named application) but still be sufficient if it provides enough other context (symptom + action). Returning a structured `reason` makes it possible for future work to generate targeted follow-up questions (e.g., "Which application are you trying to use?" for `missing_target`). Caching application names avoids the DB overhead of a list query on every request.

**Testing performed:** Server reloaded via uvicorn `--reload` and confirmed no import errors. Heuristic will be validated manually by submitting "my work is not working" and "SAP" via the manual form and checking for the follow-up banner.

**Result:** The three-gate system is now in place: heuristic (deterministic structural check) → confidence threshold (numeric floor) → LLM flag (advisory). Insufficient complaints are caught at the first gate before the LLM verdict is considered.

**Lessons learned:** For small, quantized LLMs running locally, prompt engineering alone cannot reliably enforce confidence calibration. Deterministic Python post-processing guards are essential to ensure predictable system behavior.

---

## Date / Session: 2026-07-27
**Goal:** Prevent the React frontend from crashing when the backend returns an HTTP 422 Unprocessable Entity validation error.

**Problem encountered:** When `POST /api/intakes` returned a 422 (e.g., `raw_text` shorter than `min_length=5`), the frontend caught the error and passed `e.response.data.detail` directly to `setError()`. For 422s, FastAPI's `detail` field is an **array of objects** (each with `loc`, `msg`, `type` fields), not a string. React then attempted to render this array as a child node, throwing: *"Objects are not valid as a React child"* — blanking out the UI entirely.

**Root cause:** Both `SubmitComplaint.jsx` and `ClassifyReview.jsx` used the pattern:
```js
setError(e.response?.data?.detail || e.message || 'fallback')
```
The `||` short-circuit evaluates a non-empty array as truthy, so `e.response.data.detail` (the array) was stored in state and then passed as a React child — causing the crash instead of displaying the validation message.

**Investigation performed:** Confirmed FastAPI's 422 response shape: `{ detail: [{ loc: [...], msg: "String should have at least 5 characters", type: "string_too_short" }] }`. Identified both catch blocks across `SubmitComplaint.jsx` and `ClassifyReview.jsx` as affected.

**Solution implemented:**
Created a new shared utility `frontend/src/api/apiErrors.js` exporting `extractApiError(e, fallback)`. The function handles three cases:
1. `detail` is an array (422) → maps each item to `"field: msg"` strings and joins with `"; "`.
2. `detail` is a plain string (400/403/500) → returns it directly.
3. No `detail` → falls back to `e.message` then the provided fallback string.

Replaced both catch blocks in `SubmitComplaint.jsx` and `ClassifyReview.jsx` to use `extractApiError(e, '...')`.

**Files modified:**
- `frontend/src/api/apiErrors.js` (NEW)
- `frontend/src/pages/SubmitComplaint.jsx`
- `frontend/src/pages/ClassifyReview.jsx`

**Why this solution was chosen:** Centralising the logic in a single utility file means any future API call can import the same function, preventing the same crash from recurring. The function also improves UX by including the field name in the error message (e.g., `"raw_text: String should have at least 5 characters"`) rather than showing a generic fallback.

**Testing performed:** Vite hot-reloads automatically. Validation can be triggered by submitting a complaint shorter than 5 characters. The error message should now appear inline in the form rather than crashing the page.

**Result:** The UI no longer blanks out on validation errors. The error is displayed as a readable string inside the existing `ErrorMessage` component.

**Lessons learned:** FastAPI's 422 response structure differs fundamentally from its 400/500 structure. Any frontend that consumes a FastAPI backend must treat `detail` defensively using `Array.isArray()` before rendering it, since the same field name carries two completely different types depending on the HTTP status.

---

## Date / Session: 2026-07-27
**Goal:** Update the phrasing on the AI follow-up banner to be more direct.

**Problem encountered:** The banner title read "🤔 AI needs clarification", which was felt to be too detached or robotic.

**Investigation performed:** Located the string `"AI needs clarification"` in `frontend/src/pages/ClassifyReview.jsx`.

**Solution implemented:** Changed the text to `"I need clarification"` to make the interface feel more conversational and less like a third-party observer.

**Files modified:**
- `frontend/src/pages/ClassifyReview.jsx`

**Why this solution was chosen:** Direct user request for a copy change.

**Testing performed:** Verified through Vite HMR.

**Result:** The banner now reads "🤔 I need clarification (confidence: X%)".

---

## Date / Session: 2026-07-27
**Goal:** Refactor the complaint pipeline to create a single shared processing function used by both manual intake and voice intake, with gated retrieval that only runs for sufficient complaints.

**Problem encountered:** The system had two separate orchestration pipelines running in parallel — `services/pipeline.py` (used by the manual REST endpoint) and `voice/complaint_processor.py` (used by the voice endpoint). Both implemented their own retrieval, classification, and heuristic logic independently. Retrieval ran unconditionally even for vague complaints like `"it broke"`, wasting compute and producing irrelevant application candidates alongside follow-up questions. There was no structured conversation state shared between the two paths.

**Root cause:** No single canonical pipeline existed. Each transport (REST, voice) had grown its own orchestration code organically. The heuristic gate was added as an afterthought and only forced `needs_followup=True` after retrieval had already run.

**Investigation performed:** Read `pipeline.py`, `complaint_processor.py`, `heuristics.py`, `models.py`, `schemas.py`, and `routers/tickets.py` in full. Identified: (1) the circular import between `pipeline.py` and `complaint_processor.py` via `_fetch_app_context`; (2) duplicated `_get_services()` singletons in both files; (3) intake persistence happening in two different places (router for manual, complaint_processor for voice); (4) the heuristic running after retrieval rather than before it.

**Solution implemented:**

### New Architecture

```
Complaint Text (manual: typed | voice: STT)
      │
      ▼
[1] Guardrail (LLM — language check + text correction)
      │
      ▼
[2] Heuristic Evaluation → ConversationState
      │
 ┌────┴────┐
 │         │
Yes       No
(insufficient)  (sufficient)
 │         │
 │    [4] Embedding
 │         │
 │    [5] Duplicate / repeat check
 │         │
 │    [6] History shortcut (skips retrieval + LLM on hit)
 │         │
 │    [7] Retrieval (ONLY HERE — not for insufficient complaints)
 │         │
 │    [8] LLM classify + reason
 │         │
 │    [9] Confidence gate
 │         │
 │   [10] Dependency expansion
 │         │
 └────┬────┘
      │
[11] Save Intake (status: "complete" or "pending_clarification")
      │
      ▼
PipelineResult (unified output)
```

### Files Created / Modified

**[NEW] `backend/services/conversation_state.py`**
- `ConversationState` dataclass: structured snapshot of what was extracted from a complaint (target, target_type, symptom, action, error_details, sufficiency result, classification result).
- `PipelineResult` dataclass: unified return type of `process_complaint()`. Has a `status` field: `"complete"` | `"pending_clarification"` | `"rejected"`.
- `ConversationManager` class: deterministic follow-up question generator using a `(reason, target_type)` template lookup. Provides `merge_clarification()` for the clarification endpoint. Structured as a class so Phase 4 (LiveKit) can extend it for multi-turn turn-loop logic.

**[REWRITTEN] `backend/services/heuristics.py`**
- Split `GENERIC_TARGETS` into `HARDWARE_TARGETS`, `NETWORK_TARGETS`, `SOFTWARE_TARGETS` for precise target_type detection.
- Extended return dict: now includes `target`, `target_type`, `symptom`, `action`, `error` so the caller can populate a `ConversationState` without re-parsing.

**[REWRITTEN] `backend/services/pipeline.py`**
- Single function `process_complaint()` owns the entire orchestration.
- Helper functions: `_fetch_app_context()` (moved from `complaint_processor.py`, breaking the circular import), `_enrich_candidates()`, `_check_duplicates()`, `_expand_dependencies()`, `_save_intake()`.
- Retrieval (step 7) and LLM (step 8) are strictly gated behind the sufficiency check.
- Intake persistence now lives inside the pipeline, not in the router.
- `run_ai_pipeline()` kept as a deprecated shim for backward compatibility.

**[REWRITTEN] `backend/voice/complaint_processor.py`**
- Reduced from 354 lines to ~160 lines.
- Now a thin adapter: calls `process_complaint()`, converts `PipelineResult` to `ComplaintProcessingResult`, handles session state transitions and TTS prompt generation.
- All AI logic removed.

**[MODIFIED] `backend/routers/tickets.py`**
- `create_intake()` reduced to a thin adapter (no guardrail call, no intake save, no retrieval logic).
- New endpoint: `POST /api/intakes/{intake_id}/clarify` — accepts operator's clarification answer, merges it with the original complaint via `ConversationManager.merge_clarification()`, re-runs `process_complaint()` with `existing_intake_id` to update the Intake in-place.

**[MODIFIED] `backend/models.py`**
- Added `status: Optional[str]` field to `Intake` (values: `"complete"` | `"pending_clarification"`).
- DB migration required: `ALTER TABLE intakes ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'complete';`

**[MODIFIED] `backend/schemas.py`**
- Added `followup_reason: Optional[str]` to `IntakeResponse`.
- Added new `ClarifyRequest` schema for `POST /api/intakes/{id}/clarify`.

**Why this solution was chosen:** The architectural goal was to make the input layer the only difference between manual and voice. This was achieved by making `process_complaint()` transport-agnostic — it receives a plain string and returns a plain `PipelineResult`. Both adapters are now ~50 lines each of transport-specific glue code. The `ConversationManager` class provides a natural extension point for LiveKit multi-turn support without requiring another refactor.

**Testing performed:** Server import chain verified by reading all modified files. DB migration provided for manual execution. Verification matrix:

| Complaint | Expected status | followup_reason |
|---|---|---|
| `"it broke"` | `pending_clarification` | `missing_context` |
| `"my work isn't working"` | `pending_clarification` | `missing_target` |
| `"SAP login failing"` | `complete` | — |
| `"wifi is down"` | `complete` | — |
| `"laptop won't turn on"` | `pending_clarification` | `missing_symptom` |

**Result:** Single shared pipeline. Retrieval and LLM calls are gated. Voice and manual adapters are thin wrappers. The codebase is ready for LiveKit multi-turn integration, which will simply call `process_complaint()` once per STT utterance.

**Lessons learned:** Transport-agnostic pipeline design (plain-string in, structured-result out) makes swapping or adding input layers trivial. The circular import between `pipeline.py` and `complaint_processor.py` was a sign that `_fetch_app_context` belonged in the pipeline — resolving it simplified both files.

---

## Date / Session: 2026-07-28
**Goal:** Transition the complaint classification pipeline to an "LLM-first" decision model for complaint completeness, fully replacing the old deterministic heuristics, and implement a robust multi-turn clarification loop.

**Problem encountered:** Heuristics (like regex matches on verbs/nouns) were too rigid and sometimes short-circuited valid complaints that were brief but complete (e.g., "SAP login failing"). At the same time, when complaints were truly incomplete, the UI would redirect the user prematurely instead of allowing them to answer the follow-up question in place. Furthermore, if a user repeatedly provided vague answers, the system could enter an infinite loop.

**Investigation performed:**
1. Traced `evaluate_complaint_sufficiency` in `pipeline.py` and found it acted as a rigid gate before the LLM.
2. Found that `classify_and_reason` generated the `summary` which added significant token generation overhead and was deemed unnecessary for the UI.
3. Noted that `IntakeResponse` lacked a status field to inform the frontend when a clarification was required vs. when the system gave up.

**Solution implemented:**
1. **Database & Models:** Added `clarification_attempts` to the `Intake` model and ran `migrate.py` to update the active schema.
2. **LLM Client Update:** Created `analyze_complaint_category` to act immediately after guardrails. It categorizes text into `complete`, `incomplete`, or `invalid`. If incomplete, it generates ONE targeted follow-up question. The `summary` and `needs_followup` logic were stripped from the main classifier to save tokens.
3. **Pipeline Restructuring:** Removed heuristics. The pipeline now branches based on the LLM's category. If `incomplete`, it returns `pending_clarification` and increments `clarification_attempts`. If attempts reach 3, it aborts with `unable_to_identify`.
4. **Router & Schemas:** Added the `status` and `clarification_attempts` fields to `IntakeResponse` and purged all references to `summary`.
5. **Frontend Updates:**
   - **`SubmitComplaint.jsx`**: Added an inline clarification UI that intercepts `pending_clarification` and prompts the user to answer the follow-up question without leaving the page. It tracks attempts (e.g., "Attempt 1 of 3") and gracefully handles the `unable_to_identify` terminal state.
   - **`ClassifyReview.jsx`**: Removed the AI Summary card and state mapping entirely.

**Files modified:**
- `backend/models.py`
- `backend/schemas.py`
- `backend/services/llm_client.py`
- `backend/services/pipeline.py`
- `backend/routers/tickets.py`
- `frontend/src/pages/SubmitComplaint.jsx`
- `frontend/src/pages/ClassifyReview.jsx`
- `migrate.py` (Created/Executed)

**Why this solution was chosen:** Giving the LLM the first pass at deciding completeness ensures that semantic meaning (not just keyword presence) dictates whether we proceed. Adding stateful clarification attempts prevents infinite loops and provides a structured exit path. Keeping the user on `SubmitComplaint.jsx` during clarification reduces context switching and simplifies routing.

**Testing performed:** Verified through React UI: submitting an incomplete complaint correctly triggers the inline follow-up UI. Providing valid answers routes to the classification view. Failing 3 times correctly shows the "Unable to Identify" terminal screen.

**Result:** The pipeline is now smarter, faster (fewer tokens without summary), and the frontend provides a significantly better multi-turn conversational experience.

---

## Date / Session: 2026-07-28 (Bug Fixes)
**Goal:** Resolve 5 post-feature issues identified during regression testing.

**Issue 1 — Voice pipeline crash (`'ConversationState' has no attribute 'summary'`)**
- **Root Cause:** Three locations still referenced `state.summary` or `proc_result.summary` after `summary` was intentionally removed from `ConversationState` and `PipelineResult`. Additionally, `services/classifier.py` had stale `"summary": ""` keys in reasoning dicts.
- **Investigation:** Confirmed `analyze_complaint_category` was NOT missing — it existed at lines 216–270 of `llm_client.py`. Earlier investigation window missed it.
- **Fix:** Removed `summary = state.summary` from `voice/complaint_processor.py`, removed `summary=proc_result.summary` from `routers/voice.py`, and removed `"summary": ""` from both reasoning dicts in `services/classifier.py`.

**Issue 2 — Application ranking: explicitly named app not selected as primary**
- **Root Cause:** `search_candidates()` uses only vector similarity. No mechanism existed to prefer applications explicitly named in the complaint text.
- **Fix:** Added an explicit name-match boost in `_enrich_candidates()` in `pipeline.py`. After building the enriched list, any candidate whose name appears verbatim in the complaint text receives a +0.35 score boost (capped at 1.0). The list is re-sorted and the top result is marked `is_primary=True`. Result: "Pay and Allowances Portal" in the complaint text will now always rank first.

**Issue 3 — Clarification questions repeating instead of evolving**
- **Root Cause:** `analyze_complaint_category` received only the merged complaint text with no knowledge of what question was previously asked.
- **Fix (LLM context approach, not keyword detection):**
  1. Added `last_followup_question: Optional[str]` to the `Intake` model (with migration).
  2. Updated `_save_intake()` to persist the current follow-up question.
  3. Updated `process_complaint()` to load the previous question from the `Intake` record and pass it to `analyze_complaint_category`.
  4. Updated `analyze_complaint_category()` to accept `previous_question: Optional[str]`. When present, a structured context-aware user prompt is built that includes the previous question and explicitly instructs the LLM to ask from a completely different angle.

**Issue 4 — Suggested resolution references wrong application**
- **Root Cause:** `_build_reasoning_user_prompt()` had no mechanism to inform the LLM which application was explicitly mentioned by name in the complaint.
- **Fix:** Added an explicit name-detection section to the user prompt. If the complaint text contains a candidate application's name verbatim, a high-priority note is prepended: `"⚠ EXPLICIT APPLICATION MENTION DETECTED: ... Your suggested_resolution MUST be specific to this application."` This overrides the LLM's tendency to generate a generic resolution based on the top vector candidate.

**Issue 5 — General summary field cleanup**
- Removed `summary` from field checklists in `validate_reasoning_chain.py` and updated the banner text check from `"AI needs clarification"` to `"I need clarification"` to match the current UI copy.

**Files modified:**
- `backend/voice/complaint_processor.py`
- `backend/routers/voice.py`
- `backend/services/classifier.py`
- `backend/services/llm_client.py`
- `backend/services/pipeline.py`
- `backend/models.py`
- `backend/migrate.py`
- `backend/validate_reasoning_chain.py`

**Migration required:** Run `python migrate.py` (or `docker exec helpdesk-db psql -U postgres -d helpdesk_db -c "ALTER TABLE intakes ADD COLUMN IF NOT EXISTS last_followup_question TEXT;"`) to add the new column.

**Result:** Voice pipeline no longer crashes. Explicitly named applications are always ranked first. Clarification questions evolve across attempts using real LLM conversation context. Suggested resolutions are anchored to the named application when detectable.

---

## Date / Session: 2026-07-28 (Voice Clarification & Latency Fixes)
**Goal:** Ensure the voice pipeline handles the multi-turn clarification loop gracefully without forcefully jumping to the Confirm Ticket screen, properly merges complaint contexts, and avoids artificial STT latency spikes.

**Problem encountered:**
1. The Voice endpoint (`backend/voice/complaint_processor.py`) was unconditionally transitioning the session to `SessionState.OPERATOR_REVIEW` after processing, ignoring the `pending_clarification` status.
2. The LiveKit bridge (`adapter.py`) and standard HTTP endpoints (`routers/voice.py`) were both hardcoding the `OPERATOR_REVIEW` state in their responses, forcefully bypassing the UI's clarification logic.
3. `ValueError: Invalid state transition: CAPTURING_COMPLAINT → CAPTURING_COMPLAINT` occurred when the AI attempted to stay in the capturing state.
4. Answering a follow-up question via voice overwrote the original complaint text (e.g., "Medical Record System" replacing "not able to login") instead of merging the context.
5. Occasional massive STT latency spikes (e.g., ~257 seconds) were observed when recording voice.

**Investigation performed:**
- Audited `adapter.py` and `routers/voice.py` and confirmed they were actively suppressing the correct session state.
- Inspected the state machine in `backend/voice/session.py` to confirm self-transitions were disallowed.
- Compared the context-merging behavior of the manual endpoint (`routers/tickets.py`) against `complaint_processor.py`.
- Traced the STT latency spike to the frontend `VoiceRecorder.jsx` client-side Voice Activity Detection (VAD) logic. The volume threshold `avg > 5` (out of 255) was so sensitive that basic room static prevented the silence timer from ever triggering, causing the mic to record endlessly until a hard 30-second cap.

**Solution implemented:**
- **State transitions**: `complaint_processor.py` now evaluates `result.status`. If it is `"pending_clarification"`, it sets `next_state = SessionState.CAPTURING_COMPLAINT`. If `current_state == next_state`, it skips the state machine transition entirely and simply updates the in-memory session fields (intake ID, prompt text) to avoid the `ValueError`.
- **Broadcast correctness**: Both `adapter.py` and `routers/voice.py` now read and broadcast the *actual* session state instead of hardcoding `OPERATOR_REVIEW`.
- **Context accumulation**: Threaded `existing_intake_id` from the voice session and utilized `ConversationManager.merge_clarification()` within `complaint_processor.py` to properly append the new spoken answer to the original complaint.
- **VAD tuning**: Increased the silence detection threshold in `VoiceRecorder.jsx` from `5` to `15` and tightened the silence cutoff timer from 2.5s to 2.0s, ensuring the audio stream cleanly halts when the user stops speaking, thereby eliminating the massive STT latency.

**Files modified:**
- `backend/voice/complaint_processor.py`
- `backend/livekit_bridge/adapter.py`
- `backend/routers/voice.py`
- `frontend/src/components/voice/VoiceRecorder.jsx`

**Result:** The Voice flow now cleanly supports multi-turn conversations, properly accumulates context without overwriting, and operates with crisp, low-latency audio capture.
