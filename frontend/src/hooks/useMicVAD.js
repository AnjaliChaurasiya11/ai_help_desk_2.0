/**
 * useMicVAD.js — Continuous Microphone VAD Hook
 * ================================================
 * Monitors the microphone using Web Audio API `AnalyserNode` even while TTS
 * is playing.  Calls `onSpeechDetected` the moment the energy level crosses
 * the threshold — enabling instant barge-in without waiting for TTS to finish.
 *
 * Design notes
 * ─────────────
 * • Uses `requestAnimationFrame` (not a setInterval) for zero-overhead
 *   monitoring — the loop stops itself when `active` is false.
 * • `getUserMedia` is called once and the stream is kept alive for the
 *   duration of the hook's lifetime.  We do NOT record audio here; the
 *   existing VoiceRecorder.jsx owns the MediaRecorder.
 * • The `cooldownMs` guard prevents repeated firing when the user is still
 *   speaking — `onSpeechDetected` fires once per barge-in event.
 *
 * Usage
 * ─────
 *   const { isListening, bargedIn } = useMicVAD({
 *     active: audioPlaying,                 // monitor only while TTS plays
 *     onSpeechDetected: stopAllAudio,       // called when speech is detected
 *     threshold: 8,                         // AnalyserNode energy threshold
 *     cooldownMs: 1500,                     // minimum ms between events
 *   });
 */

import { useEffect, useRef, useState, useCallback } from 'react';

export default function useMicVAD({
  active = false,
  onSpeechDetected,
  threshold = 8,       // out of 0–255 from AnalyserNode
  cooldownMs = 1500,   // ignore subsequent triggers within this window
} = {}) {
  const [isListening, setIsListening] = useState(false);
  const [bargedIn, setBargedIn]       = useState(false);

  const streamRef      = useRef(null);
  const audioCtxRef    = useRef(null);
  const analyserRef    = useRef(null);
  const rafRef         = useRef(null);
  const cooldownRef    = useRef(false);
  const isMountedRef   = useRef(true);

  /** Acquire mic stream (called once, reused). */
  const acquireMic = useCallback(async () => {
    if (streamRef.current) return true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      streamRef.current = stream;
      const ctx = new AudioContext();
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      audioCtxRef.current = ctx;
      analyserRef.current = analyser;
      return true;
    } catch (err) {
      console.warn('[useMicVAD] Could not acquire microphone:', err);
      return false;
    }
  }, []);

  /** Release all Web Audio resources. */
  const releaseMic = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    analyserRef.current = null;
    setIsListening(false);
  }, []);

  /** The rAF monitoring loop — runs only when `active`. */
  const startLoop = useCallback(() => {
    const analyser = analyserRef.current;
    if (!analyser) return;

    const data = new Uint8Array(analyser.frequencyBinCount);

    const tick = () => {
      if (!isMountedRef.current) return;
      analyser.getByteFrequencyData(data);
      const avg = data.reduce((a, b) => a + b, 0) / data.length;

      if (avg > threshold && !cooldownRef.current) {
        cooldownRef.current = true;
        setBargedIn(true);
        if (onSpeechDetected) onSpeechDetected();
        setTimeout(() => {
          cooldownRef.current = false;
          if (isMountedRef.current) setBargedIn(false);
        }, cooldownMs);
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    setIsListening(true);
  }, [threshold, cooldownMs, onSpeechDetected]);

  /** Stop the monitoring loop without releasing the mic stream. */
  const stopLoop = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    setIsListening(false);
  }, []);

  // ── Effect: respond to `active` changes ───────────────────────────────
  useEffect(() => {
    isMountedRef.current = true;

    if (active) {
      acquireMic().then(ok => {
        if (ok && isMountedRef.current) startLoop();
      });
    } else {
      stopLoop();
    }

    return () => {
      isMountedRef.current = false;
      stopLoop();
    };
  }, [active, acquireMic, startLoop, stopLoop]);

  // ── Cleanup on unmount ────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
      releaseMic();
    };
  }, [releaseMic]);

  return { isListening, bargedIn };
}
