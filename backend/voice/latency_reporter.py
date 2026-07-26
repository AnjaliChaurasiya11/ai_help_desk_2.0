"""
voice/latency_reporter.py — End-to-End Latency Reporter
========================================================
Produces a single, formatted per-request latency report at the end of
every voice pipeline call.  Both the service-number and complaint
endpoints import this module so all reports are structurally identical.

Report includes:
  - Stage timings in ms and percentage of total
  - Whisper diagnostics (model, beam size, audio duration, VAD speech
    duration, detected language, STT decode time)
  - Bottleneck identification with a concrete optimisation hint

Usage
-----
    from voice.latency_reporter import LatencyReport, emit_report

    report = LatencyReport(endpoint="service-number")
    report.mark("audio_read", t_read_ms)
    report.mark("audio_conversion", t_conv_ms)
    report.mark("vad", t_vad_ms)
    report.mark("stt", t_stt_ms)
    report.mark("svc_extraction", t_val_ms)
    report.set_whisper_info(model_size, beam_size, audio_dur, speech_dur, lang, decode_ms)
    emit_report(report, logger)
"""

import logging
import datetime
from dataclasses import dataclass, field
from typing import Dict, Optional

from config import settings

logger = logging.getLogger("voice.latency_reporter")


# Ordered list of all stages in display order.
# Each entry is (key, display_label).
# A stage that is not populated for a given endpoint will be skipped.
_STAGE_ORDER = [
    ("audio_read",      "Audio Capture     "),
    ("audio_conversion","Audio Conversion  "),
    ("vad",             "VAD (silence det) "),
    ("stt",             "STT (Whisper)     "),
    ("svc_extraction",  "Svc# Extraction   "),
    ("guardrail_llm",   "Guardrail (LLM)   "),
    ("embedding",       "Embedding         "),
    ("vector_search",   "Vector Search     "),
    ("classification",  "Classification    "),
    ("dependencies",    "Dependencies      "),
    ("database",        "Database          "),
    ("tts_synthesis",   "TTS Synthesis     "),
    ("audio_streaming", "Audio Streaming   "),
]

# Optimisation recommendations keyed by bottleneck stage
_HINTS: Dict[str, str] = {
    "stt":             "Benchmark whisper-small (set STT_MODEL_SIZE=small in .env) or reduce STT_BEAM_SIZE to 1.",
    "guardrail_llm":   "Reduce LLM temperature, use a smaller model, or cache repeated inputs.",
    "embedding":       "Check embedder model size; consider int8 quantisation.",
    "vector_search":   "Add a HNSW index to the application_embeddings table.",
    "classification":  "Use a lighter classifier or reduce LLM context length.",
    "vad":             "Tune VAD_MIN_SILENCE_MS downward (currently safe to try 300–500 ms).",
    "audio_conversion":"Check ffmpeg version; pre-process audio on the client side.",
    "database":        "Add a DB connection pool or index the intake table.",
    "tts_synthesis":   "Switch to pre-recorded static prompts or cache frequent TTS outputs.",
}


@dataclass
class WhisperInfo:
    """Diagnostic data extracted from the STT engine after each call."""
    model_size:    str   = ""
    beam_size:     int   = 1
    audio_dur_s:   float = 0.0   # total audio duration fed to Whisper (seconds)
    speech_dur_s:  float = 0.0   # speech duration after VAD filtering (seconds)
    language:      str   = ""
    decode_ms:     float = 0.0   # Whisper decode time reported by faster-whisper


@dataclass
class LatencyReport:
    """Accumulates per-stage timings for one voice pipeline request."""
    endpoint:    str                      # e.g. "service-number" or "complaint"
    session_id:  str  = ""               # voice session UUID (for log correlation)
    fsm_state:   str  = ""               # SessionState value at report time
    timestamp:   str  = field(
        default_factory=lambda: datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    )
    stages:      Dict[str, float]         = field(default_factory=dict)
    whisper:     WhisperInfo              = field(default_factory=WhisperInfo)

    def mark(self, stage_key: str, duration_ms: float) -> None:
        """Record the duration of a named stage in milliseconds."""
        self.stages[stage_key] = max(0.0, duration_ms)

    def set_whisper_info(
        self,
        model_size:   str,
        beam_size:    int,
        audio_dur_s:  float,
        speech_dur_s: float,
        language:     str,
        decode_ms:    float,
    ) -> None:
        self.whisper = WhisperInfo(
            model_size=model_size,
            beam_size=beam_size,
            audio_dur_s=audio_dur_s,
            speech_dur_s=speech_dur_s,
            language=language,
            decode_ms=decode_ms,
        )

    @property
    def total_ms(self) -> float:
        return sum(self.stages.values())

    def bottleneck(self) -> Optional[str]:
        """Return the key of the slowest stage, or None if no stages recorded."""
        if not self.stages:
            return None
        return max(self.stages, key=lambda k: self.stages[k])


