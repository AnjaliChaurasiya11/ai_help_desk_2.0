# AI Help Desk — Intelligent Enterprise Complaint Triage System

> A fully offline, air-gapped enterprise help desk that processes IT complaints via text or voice in English, Hindi, and Hinglish using locally-hosted AI models with zero cloud dependency.

[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.11-brightgreen.svg)]()
[![FastAPI](https://img.shields.io/badge/fastapi-0.138-009688.svg)]()
[![React](https://img.shields.io/badge/react-vite-61DAFB.svg)]()
[![PostgreSQL](https://img.shields.io/badge/postgresql-16+pgvector-336791.svg)]()
[![Status](https://img.shields.io/badge/status-active_development-orange.svg)]()

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Project Goals](#2-project-goals)
3. [Key Features](#3-key-features)
4. [Architecture Overview](#4-architecture-overview)
5. [System Architecture Diagram](#5-system-architecture-diagram)
6. [AI Pipeline](#6-ai-pipeline)
7. [Voice Pipeline](#7-voice-pipeline)
8. [Voice FSM](#8-voice-fsm)
9. [Technology Stack](#9-technology-stack)
10. [Repository Structure](#10-repository-structure)
11. [Database Design](#11-database-design)
12. [API Documentation](#12-api-documentation)
13. [AI Models](#13-ai-models)
14. [Configuration Reference](#14-configuration-reference)
15. [Installation](#15-installation)
16. [Running the Project](#16-running-the-project)
17. [Docker Services](#17-docker-services)
18. [Authentication](#18-authentication)
19. [Logging and Monitoring](#19-logging-and-monitoring)
20. [Security](#20-security)
21. [Performance](#21-performance)
22. [Error Handling](#22-error-handling)
23. [Testing](#23-testing)
24. [Roadmap](#24-roadmap)
25. [Known Limitations](#25-known-limitations)
26. [Credits and Acknowledgements](#26-credits-and-acknowledgements)
27. [License](#27-license)
28. [Appendix — Glossary](#28-appendix--glossary)

---

## 1. Executive Summary

### Problem Statement

Large defence and enterprise organisations maintain hundreds of software applications across isolated networks. When an employee encounters an IT fault, they call a help desk, describe their problem verbally, and wait while an operator manually determines which application is responsible, how severe the issue is, and which team should handle it. This process is slow, error-prone, and inconsistent. Operators often misclassify complaints; repeat callers re-raise the same issues without realising they already have open tickets; and knowledge captured from resolved incidents is never reused.

### Why This Project Exists

This system replaces or augments the manual operator layer with AI-driven triage. It:

- Accepts complaints via **typed text** or **live voice call**
- Automatically identifies the responsible application using **semantic search** rather than keyword matching
- Detects whether a caller is raising a **duplicate** or **repeat** complaint
- Classifies **fault type** and **severity** using a locally-hosted LLM
- Routes tickets directly to the **owning team** of the identified application
- Maintains a **learning loop** so every operator correction immediately improves future predictions

### Why Local AI

The deployment target is an **air-gapped intranet** with no public internet access. All AI inference — embeddings, speech recognition, language model inference, and text-to-speech — runs entirely on-premises. No data leaves the network boundary.

### Why Semantic Search

Enterprise employees rarely describe problems in technical terms. Someone saying *"mera portal nahi khul raha"* (my portal won't open) and someone saying *"I cannot log into the HR system"* may describe the same root cause. Keyword matching fails here. Semantic search using `multilingual-e5-base` embeddings maps both phrases to the same region of vector space, correctly identifying the application regardless of language or phrasing.

### Current Maturity

Active development at v2.0 across four implementation phases:

| Phase | Capability | Status |
|---|---|---|
| Phase 1 | Text complaint intake, AI classification, ticket management | Complete |
| Phase 2 | Voice pipeline (REST): STT, TTS, VAD, FSM | Complete |
| Phase 3 | LLM guardrail, merged verify+classify, clarification loop | Complete |
| Phase 4 | LiveKit WebRTC real-time audio transport | Complete |

---

## 2. Project Goals

### Primary Goals

- Provide a **fully offline** help desk that operates with zero internet connectivity in production
- Accept IT complaints in **English, Hindi, and Hinglish** via text or voice
- Automatically identify the responsible application using **vector similarity search**
- Classify fault type and severity using a **locally-served LLM**
- Ensure every complaint flow — Manual, Voice REST, and Live AI — uses the **same shared core AI pipeline**
- Route tickets automatically to the **correct owning team** from application metadata
- Maintain a complete, immutable **audit trail** for every ticket from creation to closure

### Secondary Goals

- Detect **duplicate complaints** and **repeat callers** within a 4-hour window using semantic similarity
- Implement a **learning loop**: operator corrections stored as embeddings improve future predictions
- Support **multi-fault intake**: one call can produce multiple tickets for separate issues
- Provide operator and admin dashboards with **role-based access control**
- Deliver sub-second TTS response latency using Piper ONNX models

### Non-Goals

- This system does **not** resolve incidents — it triages and routes them
- This system does **not** integrate with telephony (PSTN / SIP) in the current release
- This system is **not** a general-purpose chatbot — it is purpose-built for IT complaint triage

---

## 3. Key Features

### Voice Complaint Registration (Live AI Support)

**Purpose:** Allow an employee to raise an IT complaint over a voice call without typing.

**How it works:** The caller's audio is captured via browser microphone, streamed through LiveKit WebRTC to the backend, transcribed by faster-whisper, corrected by the LLM guardrail, classified by the AI pipeline, and converted into a ticket — all within a single call. The end-of-call summary screen shows the ticket number, application, assigned team, fault type, and severity.

**Technologies:** LiveKit SDK, faster-whisper (CTranslate2), Silero VAD, Piper TTS, LLM guardrail.

---

### Speech-to-Text (STT)

**Purpose:** Transcribe spoken audio to text.

**How it works:** `faster-whisper-medium` runs locally via CTranslate2. It auto-detects language per utterance, supports English, Hindi, and Hinglish, and returns segment-level confidence scores. The engine is loaded once at startup and shared across all sessions.

**Configuration:** `STT_MODEL_SIZE`, `STT_DEVICE`, `STT_COMPUTE_TYPE`, `STT_BEAM_SIZE`.

---

### Voice Activity Detection (VAD)

**Purpose:** Detect when speech begins and ends so the backend knows when the caller has finished speaking.

**How it works:** The official `silero-vad` PyTorch model processes 512-sample frames at 16 kHz. `StreamingEndpointDetector` wraps it with configurable silence thresholds, returning `True` when end-of-speech is detected.

**Configuration:** `VAD_DEVICE`, `VAD_MIN_SILENCE_MS`, `VAD_SPEECH_PAD_MS`, `VAD_THRESHOLD`.

---

### Text-to-Speech (TTS)

**Purpose:** Convert AI responses and system prompts to audio for the caller.

**How it works:** Piper TTS (ONNX-based, `en_US-lessac-medium`) is the primary engine producing sub-100ms latency WAV at 22050 Hz. If Piper models are absent, the system falls back to Windows SAPI5 via `pyttsx3`. Pre-recorded WAV prompts (greeting, retry, fallback) are served from disk without TTS overhead.

**Configuration:** `TTS_BACKEND` (`piper`, `sapi5`, `auto`).

---

### Semantic Duplicate Detection

**Purpose:** Prevent multiple tickets being created for the same underlying issue.

**How it works:** When a new complaint arrives, its 768-dimensional embedding is compared against `learning_examples` using pgvector cosine distance. Complaints from the **same caller** within cosine distance < 0.20, or from **any caller** within < 0.10 over the past 4 hours, are flagged as potential duplicates. The operator sees this before confirming the ticket.

---

### Semantic Application Matching

**Purpose:** Identify which registered application(s) is responsible for the reported issue.

**How it works:** A three-layer vector search runs in parallel:
1. **Learning examples** — prior confirmed complaints (historical recall)
2. **Application symptoms** — known fault descriptions per application
3. **Application purposes** — business purpose descriptions

Results are merged by taking the best score across all three sources. An **explicit name-mention boost** of +0.35 is applied when the complaint text contains an application name verbatim, ensuring explicitly-mentioned apps always surface first.

---

### Conditional Dependency Expansion

**Purpose:** Surface related applications that may be root causes or downstream affected systems.

**How it works:** Given the primary application and classified fault type, the `ApplicationDependencyEngine` traverses the `application_dependencies` graph table, matching `dependency_nature` exactly to the fault type. A login fault on the HR Portal pulls in the Authentication Service only if an `auth` dependency link exists between them.

---

### LLM Guardrail and Classification

**Purpose:** Validate and correct STT transcriptions; classify fault type and severity; generate follow-up questions for incomplete complaints.

**How it works:** A locally-hosted LLM (Qwen 2.5:7b via Ollama/vLLM, OpenAI-compatible API) performs a fused verification+classification call. The prompt includes retrieved candidate applications, their symptoms, and purposes as context. The model returns a structured JSON response with corrected text, validity status, fault type, severity, confidence score, suggested resolution, and a follow-up question when the complaint is insufficient.

`MOCK_LLM=True` returns deterministic mock responses for development without requiring the LLM server.

---

### Clarification Loop

**Purpose:** Gather more information when a complaint is ambiguous or incomplete.

**How it works:** When the LLM determines a complaint is insufficient, the pipeline returns a `pending_clarification` status with a targeted follow-up question. The caller answers, and the combined text is re-processed. Up to `MAX_CLARIFICATION_ATTEMPTS` turns are allowed before the intake is marked `unable_to_identify`. If the LLM confidence falls below `FOLLOWUP_CONFIDENCE_THRESHOLD` (0.65 default), the pipeline overrides to force clarification.

---

### Service Number Validation

**Purpose:** Identify the caller by their 5-digit service number without requiring typing.

**How it works:** A hybrid extraction strategy:
1. **Regex fast path** — scan for 5 consecutive digits in the STT output
2. **Word-to-digit translation** — convert spoken words (`"ek do teen char paanch"` → `"12345"`) using lookup tables for English and Hindi
3. **LLM fallback** — when regex fails, the LLM extracts the number from raw transcript with multilingual digit recognition

Multiplier words are supported: `"double four"` → `"44"`. After normalisation, the result is validated against `^[0-9]{5}$`.

---

### Operator Dashboard

**Purpose:** Allow operators to review AI predictions, correct them, and confirm tickets.

**How it works:** `ClassifyReview.jsx` presents ranked candidate applications, predicted fault type and severity, and the AI summary. Operators can modify any field. Assigned team is auto-populated from `owning_team` of the primary application but is overridable. Both single and multi-ticket confirmation are supported from a single intake.

---

### Team-Based Ticket Routing

**Purpose:** Automatically route tickets to the correct team without manual assignment.

**How it works:** The `create_ticket()` service (shared across all intake channels) reads `owning_team` from the confirmed primary application and sets `assigned_team` on the ticket. If an owning team exists, ticket status is set to `assigned`; otherwise it falls back to `triage`. All team changes are recorded in `ticket_history` with a routing note.

---

### Learning Loop

**Purpose:** Improve AI prediction accuracy over time from operator corrections.

**How it works:** Every confirmed ticket inserts a row into `learning_examples` containing the complaint text embedding alongside both predicted and confirmed labels. On subsequent similar complaints, the search engine queries this table first, providing a history-shortcut path that bypasses the full LLM classify call when a high-confidence match exists.

---

### Mass Outage Detection

**Purpose:** Alert operators when a single application receives a spike in complaints.

**How it works:** When tickets are listed, the backend counts open/assigned tickets per application in the past 60 minutes. Exceeding 10 tickets on one application generates a `MassOutageAlert` in the response. Team-lead users see alerts scoped only to their managed team's applications.

---

### Multi-Fault Intake (One Call, Multiple Tickets)

**Purpose:** Allow a single call or session to produce multiple tickets for separate issues.

**How it works:** After a ticket is confirmed, the voice FSM transitions to `ASK_ANOTHER_COMPLAINT` (R-42). If the caller affirms, the FSM resets to `CAPTURING_COMPLAINT` and the process repeats within the same session. All tickets from the same call are tracked via `CompletedTicket` snapshots in `VoiceSessionData.tickets`.

---

### Developer Diagnostics Panel

**Purpose:** Surface real-time session internals to developers during testing without exposing them to regular users.

**How it works:** A floating bug icon (`🐞`) in the bottom-right corner of the Live Call UI opens a slide-up diagnostics panel showing session state, LiveKit connection status, session ID, detected language, STT confidence, and per-stage latency metrics.

---

## 4. Architecture Overview

The system is structured in five conceptually distinct layers:

### Layer 1 — Presentation (React + Vite)

The Single-Page Application provides different views depending on the authenticated user's role. It communicates with the backend exclusively via REST and WebSocket. No AI inference occurs in the browser.

### Layer 2 — API (FastAPI)

Four routers handle distinct domains:
- `routers/admin.py` — Application Registry CRUD
- `routers/tickets.py` — Complaint intake, ticket confirmation, ticket lifecycle management
- `routers/voice.py` — Voice session management, REST audio endpoints, TTS serving
- `routers/livekit.py` — LiveKit token issuance, session event WebSocket hub

A shared service `services/ticket_service.py` handles all ticket creation logic regardless of entry channel.

### Layer 3 — Voice Transport (LiveKit / REST)

Two parallel paths exist for voice input. The LiveKit WebRTC path processes audio in real time. The REST path accepts uploaded audio files for fallback environments. Both paths converge at `voice/complaint_processor.py` before entering the shared AI pipeline.

### Layer 4 — AI Engine (Python Services)

All AI logic lives in `backend/services/`. The `pipeline.py` orchestrator is the single entry point for complaint processing regardless of input channel. Services are singleton-loaded at startup and shared across all requests.

### Layer 5 — Data Layer (PostgreSQL + pgvector)

All persistence uses PostgreSQL 16 with the pgvector extension. Vector columns (768-dim) store embeddings for symptoms, purposes, learning examples, and resolved ticket notes. Queries use the `<=>` cosine distance operator.

---

## 5. System Architecture Diagram

```mermaid
flowchart TD
    Browser["React SPA (Vite)"]
    Keycloak["Keycloak SSO / JWT"]

    Browser -->|"REST + Bearer JWT"| FastAPI
    Browser -->|"WebSocket"| EventHub
    Browser -->|"WebRTC audio"| LiveKit

    subgraph FastAPI["FastAPI — Port 8001"]
        AdminRouter["admin.py\nApp Registry"]
        TicketsRouter["tickets.py\nTicket Lifecycle"]
        VoiceRouter["voice.py\nVoice REST"]
        LiveKitRouter["livekit.py\nToken + EventHub"]
        EventHub["EventHub\nWebSocket hub"]
    end

    FastAPI -->|"JWKS fetch"| Keycloak

    subgraph VoiceLayer["Voice Layer"]
        VAD["Silero VAD"]
        STT["faster-whisper STT"]
        Validator["Service No. Validator"]
        TTS["Piper TTS / SAPI5"]
        FSM["Voice FSM"]
        Processor["complaint_processor.py"]
    end

    subgraph LiveKitBridge["LiveKit Bridge"]
        Adapter["adapter.py"]
        LiveKit["LiveKit Server (WebRTC)"]
    end

    LiveKit -->|"PCM frames"| Adapter
    Adapter --> VAD
    VAD --> STT
    STT --> Processor
    VoiceRouter --> VAD
    VoiceRouter --> STT
    VoiceRouter --> Validator
    VoiceRouter --> TTS
    VoiceRouter --> FSM

    subgraph AIEngine["AI Engine — services/"]
        Pipeline["pipeline.py (orchestrator)"]
        Embedder["embedder.py\nmultilingual-e5-base"]
        LLM["llm_client.py\nOllama / vLLM"]
        Search["search.py\nVector Search"]
        Deps["dependencies.py\nDep Graph"]
        TicketSvc["ticket_service.py\nTicket Creation"]
    end

    Processor --> Pipeline
    TicketsRouter --> Pipeline
    Pipeline --> Embedder
    Pipeline --> LLM
    Pipeline --> Search
    Pipeline --> Deps
    TicketsRouter --> TicketSvc
    Processor --> TicketSvc

    subgraph DB["PostgreSQL 16 + pgvector"]
        Apps["applications\napplication_symptoms\napplication_purposes\napplication_dependencies"]
        Intakes["intakes"]
        Tickets["tickets\nticket_history\nticket_related_apps"]
        Learning["learning_examples (768-dim)"]
        Auth["user_roles\nclassification_config"]
    end

    AIEngine --> DB
    FastAPI --> DB
```

---

## 6. AI Pipeline

The shared pipeline (`services/pipeline.py`) is the single entry point for all complaint processing. Both the manual REST intake and the voice adapter call `process_complaint()`. The pipeline never touches TTS, session management, or transport-specific code.

### Execution Stages

```
Raw Text Input
      │
      ▼
[Stage 1] LLM Guardrail — verify_and_correct_text()
  • Correct STT errors
  • Reject non-IT, non-target-language input
  • Return corrected text or reject
      │
      ▼
[Stage 2] Category Analysis — analyze_complaint_category()
  (fused with Stage 1 when MERGED_VERIFY_CATEGORY=True — saves one LLM round-trip)
  • complete / pending_clarification / rejected
      │
  ┌───┴───────────┐
  │               │
[REJECTED]   [PENDING CLARIFICATION]
                  └── save Intake, return follow-up question
                      increment clarification_attempts
                      (max attempts → unable_to_identify)
  │
[COMPLETE]
      │
      ▼
[Stage 3] Embedding — multilingual-e5-base, 768-dim
  Format: "query: <corrected text>"
      │
      ▼
[Stage 4] Duplicate Check — pgvector <=> cosine distance
  Same caller, distance < 0.20, within 4h → repeat caller flag
  Any caller, distance < 0.10, within 4h → potential duplicate
      │
      ▼
[Stage 5] History Shortcut
  Check recent confirmed complaints for high-confidence match
  If hit → skip retrieval and LLM classify
      │
      ▼
[Stage 6] Vector Search — 3-layer parallel search
  1. learning_examples  (historical recall)
  2. application_symptoms
  3. application_purposes
  Merge: best score per app across all sources
  Boost: +0.35 if app name appears verbatim in complaint
      │
      ▼
[Stage 7] LLM Reasoning — classify_and_reason()
  Context-enriched prompt: candidates + symptoms + purposes
  Returns: fault_type, severity, confidence, summary, resolution
      │
      ▼
[Stage 8] Dependency Expansion
  Traverse application_dependencies graph
  Match dependency_nature == fault_type exactly
      │
      ▼
[Stage 9] Save Intake — status = "complete"
      │
      ▼
    PipelineResult (returned to calling adapter)
```

### Confidence Handling

If LLM confidence falls below `FOLLOWUP_CONFIDENCE_THRESHOLD` (default 0.65), the pipeline overrides `needs_followup=True` regardless of the model's output.

### Fallback Logic

| Failure | Fallback |
|---|---|
| `MOCK_LLM=True` | Realistic mock responses, no LLM call |
| LLM server unreachable | HTTP 503 propagated to caller |
| Zero embedding | Empty list returned, search skipped |
| No candidates found | Intake saved as `triage`, no ticket proposal |
| Max clarifications reached | Intake marked `unable_to_identify` |

---

## 7. Voice Pipeline

### Two Intake Paths

#### Path A — LiveKit / WebRTC (Primary)

```
Browser Microphone (48 kHz stereo)
      │ WebRTC media track
      ▼
LiveKit Server (Docker, self-hosted)
      │ rtc.AudioStream frames
      ▼
livekit_bridge/adapter.py
  stereo → mono (numpy average)
  48 kHz → 16 kHz resample
      │
      ▼
Silero VAD (512-sample frames, float32)
  end-of-speech detected
      │ PCM buffer
      ▼
faster-whisper STT
  transcript + confidence + language
      │
      ▼
voice/complaint_processor.py → AI Pipeline
      │ prompt text generated
      ▼
Piper TTS → WAV bytes
      │ rtc.AudioSource publish
      ▼
LiveKit Server → Browser Speaker
```

#### Path B — REST Upload (Fallback)

```
Browser (VoiceRecorder.jsx)
  MediaRecorder API, webm/opus
      │ POST /api/voice/complaint
      ▼
backend: convert_to_wav() (pydub)
      │
      ▼
Silence detection (detect_silence)
      │ WAV bytes (16 kHz PCM)
      ▼
faster-whisper STT
      │
      ▼
voice/complaint_processor.py → AI Pipeline
  (identical pipeline as Path A from this point)
```

### Audio Processing Details

- **Input format:** Browser sends webm/opus. Backend converts to 16-bit PCM WAV at 16 kHz via `pydub`.
- **Resampling:** LiveKit frames arrive at browser sample rate (typically 48 kHz). The adapter averages stereo channels and resamples to 16 kHz before VAD.
- **Upload limits:** `VOICE_MAX_AUDIO_SIZE_BYTES` (default 10 MB) is enforced before any STT processing begins, preventing memory exhaustion from oversized payloads.
- **Silence detection:** A secondary silence check rejects silent recordings before STT inference.

---

## 8. Voice FSM

Each voice session is managed by `VoiceSessionManager`, maintaining an explicit state machine per `session_id`. Sessions are stored in process memory and expire after 30 minutes.

### States

| State | Description |
|---|---|
| `GREETING` | Session just created. System plays greeting prompt. |
| `CAPTURING_SERVICE_NUMBER` | Waiting for caller to speak their 5-digit service number. |
| `CONFIRMING_SERVICE_NUMBER` | Number extracted; system reads it back for confirmation. |
| `CAPTURING_COMPLAINT` | Service number confirmed. Waiting for complaint description. |
| `CLASSIFYING_COMPLAINT` | AI pipeline is running (intermediate, not caller-visible). |
| `OPERATOR_REVIEW` | AI has classified; caller/operator sees the proposal. |
| `OPERATOR_FALLBACK` | Max service number retries exceeded. Manual entry required. |
| `TICKET_CREATED` | Ticket persisted. Confirmation delivered to caller. |
| `ASK_ANOTHER_COMPLAINT` | Ticket confirmed. System asks if caller has another complaint. |
| `COMPLETED` | Call ended. Session finalised. |
| `ERROR` | Unrecoverable error. Session terminated. |

### State Diagram

```mermaid
stateDiagram-v2
    [*] --> GREETING : POST /api/voice/start

    GREETING --> CAPTURING_SERVICE_NUMBER : Greeting played

    CAPTURING_SERVICE_NUMBER --> CONFIRMING_SERVICE_NUMBER : Valid 5-digit number extracted
    CAPTURING_SERVICE_NUMBER --> CAPTURING_SERVICE_NUMBER : Invalid input, retry (max 3)
    CAPTURING_SERVICE_NUMBER --> OPERATOR_FALLBACK : Max retries exceeded

    CONFIRMING_SERVICE_NUMBER --> CAPTURING_COMPLAINT : Caller confirms YES
    CONFIRMING_SERVICE_NUMBER --> CAPTURING_SERVICE_NUMBER : Caller says NO

    OPERATOR_FALLBACK --> CAPTURING_COMPLAINT : Manual entry submitted

    CAPTURING_COMPLAINT --> OPERATOR_REVIEW : AI classification complete
    CAPTURING_COMPLAINT --> CAPTURING_COMPLAINT : Insufficient complaint, follow-up asked

    OPERATOR_REVIEW --> TICKET_CREATED : Operator confirms
    TICKET_CREATED --> ASK_ANOTHER_COMPLAINT : Ticket persisted

    ASK_ANOTHER_COMPLAINT --> CAPTURING_COMPLAINT : Caller has another complaint
    ASK_ANOTHER_COMPLAINT --> COMPLETED : Caller says no more complaints

    COMPLETED --> [*]
    ERROR --> [*]
```

---

## 9. Technology Stack

### Frontend

| Technology | Version | Purpose |
|---|---|---|
| React | 18 | UI framework |
| Vite | 5 | Build tool and dev server |
| React Router | 6 | Client-side routing |
| Axios | 1.x | HTTP client with auto auth headers |
| react-keycloak/web | — | Keycloak OIDC integration |
| livekit-client | — | WebRTC room connection |

### Backend

| Technology | Version | Purpose |
|---|---|---|
| Python | 3.11 | Runtime |
| FastAPI | 0.138 | REST API framework |
| Uvicorn | 0.49 | ASGI server |
| Pydantic v2 | 2.13 | Schema validation |
| pydantic-settings | 2.14 | Settings from env file |
| SQLModel | 0.0.38 | ORM layer |
| SQLAlchemy | 2.0 | Database abstraction |
| python-jose | 3.5 | JWT decode and verify |
| httpx | 0.28 | Keycloak JWKS fetch |

### Database

| Technology | Version | Purpose |
|---|---|---|
| PostgreSQL | 16 | Primary data store |
| pgvector | 0.4.2 | 768-dim vector storage and cosine similarity |
| psycopg2-binary | 2.9 | Sync PostgreSQL driver |

### AI and ML

| Technology | Version | Purpose |
|---|---|---|
| sentence-transformers | 5.6 | Embedding model loading |
| transformers | 5.12 | HuggingFace model infrastructure |
| PyTorch | 2.11 (CUDA 12.8) | Model inference backend |
| openai SDK | 2.44 | LLM client (OpenAI-compatible) |
| scikit-learn | 1.9 | Classifier utilities |

### Voice

| Technology | Version | Purpose |
|---|---|---|
| faster-whisper | 1.0.3 | Speech-to-Text |
| CTranslate2 | 4.8.1 | Optimised Whisper inference engine |
| silero-vad | latest | Voice Activity Detection |
| piper-tts | latest | Primary TTS (ONNX) |
| pyttsx3 | 2.90 | Windows SAPI5 TTS fallback |
| pydub | 0.25 | Audio format conversion |
| ONNX Runtime GPU | 1.27 | ONNX model inference |

### Infrastructure

| Technology | Version | Purpose |
|---|---|---|
| Docker Desktop | Latest | Containerisation |
| Docker Compose | 3.8 | Multi-service orchestration |
| Keycloak | 24.0.4 | OIDC identity provider |
| LiveKit Server | Latest | Self-hosted WebRTC media router |
| livekit SDK | 0.17.5 | Backend agent joining rooms |
| livekit-api | 1.0.5 | Token generation and room management |

---

## 10. Repository Structure

```
AI-HELP-DESK/
├── docker-compose.yml           # PostgreSQL+pgvector, Keycloak, LiveKit
├── livekit-config.yaml          # Self-hosted LiveKit config (set node_ip)
├── keycloak-realm-export.json   # Pre-configured realm (auto-imported on start)
├── generate_keycloak_json.py    # Regenerate realm JSON for new environments
├── replace_ips.py               # Rewrite LAN IP across all config files
├── test_api.py                  # Minimal API smoke tests
│
├── backend/
│   ├── .env                     # Runtime overrides (DB URL, LiveKit, keys)
│   ├── config.py                # Pydantic Settings — all variables documented
│   ├── database.py              # SQLModel engine + get_session dependency
│   ├── main.py                  # FastAPI app, router mounting, startup preload
│   ├── models.py                # ORM table definitions (10 tables, vector columns)
│   ├── schemas.py               # Pydantic schemas for ticket APIs
│   ├── voice_schemas.py         # Pydantic schemas for voice layer APIs
│   ├── security.py              # JWT validation, RBAC guards
│   ├── requirements.txt         # Python dependencies (CUDA 12.8 build)
│   ├── seed_db.py               # Seeds DB with applications + embeddings
│   ├── migrate.py               # Manual schema migration script
│   ├── download_weights.py      # Download multilingual-e5-base
│   ├── download_models.py       # Download faster-whisper-medium
│   ├── download_piper.py        # Download Piper TTS ONNX voice
│   ├── download_silero.py       # Download Silero VAD model
│   ├── official_seed_data.json  # Authoritative application data (83 KB)
│   │
│   ├── local_models/            # Offline model weights (git-ignored, ~3 GB)
│   │   ├── multilingual-e5-base/
│   │   ├── whisper-medium-ct2/
│   │   ├── silero_vad.onnx
│   │   └── piper/
│   │
│   ├── services/                # AI and business logic
│   │   ├── embedder.py          # Singleton multilingual-e5-base embedder
│   │   ├── classifier.py        # Fault type and severity classifier
│   │   ├── llm_client.py        # LLM guardrail and classification (mock + real)
│   │   ├── search.py            # Three-layer pgvector candidate search
│   │   ├── dependencies.py      # Conditional dependency expansion engine
│   │   ├── pipeline.py          # Shared AI pipeline orchestrator
│   │   ├── ticket_service.py    # Unified ticket creation service
│   │   └── conversation_state.py # ConversationState + PipelineResult dataclasses
│   │
│   ├── voice/                   # Voice layer
│   │   ├── vad.py               # Silero VAD + StreamingEndpointDetector
│   │   ├── stt.py               # SpeechToTextEngine (faster-whisper)
│   │   ├── tts.py               # TextToSpeechEngine (Piper → SAPI5 fallback)
│   │   ├── complaint_processor.py # Voice-to-pipeline transport adapter
│   │   ├── session.py           # VoiceSessionManager + SessionState FSM
│   │   ├── validators.py        # Service number normalisation and validation
│   │   ├── audio.py             # Format conversion, silence detection
│   │   ├── prompts.py           # Static prompt registry + Jinja2 rendering
│   │   ├── latency_reporter.py  # Per-stage latency measurement and logging
│   │   └── static_prompts/      # Pre-generated WAV prompt files
│   │
│   ├── livekit_bridge/          # WebRTC transport layer
│   │   ├── adapter.py           # LiveKit <-> Voice Layer integration
│   │   ├── client.py            # LiveKit Room Service admin API wrapper
│   │   ├── connection_manager.py # Agent room join/leave/reconnect
│   │   ├── room_manager.py      # Room-to-session registry
│   │   └── token_manager.py     # Short-lived JWT generation for participants
│   │
│   └── routers/
│       ├── admin.py             # Application Registry CRUD (/api/admin/)
│       ├── tickets.py           # Intake, confirm, list, patch (/api/)
│       ├── voice.py             # Voice session REST API (/api/voice/)
│       └── livekit.py           # Token, status, WebSocket hub (/api/livekit/)
│
└── frontend/
    ├── .env                     # VITE_API_URL, VITE_WS_URL, VITE_KEYCLOAK_URL
    ├── package.json
    └── src/
        ├── App.jsx              # Router with protected routes
        ├── auth.config.js       # Keycloak OIDC client config
        ├── useCurrentUser.js    # Hook returning {service_no, role, managed_team}
        ├── api/
        │   ├── axios.js         # Axios instance + auth header injection
        │   ├── registry.api.js  # Application registry calls
        │   ├── tickets.api.js   # Ticket API calls
        │   └── voice.api.js     # Voice session API calls
        ├── components/
        │   ├── layout/
        │   │   ├── Sidebar.jsx
        │   │   └── Topbar.jsx
        │   └── voice/
        │       ├── VoiceSessionPanel.jsx     # Voice session controller
        │       ├── LiveKitAudioTransport.jsx # WebRTC room connection
        │       ├── VoiceRecorder.jsx         # Browser mic capture (REST)
        │       ├── TranscriptPanel.jsx       # Live transcript display
        │       └── ui/
        │           ├── CallSummaryScreen.jsx  # End-of-call ticket summary
        │           ├── CallControls.jsx       # Mic / mute controls
        │           ├── ConnectionStatus.jsx   # LiveKit connection indicator
        │           ├── LanguageBadge.jsx      # Detected language display
        │           ├── VoiceAvatar.jsx        # Animated speaking indicator
        │           └── Waveform.jsx           # Audio waveform visualisation
        └── pages/
            ├── LoginPage.jsx           # Keycloak login redirect
            ├── Dashboard.jsx           # Home dashboard with ticket stats
            ├── SubmitComplaint.jsx     # Text + voice complaint form
            ├── ClassifyReview.jsx      # AI review, single/multi ticket confirm
            ├── TicketList.jsx          # All tickets with filters
            ├── TicketDetail.jsx        # Ticket detail + status + audit trail
            ├── TeamQueue.jsx           # Team-scoped queue for admins
            ├── Registry.jsx            # Application registry (admin)
            ├── TrackTicket.jsx         # Public ticket tracking by number
            ├── LiveCallPage.jsx        # Live AI voice session UI
            └── LiveCallContainer.jsx   # Session and summary state handler
```

---

## 11. Database Design

### Tables

| Table | Primary Key | Purpose |
|---|---|---|
| `applications` | `id` | Master registry of enterprise software applications |
| `application_symptoms` | `id` | Known fault symptoms per application with 768-dim embedding |
| `application_purposes` | `id` | Business purpose descriptions per application with 768-dim embedding |
| `application_dependencies` | `id` | Directed dependency graph with typed `dependency_nature` |
| `intakes` | `id` | Raw complaint before ticket creation; tracks clarification attempts |
| `tickets` | `ticket_number` | Main ticket: status, fault, severity, assigned_team, assignee_id |
| `ticket_related_apps` | `(ticket_number, related_application_id)` | Multi-application incident links |
| `ticket_history` | `id` | Immutable audit trail with optional resolution embedding |
| `learning_examples` | `id` | Operator-confirmed labels and embeddings for learning loop |
| `user_roles` | `service_no` | Maps service number to role and managed team |
| `classification_config` | `id` | Zero-shot label descriptions for fault types and severities |

### Vector Columns

| Table | Column | Dimension | Purpose |
|---|---|---|---|
| `application_symptoms` | `embedding` | 768 | Complaint to symptom similarity search |
| `application_purposes` | `embedding` | 768 | Complaint to purpose similarity search |
| `learning_examples` | `text_embedding` | 768 | Historical confirmed complaint lookup |
| `ticket_history` | `resolution_embedding` | 768 | Similar past resolution retrieval |

### Ticket Number Format

`TIC-YYYYMM-XXXX` (e.g., `TIC-202607-0045`). A PostgreSQL advisory lock `pg_advisory_xact_lock(7483921)` prevents race conditions during sequential number generation.

### Ticket Status Lifecycle

```
open → triage → assigned → in_progress → resolved → closed
                  ↑                          │
                  └──────── reopened ←───────┘
```

Closing a ticket requires `notes` to be provided (enforced server-side).

### Migration Strategy

The project does not use Alembic. Schema changes require manual `ALTER TABLE` statements. Required statements for upgrading to v2.0:

```sql
ALTER TABLE tickets
  ADD COLUMN IF NOT EXISTS assigned_team VARCHAR(100);

ALTER TABLE intakes
  ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'complete',
  ADD COLUMN IF NOT EXISTS clarification_attempts INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_followup_question TEXT;
```

---

## 12. API Documentation

**Base URL:** `http://<host>:8001`

All protected routes require: `Authorization: Bearer <keycloak_jwt>`

---

### Health

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | None | Returns `{"status": "ok", "version": "1.0.0"}` |
| `GET` | `/api/me` | Required | Returns `{service_no, role, managed_team}` |

---

### Complaint Intake

#### `POST /api/intakes` — Submit complaint for AI classification

**Auth:** Operator

```json
// Request
{
  "raw_text": "I cannot log into the Medical Records System",
  "complainant_service_no": "12345",
  "complainant_name": "Ravi Kumar",
  "complainant_unit": "Alpha Unit",
  "complainant_rank": "Corporal"
}

// Response
{
  "intake_id": 42,
  "corrected_text": "I cannot log into the Medical Records System",
  "status": "complete",
  "candidates": [
    {
      "application_id": 3,
      "application_name": "Medical Records System",
      "owning_team": "Medical IT Team",
      "confidence_score": 0.94,
      "is_primary": true
    }
  ],
  "fault_type_proposal": "login/access",
  "severity_proposal": "high",
  "is_repeat_caller": false,
  "potential_duplicates": [],
  "needs_followup": false,
  "ai_summary": "Employee cannot access Medical Records System.",
  "ai_confidence": 0.94,
  "ai_suggested_resolution": "Reset Active Directory credentials."
}
```

---

#### `POST /api/intakes/clarify` — Submit clarification answer

**Auth:** Operator

```json
{
  "intake_id": 42,
  "additional_text": "It is the HR portal for leave applications"
}
```

---

### Ticket Confirmation

#### `POST /api/tickets/confirm` — Confirm single ticket

**Auth:** Operator

```json
// Request
{
  "intake_id": 42,
  "confirmed_app_id": 3,
  "related_app_ids": [7],
  "confirmed_fault_type": "login/access",
  "confirmed_severity": "high",
  "operator_notes": "Reset credentials attempted, still failing.",
  "predicted_app_id": 3,
  "predicted_fault_type": "login/access",
  "predicted_severity": "high",
  "assigned_team": "Medical IT Team"
}

// Response
{
  "ticket_number": "TIC-202607-0045",
  "status": "assigned",
  "primary_application_name": "Medical Records System",
  "fault_type": "login/access",
  "severity": "high",
  "routed_to_team": "Medical IT Team",
  "message": "Ticket created. Routed to Medical IT Team."
}
```

---

#### `POST /api/tickets/confirm-multi` — Confirm multiple tickets from one intake

**Auth:** Operator

```json
{
  "intake_id": 42,
  "tickets": [
    {
      "confirmed_app_id": 3,
      "confirmed_fault_type": "login/access",
      "confirmed_severity": "high",
      "assigned_team": "Medical IT Team"
    },
    {
      "confirmed_app_id": 7,
      "confirmed_fault_type": "total outage",
      "confirmed_severity": "critical",
      "assigned_team": "Network Team"
    }
  ]
}
```

---

### Ticket Management

#### `GET /api/tickets` — List tickets with optional filters

**Auth:** Operator/Admin (team-scoped for admin role)

| Query Param | Type | Description |
|---|---|---|
| `status` | string | Filter by status |
| `search` | string | Search ticket_number or service_no |
| `skip` | int | Pagination offset (default 0) |
| `limit` | int | Page size (default 50) |

Response includes `mass_outage_alerts` array when applicable.

---

#### `GET /api/tickets/track/{ticket_number}` — Public tracking (no auth)

---

#### `PATCH /api/tickets/{ticket_number}` — Update ticket status

**Auth:** Admin

```json
{
  "new_status": "resolved",
  "notes": "Credentials reset by L2 support.",
  "changed_by": "12345P",
  "assigned_team": "Medical IT Team"
}
```

---

#### `GET /api/tickets/{ticket_number}/history` — Full audit trail

#### `GET /api/tickets/{ticket_number}/similar-resolutions` — Semantic resolution lookup

---

### Application Registry

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/admin/applications` | Any | List all applications |
| `POST` | `/api/admin/applications` | Operator | Create application |
| `PUT` | `/api/admin/applications/{id}` | Operator | Update application |
| `DELETE` | `/api/admin/applications/{id}` | Operator | Delete application |
| `POST` | `/api/admin/applications/{id}/symptoms` | Operator | Add symptom (auto-embedded) |
| `POST` | `/api/admin/applications/{id}/purposes` | Operator | Add purpose (auto-embedded) |
| `POST` | `/api/admin/dependencies` | Operator | Create dependency link |

---

### Voice API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/voice/start` | Create session; returns session_id + LiveKit token |
| `POST` | `/api/voice/service-number` | Upload audio for service number extraction |
| `POST` | `/api/voice/confirm` | Text YES/NO: confirm or retry service number |
| `POST` | `/api/voice/confirm-audio` | Audio YES/NO: confirm or retry service number |
| `POST` | `/api/voice/complaint` | Upload complaint audio for AI classification |
| `POST` | `/api/voice/fallback` | Manual service number entry (OPERATOR_FALLBACK state) |
| `POST` | `/api/voice/another-complaint` | Audio YES/NO for another complaint |
| `GET` | `/api/voice/status` | Query current session state |
| `GET` | `/api/voice/tts` | Generate dynamic TTS WAV for arbitrary text |
| `GET` | `/api/voice/prompt/{key}` | Serve pre-recorded static WAV prompt |
| `GET` | `/api/voice/spell/{text}` | TTS: spell out text character by character |

---

### LiveKit API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/livekit/token` | Re-issue caller LiveKit room token |
| `GET` | `/api/livekit/status` | Active rooms and agent status |
| `WS` | `/api/livekit/events/{session_id}` | WebSocket: push session events to browser |

---

## 13. AI Models

### multilingual-e5-base

| Property | Value |
|---|---|
| Purpose | Text embedding for semantic similarity |
| Input | Text prefixed with `"query: "` |
| Output | 768-dimensional float vector |
| Size | ~1.1 GB |
| Offline | Yes — `local_models/multilingual-e5-base/` |
| Languages | 100+ including English, Hindi, Hinglish |

---

### faster-whisper-medium (CTranslate2)

| Property | Value |
|---|---|
| Purpose | Speech-to-Text transcription |
| Input | WAV audio (16 kHz, 16-bit PCM) |
| Output | Transcript + language + confidence segments |
| Size | ~1.5 GB |
| Offline | Yes — `local_models/whisper-medium-ct2/` |
| Benefit | 4x faster than vanilla Whisper; half VRAM; int8 quantisation |

---

### Silero VAD

| Property | Value |
|---|---|
| Purpose | Real-time speech start/end detection |
| Input | 512-sample PCM frames at 16 kHz |
| Output | Speech probability per frame (0.0–1.0) |
| Size | ~2.3 MB |
| Offline | Yes — loaded via `silero-vad` package |

---

### Piper TTS (en_US-lessac-medium)

| Property | Value |
|---|---|
| Purpose | Text-to-speech for AI responses |
| Input | Text string |
| Output | WAV audio (22050 Hz, 16-bit) |
| Size | ~65 MB (ONNX + config JSON) |
| Offline | Yes — `local_models/piper/en_US-lessac-medium.onnx` |
| Fallback | Windows SAPI5 via `pyttsx3` |

---

### LLM — Qwen 2.5:7b (via Ollama / vLLM)

| Property | Value |
|---|---|
| Purpose | Guardrail, text correction, classification, follow-up generation |
| Input | System prompt + complaint text + candidate application context |
| Output | Structured JSON (corrected text, fault type, severity, confidence, summary, resolution) |
| API | OpenAI-compatible `/v1/chat/completions` |
| Offline | Yes — served by self-hosted Ollama or vLLM on local GPU |
| Mock mode | `MOCK_LLM=True` bypasses all LLM calls |

> **Note:** `VLLM_MODEL_NAME` currently points to `qwen2.5:7b` via Ollama for development. The original air-gapped environment uses Gemma 4 via vLLM. Either model works provided the server is running at `VLLM_API_URL`.

---

## 14. Configuration Reference

All settings live in `backend/config.py`. The `backend/.env` file overrides defaults.

### Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/helpdesk_db` | PostgreSQL DSN. Use port 5433 for Docker deployment. |

### Server

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Uvicorn bind address |
| `PORT` | `8001` | Uvicorn port |
| `DEBUG` | `True` | Hot-reload (development only) |
| `CORS_ORIGINS` | `["http://localhost:5173", ...]` | Explicit allowed origins list |

### Authentication

| Variable | Default | Description |
|---|---|---|
| `AUTH_ENABLED` | `False` | `True` enforces JWT. `False` = dev user on all requests. |
| `KEYCLOAK_URL` | `http://localhost:8080` | Keycloak server base URL |
| `KEYCLOAK_REALM` | `ai-helpdesk` | Realm name |
| `KEYCLOAK_CLIENT_ID` | `helpdesk-frontend` | OIDC client ID |

### LLM

| Variable | Default | Description |
|---|---|---|
| `VLLM_API_URL` | `http://localhost:11434/v1` | Ollama or vLLM endpoint |
| `VLLM_MODEL_NAME` | `qwen2.5:7b` | Model name on the server |
| `VLLM_API_KEY` | `none` | API key if required |
| `MOCK_LLM` | `False` | `True` = skip all LLM calls |
| `MERGED_VERIFY_CATEGORY` | `True` | Fuse verify+classify into one call (~40–50% latency reduction) |
| `ENABLE_AI_REASONING` | `True` | Include candidate context in classify prompt |
| `CLASSIFY_MAX_CANDIDATES` | `3` | Limit candidates injected into prompt |
| `CLASSIFY_MAX_DESC_CHARS` | `120` | Max chars per symptom/purpose in prompt |
| `FOLLOWUP_CONFIDENCE_THRESHOLD` | `0.65` | Force clarification if LLM confidence below this |
| `MAX_CLARIFICATION_ATTEMPTS` | `3` | Max follow-up turns before unable_to_identify |

### Voice and STT

| Variable | Default | Description |
|---|---|---|
| `STT_MODEL_SIZE` | `medium` | Whisper model size |
| `STT_DEVICE` | `auto` | `auto`, `cuda`, or `cpu` |
| `STT_COMPUTE_TYPE` | `default` | `default`, `float16`, `int8` |
| `STT_BEAM_SIZE` | `1` | 1 = greedy (fastest) |
| `VOICE_MAX_AUDIO_SIZE_BYTES` | `10485760` | Max upload size (10 MB) |
| `VOICE_SESSION_TTL` | `1800` | Session expiry in seconds |
| `VOICE_MAX_SVC_RETRIES` | `3` | Max service number retries |

### VAD

| Variable | Default | Description |
|---|---|---|
| `VAD_DEVICE` | `cuda` | `cuda` or `cpu` |
| `VAD_MIN_SILENCE_MS` | `2000` | Silence to trigger end-of-speech |
| `VAD_SPEECH_PAD_MS` | `400` | Padding before/after speech |
| `VAD_THRESHOLD` | `0.5` | Silero speech probability threshold |

### LiveKit

| Variable | Default | Description |
|---|---|---|
| `LIVEKIT_ENABLED` | `True` | `True` = activate WebRTC path |
| `LIVEKIT_URL` | `ws://localhost:7880` | LiveKit WebSocket URL |
| `LIVEKIT_API_KEY` | `helpdesk_key` | Change in production |
| `LIVEKIT_API_SECRET` | `helpdesk_secret_change_in_production` | **Change before deployment** |

### Frontend Environment

| Variable | Example | Description |
|---|---|---|
| `VITE_API_URL` | `http://192.168.x.x:8001` | Backend REST API URL |
| `VITE_WS_URL` | `ws://192.168.x.x:8001` | Backend WebSocket URL |
| `VITE_KEYCLOAK_URL` | `http://192.168.x.x:8080` | Keycloak URL |

---

## 15. Installation

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Docker Desktop | Latest | Must be running before Step 1 |
| Python | 3.11.x | `python --version` to verify |
| Node.js | 18 or 20 LTS | `node --version` to verify |
| CUDA | 12.8+ | Optional. GPU accelerates VAD, STT. CPU fallback available. |
| Disk space | ~5 GB | Model weights total |
| RAM | 8 GB minimum | 16 GB recommended |

### Step 1 — Start Docker Services

```powershell
# From project root
docker compose up -d
docker ps
```

Expected containers: `helpdesk-db` (5433), `helpdesk-keycloak` (8080), `helpdesk-livekit` (7880/7881/7882).

### Step 2 — Configure LAN IP

```powershell
python replace_ips.py
```

Or manually edit `backend/.env`, `frontend/.env`, and `livekit-config.yaml` with your LAN IP. After changing `livekit-config.yaml`:

```powershell
docker restart helpdesk-livekit
```

### Step 3 — Backend Virtual Environment

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

> **CPU-only:** Remove the `--extra-index-url` CUDA line and replace the torch lines with standard CPU builds before `pip install`.

### Step 4 — Download AI Model Weights

```powershell
python download_weights.py   # multilingual-e5-base (~1.1 GB)
python download_models.py    # faster-whisper-medium (~1.5 GB)
python download_piper.py     # Piper TTS voice (~65 MB)
```

> **Air-gapped setup:** Download on an internet-connected machine, copy the `local_models/` directory, then set `TRANSFORMERS_OFFLINE=1` and `HF_HUB_OFFLINE=1` in `backend/.env`.

### Step 5 — Seed the Database

```powershell
python seed_db.py
```

Output: `Database successfully seeded with AI vectors!`

### Step 6 — Apply Schema Migrations (Upgrade Only)

```sql
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS assigned_team VARCHAR(100);
ALTER TABLE intakes ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'complete';
ALTER TABLE intakes ADD COLUMN IF NOT EXISTS clarification_attempts INTEGER DEFAULT 0;
ALTER TABLE intakes ADD COLUMN IF NOT EXISTS last_followup_question TEXT;
```

### Step 7 — Install Frontend Dependencies

```powershell
cd frontend
npm install
```

---

## 16. Running the Project

### Development Mode

**Terminal 1 — Backend:**
```powershell
cd backend
.\venv\Scripts\activate
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

**Terminal 2 — Frontend:**
```powershell
cd frontend
npm run dev -- --host
```

### Access Points

| Service | URL |
|---|---|
| Frontend (local) | `http://localhost:5173` |
| Frontend (LAN) | `http://192.168.x.x:5173` |
| Backend API | `http://localhost:8001` |
| Swagger UI | `http://localhost:8001/docs` |
| ReDoc | `http://localhost:8001/redoc` |
| Keycloak Admin | `http://localhost:8080` — `admin` / `admin` |

### Starting the LLM Server

```powershell
ollama serve
ollama pull qwen2.5:7b
```

Set `MOCK_LLM=False` in `backend/.env` once the server is running.

---

## 17. Docker Services

### Services

| Container | Image | Ports | Purpose |
|---|---|---|---|
| `helpdesk-db` | `pgvector/pgvector:pg16` | `5433:5432` | PostgreSQL 16 + pgvector |
| `helpdesk-keycloak` | `quay.io/keycloak/keycloak:24.0.4` | `8080:8080` | OIDC identity provider |
| `helpdesk-livekit` | `livekit/livekit-server:latest` | `7880`, `7881`, `7882/udp` | WebRTC media server |

### LiveKit Ports

| Port | Protocol | Purpose |
|---|---|---|
| `7880` | HTTP/WS | Python SDK + browser client connection |
| `7881` | TCP | WebRTC fallback when UDP is blocked |
| `7882` | UDP | Primary WebRTC media (lowest latency) |

### Volumes

| Volume | Mount | Purpose |
|---|---|---|
| `postgres_data` | `/var/lib/postgresql/data` | Persistent database |
| `./keycloak-realm-export.json` | `/opt/keycloak/data/import/realm.json` | Auto-imported realm |
| `./livekit-config.yaml` | `/etc/livekit/config.yaml` | LiveKit server config |

---

## 18. Authentication

### Mechanism

Keycloak 24 acts as the OIDC identity provider. The React frontend uses `react-keycloak/web` for the login redirect. After login, an RS256-signed JWT is attached as a Bearer token on all Axios requests.

### Backend Validation (`security.py`)

1. Extract `Authorization: Bearer <token>` from the request header
2. Fetch Keycloak JWKS (cached in module variable after first successful fetch)
3. Decode and verify the JWT signature using RS256
4. Extract `preferred_username` (the service number) from the payload
5. Query `user_roles` table for role and managed_team
6. Return `CurrentUser(service_no, role, managed_team)`

### Development Mode

`AUTH_ENABLED=False` (the default) returns `DEV-00000 / operator` for every request. No Keycloak required.

### Roles

| Role | Permissions |
|---|---|
| `operator` | Submit complaints, confirm tickets, view all tickets |
| `admin` | Update ticket status, reassign teams; scoped to `managed_team` if set |

---

## 19. Logging and Monitoring

### Log Format

```
2026-07-29 18:00:00,123 INFO routers.tickets: Intake 42 processed in 850ms
```

### Named Loggers

| Logger | Module |
|---|---|
| `startup` | Model preload events |
| `routers.tickets` | Ticket API requests |
| `routers.voice` | Voice session events |
| `services.pipeline` | Per-stage latency timings |
| `voice.stt` | STT inference events |
| `voice.tts` | TTS generation events |
| `voice.complaint_processor` | Session processing events |
| `services.ticket_service` | Ticket creation events |
| `livekit_bridge.adapter` | WebRTC transport events |

### Latency Logging

`services/pipeline.py` emits a structured latency breakdown after every complaint:

```
[pipeline:timings] total=850ms  stages={ guardrail=320ms  embed=45ms  search=18ms  llm_reason=420ms  deps=12ms  save=35ms }
```

`ENABLE_LATENCY_PROFILING=True` (default) enables per-stage reports. Set `False` to reduce log volume.

---

## 20. Security

### Air-Gap Assumptions

- No data leaves the network. All AI inference is local.
- `TRANSFORMERS_OFFLINE=1` and `HF_HUB_OFFLINE=1` block accidental model download attempts.

### Input Validation

- All API requests validated by Pydantic v2 before business logic
- Audio upload size enforced before STT processing (`VOICE_MAX_AUDIO_SIZE_BYTES`)
- All SQL queries use parameterised statements — no string interpolation

### CORS

`allow_origins=["*"]` is deliberately avoided. An explicit `CORS_ORIGINS` list is required to comply with the Fetch specification when `allow_credentials=True`.

### Known Security Limitations

| Limitation | Mitigation |
|---|---|
| `AUTH_ENABLED=False` default | **Must** be set `True` for non-development deployments |
| No rate limiting | Deploy behind nginx with per-IP rate limits in production |
| JWKS cached at startup | Restart backend if Keycloak signing key rotates |
| In-memory sessions | Restart clears all active voice sessions |
| LiveKit secret is a placeholder | Change `LIVEKIT_API_SECRET` before any deployment |
| Prompt injection not filtered | Structured JSON output reduces risk; text filtering not yet implemented |

---

## 21. Performance

### Approximate Latencies (GPU Development Machine)

| Stage | Latency |
|---|---|
| Text embedding | 40–80 ms |
| pgvector search (3 tables) | 10–30 ms |
| Duplicate check | 10–20 ms |
| LLM verify+classify (merged, GPU) | 300–800 ms |
| Whisper STT (medium, GPU, ~5 s audio) | 400–600 ms |
| Piper TTS (one sentence) | 50–100 ms |
| Full pipeline (complete path) | 800–1500 ms |
| Full pipeline (history hit, no LLM) | 100–200 ms |

### Optimisations Implemented

- **Merged LLM call** (`MERGED_VERIFY_CATEGORY=True`): single LLM round-trip instead of two, saving ~40–50% latency
- **History shortcut**: skip LLM classify when a high-confidence learning example match exists
- **Model singleton**: all AI models loaded once at startup and reused across all requests
- **Greedy STT decoding** (`STT_BEAM_SIZE=1`): fastest Whisper path with minimal accuracy trade-off for short utterances
- **Prompt size limits**: `CLASSIFY_MAX_CANDIDATES` and `CLASSIFY_MAX_DESC_CHARS` bound LLM prompt token count
- **Static prompt cache**: pre-generated WAV files served from disk, no TTS overhead for common prompts

---

## 22. Error Handling

### API Layer

| Error | HTTP Code |
|---|---|
| Validation failure (Pydantic) | 422 Unprocessable Entity |
| Business logic error | 400 Bad Request with detail |
| Not authenticated | 401 Unauthorized |
| Insufficient permissions | 403 Forbidden |
| Resource not found | 404 Not Found |
| Audio file too large | 413 Request Entity Too Large |
| LLM server unreachable | 503 Service Unavailable |

### Voice Layer

| Scenario | Handling |
|---|---|
| Silent audio | HTTP 400 "No speech detected" |
| STT transcription failure | HTTP 500 with error detail |
| Max service number retries | Session → OPERATOR_FALLBACK state |
| Max clarification attempts | Intake → unable_to_identify |

### Startup

Model preload failures are non-fatal. The server starts successfully and loads models lazily on the first request that requires them.

---

## 23. Testing

### Current Test Files

| File | Purpose |
|---|---|
| `test_api.py` | Basic API endpoint smoke tests |
| `test_vad.py` | Silero VAD loading and inference |
| `test_vad_direct.py` | Direct VAD probability verification |
| `test_mic_vad.py` | Live microphone VAD integration |
| `eval_classifier.py` | Fault/severity classifier accuracy evaluation |
| `validate_reasoning_chain.py` | Contract: PipelineResult fields exist in ComplaintProcessingResult |

### Missing Test Coverage

The following areas have no automated tests:

- `services/pipeline.py` — end-to-end pipeline branches
- `services/ticket_service.py` — ticket creation side-effects
- `routers/tickets.py` — API integration tests
- `voice/validators.py` — service number normalisation edge cases
- `livekit_bridge/adapter.py` — WebRTC transport
- Frontend components — no Jest or Vitest tests

### Suggested Tests

```
pytest tests/
├── unit/
│   ├── test_pipeline.py         # Mock LLM + DB; test each pipeline branch
│   ├── test_ticket_service.py   # Mock DB; test create_ticket() side effects
│   ├── test_validators.py       # Service number normalisation table tests
│   └── test_search.py           # Mock pgvector; multi-source fusion logic
├── integration/
│   ├── test_intake_api.py       # POST /api/intakes with real DB
│   └── test_confirm_api.py      # Full intake → confirm → ticket flow
└── performance/
    └── test_latency.py          # Per-stage latency under concurrent load
```

---

## 24. Roadmap

### Short-Term

- Add Alembic for managed database migrations
- Add pytest integration suite for the full ticket creation flow
- Implement refresh token handling in the React frontend
- Replace in-memory voice sessions with Redis for multi-worker support

### Medium-Term

- SIP/PSTN telephony gateway for traditional phone calls
- Real-time supervisor dashboard with live queue and SLA metrics
- Automated resolution suggestion delivery to end-users
- Hindi TTS voice model (Piper `hi_IN-swara-medium`)

### Long-Term

- STT fine-tuning on domain-specific terminology
- Automated escalation rules based on SLA thresholds
- Integration with external ticketing systems (JIRA, ServiceNow) via webhooks
- Multi-agent concurrent session support with Redis-backed state

---

## 25. Known Limitations

| Limitation | Impact | Mitigation |
|---|---|---|
| In-memory voice sessions | Sessions lost on backend restart | Acceptable for single-operator. Redis needed for HA. |
| No Alembic migrations | Manual SQL on schema changes | ALTER TABLE statements documented in models.py |
| STT single-threaded | Concurrent voice sessions queue at STT lock | Acceptable for low concurrency. Pool on high load. |
| JWKS cached at startup | Backend restart needed on Keycloak key rotation | Standard for air-gapped environments |
| No rate limiting | API flood possible | Add nginx rate limiting in production |
| `AUTH_ENABLED=False` default | API open without Keycloak | Must set True for non-development |
| No frontend tests | UI regressions uncaught | Manual testing required |
| `.bak` files committed | `VoiceRecorder.jsx.bak`, `VoiceSessionPanel.jsx.bak` | Should be removed and git-ignored |
| LLM prompt injection | Complaint text reaches LLM unfiltered | Structured JSON output mitigates; full filtering not yet implemented |

---

## 26. Credits and Acknowledgements

| Component | Source | Licence |
|---|---|---|
| `intfloat/multilingual-e5-base` | HuggingFace / Microsoft | MIT |
| faster-whisper | SYSTRAN | MIT |
| OpenAI Whisper | OpenAI | MIT |
| Silero VAD | Silero Team | MIT |
| Piper TTS | Rhasspy Project | MIT |
| pgvector | pgvector contributors | MIT |
| FastAPI | Sebastián Ramírez | MIT |
| SQLModel | Sebastián Ramírez | MIT |
| LiveKit | LiveKit Inc. | Apache 2.0 |
| Keycloak | Red Hat | Apache 2.0 |
| React | Meta | MIT |
| Vite | Evan You | MIT |
| PyTorch | Meta / Linux Foundation | BSD |

---

## 27. License

This repository does not currently contain a `LICENSE` file.

**Recommended:** MIT License for an internal defence/enterprise tool, or Apache 2.0 if external contributions are anticipated.

---

## 28. Appendix — Glossary

| Term | Definition |
|---|---|
| Air-gapped | A network physically isolated from the public internet |
| pgvector | PostgreSQL extension for 768-dim vector storage and cosine similarity search |
| Cosine distance | `<=>` operator in pgvector; 0.0 = identical vectors |
| VAD | Voice Activity Detection — determines when speech is present in an audio stream |
| STT | Speech-to-Text — converts audio to transcript text |
| TTS | Text-to-Speech — converts text to audio |
| FSM | Finite State Machine — explicit states and transitions for voice session lifecycle |
| Intake | A raw complaint record before it becomes a confirmed ticket |
| Learning Loop | Operator corrections stored as embeddings, retrieved on future similar complaints |
| Dependency Expansion | Surfacing upstream/downstream applications related to the primary fault |
| Guardrail | LLM validation step rejecting non-IT, gibberish, or non-target-language input |
| RBAC | Role-Based Access Control |
| OIDC | OpenID Connect — authentication layer used by Keycloak |
| JWKS | JSON Web Key Set — Keycloak's public keys for JWT signature verification |
| WebRTC | Web Real-Time Communication — peer-to-peer audio protocol used by LiveKit |
| CTranslate2 | Optimised Transformer inference engine used by faster-whisper |
| Hinglish | Code-mixed Hindi-English commonly spoken across India |
| `TIC-YYYYMM-XXXX` | Ticket number format (e.g., `TIC-202607-0045`) |
| Mass Outage | Triggered when >10 open tickets exist for one application within 60 minutes |
| OPERATOR_FALLBACK | FSM state when service number cannot be extracted after max retries |
| Assigned Team | The owning team routed onto the ticket, derived from `applications.owning_team` |
| Mock LLM | Development mode bypassing all LLM calls with deterministic fake responses |

---

*This README was generated from direct codebase analysis. All information reflects what is actually implemented in the repository as of July 2026.*
