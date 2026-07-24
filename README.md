# AI Help Desk — Intelligent Complaint Triage System

> **Air-gapped, fully offline, enterprise-grade help desk** with real-time voice intake, multilingual AI classification, semantic search, WebRTC audio transport, and role-based ticketing.

---

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [Architecture](#architecture)
4. [Technology Stack](#technology-stack)
5. [Repository Layout](#repository-layout)
6. [Database Schema](#database-schema)
7. [Prerequisites](#prerequisites)
8. [Step-by-Step Setup](#step-by-step-setup)
9. [Environment Configuration](#environment-configuration)
10. [Running the Project](#running-the-project)
11. [Downloading AI Models](#downloading-ai-models)
12. [Voice Layer (WebRTC / LiveKit)](#voice-layer)
13. [Troubleshooting](#troubleshooting)
14. [Service Summary](#service-summary)

---

## Overview

The **AI Help Desk** is a secure, intelligent complaint triage system designed for **air-gapped enterprise environments**. It processes user complaints in **English, Hindi, and Hinglish (code-mixed)** to automatically:

- Identify the responsible application(s)
- Expand linked system dependencies conditionally
- Classify the fault category and severity
- Route tickets to the appropriate teams

Unlike cloud-dependent systems, this application uses **entirely local AI models** — embeddings, classification, speech-to-text, and text-to-speech all run on-premises with no internet required in production.

---

## Key Features

| Feature | Description |
|---|---|
| **Semantic Matching** | `multilingual-e5-base` + `pgvector` cosine similarity to identify affected applications from natural language |
| **Conditional Dependency Mapping** | Links related systems only when the fault type matches the dependency nature (e.g. auth systems pulled in only on login faults) |
| **Multilingual Support** | Natively understands English, Hindi, and Hinglish (code-mixed) complaints |
| **LLM Guardrail & Classification** | Local Gemma model via vLLM validates, corrects STT text, and classifies fault/severity. `MOCK_LLM=True` for offline development |
| **Real-time Learning Loop** | Operator confirmations immediately improve future AI predictions via k-NN retrieval from `learning_examples` |
| **Voice Intake Pipeline** | Silero VAD -> faster-whisper STT -> LLM Guardrail -> Piper/SAPI5 TTS, over both legacy REST and WebRTC (LiveKit) |
| **SSO Authentication** | Keycloak-issued JWTs protect all API routes. Role-based access (operator / team lead) enforced server-side |
| **Human-in-the-Loop** | Operator reviews and corrects every AI prediction before the ticket is written to the database |

---

## Architecture

```
+----------------------------------------------------------+
|          AI HELP DESK - SYSTEM ARCHITECTURE              |
|     Fully Offline / Air-Gapped System (Phases 1-4)       |
+----------------------------------------------------------+

+------------------------------------------+
| LAYER 1 - PRESENTATION                   |
| React + Vite SPA                         |
|   - Complaint form (text + voice)        |
|   - AI classification review             |
|   - Ticket Dashboard & Team Queue        |
|   - Application Registry (Admin)         |
|   - Keycloak SSO login                   |
+------------------------------------------+
         |  REST/JSON         |  WebRTC audio
         v                   v
+------------------------------------------+
| LAYER 2 - API & BUSINESS LOGIC           |
| FastAPI + Python 3.11 + Uvicorn          |
|   routers/admin.py    -> App Registry    |
|   routers/tickets.py  -> Ticket CRUD     |
|   routers/voice.py    -> Voice REST/WS   |
|   routers/livekit.py  -> LiveKit tokens  |
+------------------------------------------+
                   |
                   v
+------------------------------------------+
| LAYER 3 - AI ENGINE                      |
|   llm_client.py  -> Gemma/vLLM guardrail |
|   embedder.py    -> multilingual-e5-base |
|   search.py      -> pgvector k-NN        |
|   classifier.py  -> Fault + Severity     |
|   dependencies.py-> Dependency graph     |
|   pipeline.py    -> Shared orchestrator  |
+------------------------------------------+
                   |
                   v
+------------------------------------------+
| LAYER 4 - DATA LAYER                     |
| PostgreSQL 16 + pgvector (Docker)        |
|   applications, application_symptoms     |
|   application_purposes, app_dependencies |
|   intakes, tickets, ticket_history       |
|   learning_examples (RAG memory)         |
+------------------------------------------+


END-TO-END VOICE FLOW (LiveKit/WebRTC)

 Browser <-> LiveKit Room (WebRTC)
                  |
            livekit_bridge/adapter.py
                  |
            voice/vad.py (Silero VAD)
                  |
            voice/stt.py (faster-whisper)
                  |
       voice/complaint_processor.py -> AI Pipeline
                  |
            voice/tts.py (Piper / SAPI5)
                  |
            Ticket Creation
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI 0.138, Python 3.11, Uvicorn 0.49 |
| **Frontend** | React (Vite 8), Node.js 20 LTS |
| **Database** | PostgreSQL 16 + `pgvector` (Docker) |
| **Embedding Model** | `intfloat/multilingual-e5-base` (local, 768-dim) |
| **LLM / Guardrail** | Gemma 4 via vLLM (OpenAI-compatible). `MOCK_LLM=True` for offline dev |
| **STT** | `faster-whisper-medium` (CTranslate2, GPU/CPU) |
| **TTS** | Piper TTS (ONNX, primary) -> Windows SAPI5/pyttsx3 (fallback) |
| **VAD** | Silero VAD (ONNX, real-time speech detection) |
| **WebRTC** | LiveKit (self-hosted, Docker, ports 7880/7881/7882) |
| **Auth / SSO** | Keycloak 24 (Docker, port 8080) |
| **Containers** | Docker Compose |

---

## Repository Layout

```
AI-HELP-DESK/
|
+-- docker-compose.yml           # PostgreSQL+pgvector, Keycloak, LiveKit
+-- livekit-config.yaml          # Self-hosted LiveKit server config
+-- keycloak-realm-export.json   # Pre-configured Keycloak realm (auto-imported)
+-- generate_keycloak_json.py    # Regenerates Keycloak realm for new environments
+-- replace_ips.py               # Rewrites host IPs across all config files
|
+-- backend/
|   +-- .env                     # Runtime overrides (DB URL, LiveKit URL, keys)
|   +-- requirements.txt         # Python dependencies (CUDA 12.8 build)
|   +-- main.py                  # App entry point, router mounting
|   +-- config.py                # Pydantic Settings (defaults + .env overrides)
|   +-- database.py              # SQLModel engine & session management
|   +-- models.py                # SQLModel table schemas (ORM)
|   +-- schemas.py               # Pydantic API request/response validation
|   +-- voice_schemas.py         # Pydantic schemas for Voice Layer API
|   +-- security.py              # JWT verification via Keycloak JWKS
|   +-- seed_db.py               # Seeds DB with apps, symptoms, embeddings
|   +-- download_models.py       # Downloads faster-whisper weights
|   +-- download_piper.py        # Downloads Piper TTS voice ONNX models
|   +-- download_weights.py      # Downloads embedding model weights
|   |
|   +-- local_models/            # Offline model weights (git-ignored)
|   |   +-- multilingual-e5-base/   # Sentence embedding model
|   |   +-- whisper-medium-ct2/     # faster-whisper STT model
|   |   +-- silero_vad.onnx         # Voice Activity Detection model
|   |   +-- piper/                  # Piper TTS voice ONNX files
|   |
|   +-- voice/                   # Phase 2 - Voice Layer
|   |   +-- vad.py               # Silero VAD - speech start/end detection
|   |   +-- stt.py               # Speech-to-Text (faster-whisper)
|   |   +-- tts.py               # Text-to-Speech (Piper primary, SAPI5 fallback)
|   |   +-- complaint_processor.py  # Shared pipeline: REST + LiveKit paths
|   |   +-- session.py           # Voice session state machine
|   |   +-- validators.py        # Service number validation
|   |   +-- audio.py             # Audio format conversion
|   |   +-- prompts.py           # Pre-recorded static prompt management
|   |   +-- static_prompts/      # Pre-generated WAV prompt files
|   |
|   +-- livekit_bridge/          # Phase 4 - WebRTC Media Transport
|   |   +-- adapter.py           # LiveKit <-> Voice Layer integration
|   |   +-- client.py            # LiveKit Room Service admin API wrapper
|   |   +-- connection_manager.py  # Agent room join/leave/reconnect
|   |   +-- room_manager.py      # Room-to-session registry
|   |   +-- token_manager.py     # Short-lived JWTs for room participants
|   |
|   +-- services/                # AI & Business Logic
|   |   +-- embedder.py          # Multilingual pgvector embeddings
|   |   +-- classifier.py        # Fault type & severity classification
|   |   +-- llm_client.py        # Gemma/vLLM guardrail + classification client
|   |   +-- search.py            # Candidate ranking & learning loop retrieval
|   |   +-- dependencies.py      # Conditional dependency graph expansion
|   |   +-- pipeline.py          # AI pipeline orchestrator (shared)
|   |
|   +-- routers/                 # API Endpoints
|       +-- admin.py             # Application Registry CRUD
|       +-- tickets.py           # Intake submission & Ticket lifecycle
|       +-- voice.py             # Voice layer (REST/WebSocket)
|       +-- livekit.py           # LiveKit token, status, event stream
|
+-- frontend/
    +-- .env                     # VITE_API_URL, VITE_WS_URL, VITE_KEYCLOAK_URL
    +-- package.json
    +-- src/
        +-- App.jsx              # Main router
        +-- auth.config.js       # Keycloak OIDC config (reads VITE_KEYCLOAK_URL)
        +-- useCurrentUser.js    # Hook: logged-in service_no & role
        +-- api/
        |   +-- axios.js         # Axios instance (base URL + auth header)
        |   +-- registry.api.js  # Application registry API calls
        |   +-- tickets.api.js   # Ticket API calls
        |   +-- voice.api.js     # Voice session API calls
        +-- components/
        |   +-- layout/
        |   |   +-- Sidebar.jsx, Topbar.jsx
        |   +-- voice/
        |   |   +-- VoiceSessionPanel.jsx      # Voice session state machine UI
        |   |   +-- LiveKitAudioTransport.jsx  # WebRTC room connection
        |   |   +-- VoiceRecorder.jsx          # Mic capture (legacy REST path)
        |   |   +-- TranscriptPanel.jsx        # STT transcript display
        |   +-- ui/
        |       +-- Badge.jsx, ErrorMessage.jsx, LoadingSpinner.jsx, StatCard.jsx
        +-- pages/
        |   +-- LoginPage.jsx        # Keycloak login
        |   +-- Dashboard.jsx        # Home dashboard
        |   +-- SubmitComplaint.jsx  # Complaint form (text + voice)
        |   +-- ClassifyReview.jsx   # AI prediction review & confirmation
        |   +-- TicketList.jsx       # All tickets
        |   +-- TicketDetail.jsx     # Single ticket detail + history
        |   +-- TeamQueue.jsx        # Team-lead queue view
        |   +-- Registry.jsx         # Application registry (admin)
        +-- constants/
            +-- enums.js            # Fault types, severity, status enums
```

---

## Database Schema

| Table | Purpose |
|---|---|
| `applications` | Master registry of all enterprise software applications |
| `application_symptoms` | Known symptoms per application (768-dim vector) |
| `application_purposes` | Business purpose descriptions per application (768-dim vector) |
| `application_dependencies` | Directional dependency links between applications |
| `intakes` | Raw complaint text before ticket creation |
| `tickets` | Main ticket table (status, fault, severity, assignee) |
| `ticket_related_apps` | Multi-application incidents |
| `ticket_history` | Full audit trail of every ticket status change |
| `learning_examples` | AI learning memory with operator-confirmed labels (vector + k-NN) |
| `user_roles` | Maps `service_no` to `role` (operator / team-lead) |
| `classification_config` | Zero-shot label descriptions for fault types and severities |

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| **Docker Desktop** | Latest | Must be running before Step 1 |
| **Python** | 3.11.x | Use `python --version` to verify |
| **Node.js** | 18 or 20 LTS | Use `node --version` to verify |
| **CUDA** (optional) | 12.8+ | For GPU-accelerated STT/VAD. CPU fallback works. |

---

## Step-by-Step Setup

### Step 1 - Start Docker Containers

```powershell
# From the project root (AI-HELP-DESK/)
docker compose up -d

# Verify all three containers are running
docker ps
```

Expect to see: `helpdesk-db` (5433), `helpdesk-keycloak` (8080), `helpdesk-livekit` (7880/7881/7882)

---

### Step 2 - Configure Your IP Address

> **Important**: Set your machine's LAN IP in all config files before starting.

**Option A - Automatic (recommended):**

```powershell
python replace_ips.py
```

This rewrites the IP in `backend/.env`, `frontend/.env`, and `livekit-config.yaml` automatically.

**Option B - Manual:** Edit each file and replace `192.168.x.x` with your actual LAN IP:
- `backend/.env` -> `DATABASE_URL`, `KEYCLOAK_URL`, `LIVEKIT_URL`
- `frontend/.env` -> `VITE_API_URL`, `VITE_WS_URL`, `VITE_KEYCLOAK_URL`
- `livekit-config.yaml` -> `node_ip`

After editing `livekit-config.yaml`, restart the LiveKit container:

```powershell
docker restart helpdesk-livekit
```

---

### Step 3 - Python Virtual Environment

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

---

### Step 4 - Download AI Model Weights

```powershell
# Inside backend/ with venv activated

# Embedding model (multilingual-e5-base, ~1.1 GB)
python download_weights.py

# Speech-to-Text model (faster-whisper-medium, ~1.5 GB)
python download_models.py

# Piper TTS voice model (en_US-lessac-medium, ~65 MB)
python download_piper.py
```

> The Silero VAD model (`silero_vad.onnx`) is already included in `local_models/`.

---

### Step 5 - Seed the Database

```powershell
# Inside backend/ with venv activated
python seed_db.py
```

Expected output: `Database successfully seeded with AI vectors!`

---

### Step 6 - Install Frontend Dependencies

```powershell
cd frontend
npm install
```

---

## Environment Configuration

### `backend/.env`

```ini
# Database (PostgreSQL in Docker)
DATABASE_URL=postgresql://postgres:postgres@192.168.x.x:5433/helpdesk_db

# Keycloak SSO
KEYCLOAK_URL=http://192.168.x.x:8080

# LiveKit WebRTC Server
LIVEKIT_URL=ws://192.168.x.x:7880
LIVEKIT_API_KEY=helpdesk_key
LIVEKIT_API_SECRET=helpdesk_secret_change_in_production
LIVEKIT_ENABLED=True

# AI Model Mode
# True  = Mock LLM responses (no GPU required, for development)
# False = Real vLLM server required (production/air-gapped GPU machine)
MOCK_LLM=True

# HuggingFace download control
# Set to 1 to block all internet model downloads (true air-gapped mode)
TRANSFORMERS_OFFLINE=0
HF_HUB_OFFLINE=0

# Voice AI hardware
# "cuda" if NVIDIA GPU available, "cpu" otherwise
VAD_DEVICE=cuda
STT_DEVICE=auto
```

### `frontend/.env`

```ini
VITE_API_URL=http://192.168.x.x:8001
VITE_WS_URL=ws://192.168.x.x:8001
VITE_KEYCLOAK_URL=http://192.168.x.x:8080
```

### How `config.py` and `.env` interact

`config.py` defines sensible defaults (all pointing to `localhost`) for single-machine development. The `backend/.env` file **overrides** these defaults for LAN or multi-machine deployments. You should never need to edit `config.py` directly — use `.env` instead.

---

## Running the Project

Open **two separate terminals**:

**Terminal 1 - Backend:**

```powershell
cd backend
.\venv\Scripts\activate
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

**Terminal 2 - Frontend:**

```powershell
cd frontend
npm run dev -- --host
```

The `--host` flag exposes the frontend to other machines on the LAN.

| Access point | URL |
|---|---|
| Same machine | `http://localhost:5173` |
| Other LAN machines | `http://192.168.x.x:5173` |
| Backend API Docs | `http://localhost:8001/docs` |

---

## Downloading AI Models

| Model | Script | Size | Destination |
|---|---|---|---|
| Embedding (multilingual-e5-base) | `python download_weights.py` | ~1.1 GB | `local_models/multilingual-e5-base/` |
| STT (faster-whisper-medium) | `python download_models.py` | ~1.5 GB | `local_models/whisper-medium-ct2/` |
| TTS (Piper en_US-lessac) | `python download_piper.py` | ~65 MB | `local_models/piper/` |
| VAD (Silero) | Pre-bundled | ~2.3 MB | `local_models/silero_vad.onnx` |

To use the **Hindi TTS voice**, edit `download_piper.py` and change the voice name to `hi_IN-swara-medium`.

---

## Voice Layer

### Two Modes

| Mode | How it works | Activated by |
|---|---|---|
| **LiveKit / WebRTC** | Browser streams audio over WebRTC to the LiveKit server. The backend AI agent joins the room and processes speech in real time. | `LIVEKIT_ENABLED=True` in `backend/.env` |
| **Legacy REST** | Browser records audio and uploads WAV files via HTTP POST. | Automatic fallback if LiveKit is unavailable |

### LiveKit Config (`livekit-config.yaml`)

```yaml
port: 7880
rtc:
  tcp_port: 7881
  udp_port: 7882
  use_external_ip: false
  node_ip: 192.168.x.x    # MUST match your machine LAN IP
keys:
  helpdesk_key: helpdesk_secret_change_in_production
turn:
  enabled: false
```

After editing, run: `docker restart helpdesk-livekit`

### TTS Backend Priority

1. **Piper TTS** (primary) - if `local_models/piper/en_US-lessac-medium.onnx` exists
2. **Windows SAPI5** via `pyttsx3` (fallback) - always available on Windows

Install Piper:

```powershell
pip install piper-tts
python download_piper.py
```

Verify on backend startup:
```
INFO: voice.tts: TTS backend: Piper (en_US-lessac-medium)
```

---

## Troubleshooting

### `ERR_CONNECTION_REFUSED` on `/api/me`

Frontend cannot reach the backend. Fix:
1. Ensure backend is running on port **8001**
2. Check `VITE_API_URL=http://<your-ip>:8001` in `frontend/.env`
3. Restart the Vite dev server after changing `.env`

### WebSocket fails on `/api/livekit/events/...`

1. Ensure the backend is running and accessible
2. Check `VITE_WS_URL` in `frontend/.env` matches the backend host and port

### `publishing rejected as engine not connected within timeout`

LiveKit ICE negotiation failure. The LiveKit Docker container is advertising the wrong IP.

Fix:
1. Set `node_ip: <your-LAN-IP>` in `livekit-config.yaml`
2. Run `docker restart helpdesk-livekit`

### `500 Internal Server Error` on complaint submission

Embedding model failed to load. Fix:
1. Check `backend/local_models/multilingual-e5-base/model.safetensors` exists
2. Set `TRANSFORMERS_OFFLINE=0` and `HF_HUB_OFFLINE=0` in `backend/.env` to allow auto-download
3. Check the backend terminal for the full Python traceback

### Keycloak login redirects to wrong URL

Ensure `frontend/.env` has the correct IP:
```ini
VITE_KEYCLOAK_URL=http://192.168.x.x:8080
```
Restart the Vite dev server after changing.

### VAD crashes on startup

`VAD_DEVICE=cuda` is set but no CUDA GPU is available. Fix:
```ini
VAD_DEVICE=cpu
```

---

## Service Summary

| Service | Default URL | Credentials |
|---|---|---|
| **Frontend UI** | `http://localhost:5173` | Keycloak login |
| **Backend API** | `http://localhost:8001` | JWT Bearer token |
| **Backend API Docs** | `http://localhost:8001/docs` | None (dev mode) |
| **Keycloak Admin Console** | `http://localhost:8080` | `admin` / `admin` |
| **PostgreSQL** | `localhost:5433` | `postgres` / `postgres` |
| **LiveKit Server** | `ws://localhost:7880` | API key/secret in `backend/.env` |

