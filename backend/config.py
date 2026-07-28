from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):

    # -- Database ----------------------------
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/helpdesk_db"

    # -- Server ------------------------------
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    DEBUG: bool = True

    # -- App Info ----------------------------
    APP_NAME: str = "AI Help Desk"
    VERSION: str = "1.0.0"

    # -- AI Models (Air-gapped local paths) --
    MODEL_PATH: str = "./local_models/multilingual-e5-base"
    OLLAMA_URL: str = "http://localhost:11434"

    # -- Offline Mode (HuggingFace) ----------
    TRANSFORMERS_OFFLINE: str = "1"
    HF_HUB_OFFLINE: str = "1"

    # -- CORS -------------------------------------
    # Explicit list of allowed browser origins.
    # "allow_origins=['*']" conflicts with "allow_credentials=True" per the
    # Fetch spec and is rejected by browsers on credentialed requests.
    # Add your production frontend URL here or set CORS_ORIGINS in .env.
    # Example .env value:
    #   CORS_ORIGINS=["http://192.168.1.10:5173","https://helpdesk.example.mil"]
    CORS_ORIGINS: list = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://192.168.252.172:5173",   # LAN dev host (matches frontend/.env IP)
    ]

    # -- Auth (Keycloak) ---------------------
    # Set to True to enforce JWT tokens on all routes.
    # Keep False during development if Keycloak is not running.
    AUTH_ENABLED: bool = False
    KEYCLOAK_URL: str = "http://localhost:8080"
    KEYCLOAK_REALM: str = "ai-helpdesk"
    KEYCLOAK_CLIENT_ID: str = "helpdesk-frontend"

    # -- Phase 2: Voice Layer ----------------
    # STT (Speech-to-Text) — faster-whisper
    STT_MODEL_SIZE: str = "medium"
    STT_DEVICE: str = "auto"          # "auto", "cuda", "cpu"
    STT_COMPUTE_TYPE: str = "default" # "default", "float16", "int8", "float32"
    STT_KEEP_MODEL_LOADED: bool = True # True = keep model resident (no first-call reload penalty)
    STT_BEAM_SIZE: int = 1            # 1 = greedy (fastest), 5 = more accurate but ~2x slower

    # Language hints for Whisper — None/"" means auto-detect per utterance.
    # Set to "en" to skip language identification and gain ~50 ms per call.
    # Our users may speak English, Hindi, or Hinglish, so auto-detect is the
    # safe default.  Switch per-context via .env once real latency data exists.
    STT_LANGUAGE_SVC_NUM: str = ""    # "" = auto-detect for service-number capture
    STT_LANGUAGE_COMPLAINT: str = ""  # "" = auto-detect for complaint transcription

    # VAD parameters — passed directly to faster-whisper's built-in Silero VAD.
    # Production defaults are kept at faster-whisper's own defaults so we never
    # truncate slower speakers.  Tune these after reviewing real latency reports.
    #   min_silence_duration_ms : ms of silence to mark end-of-speech segment
    #   speech_pad_ms           : padding added before and after detected speech
    #   threshold               : Silero speech probability threshold (0.0–1.0)
    VAD_MIN_SILENCE_MS: int = 2000    # faster-whisper default
    VAD_SPEECH_PAD_MS: int = 400      # faster-whisper default
    VAD_THRESHOLD: float = 0.5        # faster-whisper default

    # Streaming VAD (StreamingEndpointDetector) — controls how long the browser
    # keeps the mic open before auto-stopping.  These do NOT affect STT accuracy.
    VAD_STREAMING_SILENCE_MS: int = 800   # original default (unchanged)
    VAD_STREAMING_MAX_WAIT_MS: int = 8000 # original default (unchanged)

    # VAD (Voice Activity Detection) — Silero VAD
    VAD_DEVICE: str = "cuda"           # "cpu" on home PC, "cuda" on offline GPU PC



    # TTS (Text-to-Speech)
    TTS_BACKEND: str = "auto"          # "piper", "sapi5", "auto"

    # Voice session
    VOICE_SESSION_TTL: int = 1800      # seconds (30 min default)
    VOICE_MAX_SVC_RETRIES: int = 3
    ENABLE_LATENCY_PROFILING: bool = True # Toggle comprehensive latency reports

    # -- AI Reasoning Layer (context-aware classification) --------
    # When True the single classify+reason LLM call receives retrieved
    # application candidates, symptoms, and purposes as context and
    # returns a richer 7-field response.
    # Set False to revert to the 2-field classify-only output with zero
    # latency change.
    ENABLE_AI_REASONING: bool = True

    # Deterministic follow-up gate: if the LLM's confidence score is
    # below this threshold the pipeline overrides needs_followup=True
    # regardless of what the model returned.  Set to 0.0 to never ask.
    FOLLOWUP_CONFIDENCE_THRESHOLD: float = 0.65

    # Maximum audio upload size for all voice endpoints (service-number,
    # confirm-audio, another-complaint, complaint). Requests exceeding this
    # size are rejected with HTTP 413 before any RAM is allocated for
    # STT/VAD processing, preventing memory exhaustion attacks.
    # Default: 10 MB — comfortably above a 2-min opus/webm recording (~2 MB)
    # but well below a problematic multi-GB payload.
    # Override in .env: VOICE_MAX_AUDIO_SIZE_BYTES=5242880  (5 MB)
    VOICE_MAX_AUDIO_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB

    # -- Phase 4: LiveKit Media Transport (runtime backend flag) -----
    # Set LIVEKIT_ENABLED=true to activate real-time WebRTC media transport.
    # When false (default), the existing record/upload REST audio path
    # remains the only path. The frontend reads this flag from the
    # /voice/start response (no build-time env var) and decides whether
    # to join a LiveKit room or use the legacy path.
    LIVEKIT_ENABLED: bool = True
    LIVEKIT_URL: str = "ws://localhost:7880"
    LIVEKIT_API_KEY: str = "helpdesk_key"
    LIVEKIT_API_SECRET: str = "helpdesk_secret_change_in_production"
    # Identity used by the AI agent when joining a room as a participant.
    LIVEKIT_AGENT_IDENTITY: str = "ai-helpdesk-agent"
    # STT concurrency: single lock protects the shared SpeechToTextEngine.
    # Future: increase to allow a pool when concurrency becomes a bottleneck.
    LIVEKIT_STT_POOL_SIZE: int = 1

    # -- Phase 3: LLM Guardrail & Classification ----
    # The vLLM server URL exposed by the air-gapped environment.

    # VLLM_API_URL: str = "http://localhost:8010/v1"
    # VLLM_MODEL_NAME: str = "g"
    VLLM_API_URL: str = "http://localhost:11434/v1"
    VLLM_MODEL_NAME: str = "qwen2.5:7b" 

    # API key if the vLLM server requires one (leave blank if not needed).
    VLLM_API_KEY: str = "none"
    # --- OFFLINE DEVELOPMENT FLAG ---
    # Set to True at home to skip LLM network calls entirely.
    # The system will return a realistic mock response so the UI can be built
    # and tested without needing access to the air-gapped vLLM server.
    MOCK_LLM: bool = False
    
    # Maximum number of clarification attempts before marking intake as unable_to_identify
    MAX_CLARIFICATION_ATTEMPTS: int = 3

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()