def emit_report(report: LatencyReport, log: Optional[logging.Logger] = None) -> None:
    """
    Format and emit the complete latency report via the given logger.

    Falls back to the module-level logger if none is provided.
    """
    if not settings.ENABLE_LATENCY_PROFILING:
        return

    log = log or logger
    total = report.total_ms or 1.0  # avoid div-by-zero

    W = 56  # line width for the box

    def pct(ms: float) -> str:
        return f"{(ms / total) * 100:4.1f}%"

    # ── Formatting for Complaint Pipeline ───────────────────────────
    if report.endpoint == "complaint":
        lines = [
            f"\n========== COMPLAINT PIPELINE ==========",
            f"Complaint Length        : {report.whisper.audio_dur_s} chars" if not getattr(report, "complaint_len", None) else f"Complaint Length        : {report.complaint_len} chars",
            f"LLM Verification        : {report.stages.get('guardrail_llm', 0):.0f} ms",
            f"Embedding               : {report.stages.get('embedding', 0):.0f} ms",
            f"Vector Search           : {report.stages.get('vector_search', 0):.0f} ms",
            f"Classification LLM      : {report.stages.get('classification', 0):.0f} ms",
            f"Dependency Lookup       : {report.stages.get('dependencies', 0):.0f} ms",
            f"Database                : {report.stages.get('database', 0):.0f} ms",
            f"Response Generation     : {report.stages.get('response_generation', 'N/A')} ms",
            f"TTS                     : {report.stages.get('tts_synthesis', 'N/A')} ms",
            f"Audio Publish           : {report.stages.get('audio_streaming', 'N/A')} ms",
            f"TOTAL                   : {total:.0f} ms",
            f"========================================"
        ]
        log.info("\n".join(lines))
        return

    # ── Formatting for Service Number (and others) ──────────────────
    lines = [
        f"\n{'=' * W}",
        f"  VOICE LATENCY REPORT  [{report.endpoint.upper()}]",
        f"  {report.timestamp}  session={report.session_id or '(unknown)'}  state={report.fsm_state or '(unknown)'}",
        f"{'=' * W}",
        f"  {'Stage':<22}  {'ms':>7}  {'%':>6}",
        f"  {'-' * 22}  {'-' * 7}  {'-' * 6}",
    ]

    for key, label in _STAGE_ORDER:
        ms = report.stages.get(key)
        if ms is None:
            continue
        lines.append(f"  {label:<22}  {ms:>7.0f}  {pct(ms):>6}")

    lines += [
        f"  {'─' * 37}",
        f"  {'TOTAL':<22}  {total:>7.0f}  {'100.0%':>6}",
        f"{'─' * W}",
    ]

    # ── Whisper Diagnostics ──────────────────────────────────────────
    wi = report.whisper
    if wi.model_size:
        lines += [
            f"  WHISPER DIAGNOSTICS",
            f"  {'Model':<22}  whisper-{wi.model_size}",
            f"  {'Beam size':<22}  {wi.beam_size}",
            f"  {'Input duration':<22}  {wi.audio_dur_s:.2f}s",
            f"  {'Speech after VAD':<22}  {wi.speech_dur_s:.2f}s  "
            f"({100.0 * wi.speech_dur_s / max(wi.audio_dur_s, 0.001):.0f}% of audio)",
            f"  {'Detected language':<22}  {wi.language or '(auto)'}",
            f"  {'STT decode time':<22}  {wi.decode_ms:.0f} ms",
            f"{'─' * W}",
        ]

    # ── Bottleneck Analysis ──────────────────────────────────────────
    bn = report.bottleneck()
    if bn:
        bn_ms = report.stages[bn]
        bn_label = next((lbl for k, lbl in _STAGE_ORDER if k == bn), bn).strip()
        hint = _HINTS.get(bn, "Review this stage for optimisation opportunities.")
        lines += [
            f"  BOTTLENECK",
            f"  {bn_label} = {bn_ms:.0f} ms ({pct(bn_ms)} of total)",
            f"",
            f"  Recommendation:",
            f"  {hint}",
            f"{'=' * W}",
        ]
    else:
        lines.append(f"{'=' * W}")

    log.info("\n".join(lines))
