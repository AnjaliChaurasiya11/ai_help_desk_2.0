/**
 * useSileroVAD.js — Barge-In via Backend Silero VAD (WebSocket)
 * ==============================================================
 * Streams microphone audio to the existing backend WebSocket endpoint
 * (/api/voice/ws/vad-stream) which runs the same Silero VAD model already
 * used by the recording pipeline.  When the backend sends a "speech_started"
 * event, onSpeechDetected fires — stopping TTS playback for instant barge-in.
 *
 * Protocol (matches backend /ws/vad-stream):
 *   Client → Server: binary chunks of 16-bit signed PCM at 16 kHz mono
 *   Server → Client: JSON  { "event": "listening" | "speech_started" |
 *                             "end_of_speech" | "timeout" | "error" }
 *
 * Why WebSocket-based instead of energy/AnalyserNode:
 *   • Reuses the existing Silero model — no second VAD implementation to maintain
 *   • More robust in noisy environments (same sensitivity as recording pipeline)
 *   • Consistent speech onset thresholds for both capture and barge-in
 *
 * Browser → Backend audio chain:
 *   getUserMedia → AudioContext (16 kHz) → ScriptProcessorNode (1024 samples)
 *   → Int16 PCM conversion → WebSocket.send(binary)
 *
 * Fallback:
 *   If WebSocket fails to connect (network error, server down), the hook
 *   silently stops — TTS continues uninterrupted.  No crash.
 *
 * Usage
 * ─────
 *   const { isConnected } = useSileroVAD({
 *     sessionId,
 *     active: audioPlaying && !isProcessing,
 *     onSpeechDetected: handleBargeIn,
 *     wsBaseUrl: 'ws://127.0.0.1:8001/api/voice',
 *   });
 */

import { useEffect, useRef, useState, useCallback } from 'react';

// Silero VAD expects 16 kHz mono audio
const TARGET_SAMPLE_RATE = 16000;
// ScriptProcessor buffer: 1024 samples @ 16 kHz ≈ 64 ms per chunk
// (small enough for low barge-in latency, large enough to avoid GC jank)
const SCRIPT_PROC_BUFFER = 1024;

export default function useSileroVAD({
  sessionId,
  active = false,
  onSpeechDetected,
  wsBaseUrl = 'ws://127.0.0.1:8001/api/voice',
} = {}) {
  const [isConnected, setIsConnected] = useState(false);

  const wsRef            = useRef(null);
  const streamRef        = useRef(null);
  const audioCtxRef      = useRef(null);
  const processorRef     = useRef(null);
  const sourceRef        = useRef(null);
  const isMountedRef     = useRef(true);
  // Cooldown guard — prevents duplicate barge-in events from the same utterance
  const cooldownRef      = useRef(false);

  /** Convert Float32 samples (-1..1) to Int16 PCM bytes for the backend. */
  const float32ToInt16 = useCallback((float32Array) => {
    const int16 = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16.buffer;
  }, []);

  /** Open WebSocket + mic stream + ScriptProcessorNode pipeline. */
  const start = useCallback(async () => {
    if (wsRef.current || !isMountedRef.current) return;

    // ── 1. Open WebSocket ────────────────────────────────────────────
    const url = sessionId
      ? `${wsBaseUrl}/ws/vad-stream?session_id=${encodeURIComponent(sessionId)}`
      : `${wsBaseUrl}/ws/vad-stream`;

    let ws;
    try {
      ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
    } catch (err) {
      console.warn('[useSileroVAD] WebSocket construction failed:', err);
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      if (isMountedRef.current) {
        console.debug('[useSileroVAD] WebSocket connected');
        setIsConnected(true);
      }
    };

    ws.onmessage = (event) => {
      if (!isMountedRef.current) return;
      try {
        const msg = JSON.parse(event.data);
        if (msg.event === 'speech_started' && !cooldownRef.current) {
          console.log('[useSileroVAD] speech_started — firing barge-in');
          cooldownRef.current = true;
          if (onSpeechDetected) onSpeechDetected();
          // Reset cooldown after 2 s (Silero will re-detect on next utterance)
          setTimeout(() => { cooldownRef.current = false; }, 2000);
        }
        // "end_of_speech" / "timeout" during barge-in monitoring are ignored —
        // we only care about the start of speech, not the end.
      } catch (_) {
        // Non-JSON frame — ignore
      }
    };

    ws.onerror = (err) => {
      console.warn('[useSileroVAD] WebSocket error:', err);
    };

    ws.onclose = () => {
      wsRef.current = null;
      if (isMountedRef.current) setIsConnected(false);
    };

    // ── 2. Acquire microphone ────────────────────────────────────────
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (err) {
      console.warn('[useSileroVAD] Could not acquire microphone:', err);
      ws.close();
      wsRef.current = null;
      return;
    }
    streamRef.current = stream;

    // ── 3. Audio routing: mic → 16 kHz → Int16 PCM → WebSocket ─────
    // We need a 16 kHz AudioContext to match what Silero expects.
    // The browser's native sample rate is typically 44100/48000 Hz —
    // we create a context at 16000 Hz so the engine down-samples for us.
    const ctx = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
    audioCtxRef.current = ctx;

    const source = ctx.createMediaStreamSource(stream);
    sourceRef.current = source;

    // ScriptProcessorNode is deprecated but remains the most reliable
    // cross-browser way to intercept raw PCM.  AudioWorklet is the modern
    // alternative but requires an extra fetch for the Worklet module file.
    // For barge-in monitoring (low-complexity, short-lived) SP is fine.
    // eslint-disable-next-line no-undef
    const processor = ctx.createScriptProcessor(SCRIPT_PROC_BUFFER, 1, 1);
    processorRef.current = processor;

    processor.onaudioprocess = (e) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      const float32 = e.inputBuffer.getChannelData(0);
      const pcmBytes = float32ToInt16(float32);
      wsRef.current.send(pcmBytes);
    };

    source.connect(processor);
    processor.connect(ctx.destination);  // required to keep the node active
  }, [sessionId, wsBaseUrl, onSpeechDetected, float32ToInt16]);

  /** Tear down all resources cleanly. */
  const stop = useCallback(() => {
    // Disconnect audio graph
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current.onaudioprocess = null;
      processorRef.current = null;
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    // Stop mic tracks
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    // Close WebSocket
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    cooldownRef.current = false;
    setIsConnected(false);
  }, []);

  // ── Effect: start/stop based on `active` flag ─────────────────────
  useEffect(() => {
    isMountedRef.current = true;

    if (active) {
      start();
    } else {
      stop();
    }

    return () => {
      isMountedRef.current = false;
      stop();
    };
  }, [active, start, stop]);

  return { isConnected };
}
