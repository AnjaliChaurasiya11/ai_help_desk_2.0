import React, { useState, useEffect, useRef } from 'react';
import VoiceAvatar from '../components/voice/ui/VoiceAvatar';
import ConnectionStatus from '../components/voice/ui/ConnectionStatus';
import LanguageBadge from '../components/voice/ui/LanguageBadge';
import CallControls from '../components/voice/ui/CallControls';
import CallSummaryScreen from '../components/voice/ui/CallSummaryScreen';

export default function LiveCallPage({ session, audioPlaying, isProcessing, bargingIn, onCancel, summaryData, children }) {
  const [history, setHistory] = useState([]);
  const [duration, setDuration] = useState(0);
  const [languageOverride, setLanguageOverride] = useState(null);
  const [isDiagnosticsOpen, setIsDiagnosticsOpen] = useState(true);
  const scrollRef = useRef(null);

  // Timer
  useEffect(() => {
    const timer = setInterval(() => setDuration(d => d + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // Watch session for new utterances
  useEffect(() => {
    setHistory(prev => {
      const newHistory = [...prev];
      if (session.promptText && session.promptText !== 'Starting voice session...') {
        const lastAi = newHistory.filter(h => h.role === 'ai').pop();
        if (!lastAi || lastAi.text !== session.promptText) {
          newHistory.push({ id: Date.now() + 'a', role: 'ai', text: session.promptText });
        }
      }
      return newHistory;
    });
  }, [session.promptText]);

  useEffect(() => {
    setHistory(prev => {
      const newHistory = [...prev];
      if (session.transcript) {
        const lastMsg = newHistory[newHistory.length - 1];
        if (lastMsg && lastMsg.role === 'user') {
          // Update partial transcript
          lastMsg.text = session.transcript;
        } else {
          newHistory.push({ id: Date.now() + 'u', role: 'user', text: session.transcript });
        }
      }
      return newHistory;
    });
  }, [session.transcript]);

  // Scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history]);

  const isDev = import.meta.env.DEV;
  const isListening = ['CAPTURING_SERVICE_NUMBER', 'CAPTURING_COMPLAINT', 'ASK_ANOTHER_COMPLAINT'].includes(session.state) && !audioPlaying;

  if (session.state === 'INIT' && !session.id) {
    return (
      <div className="voice-call-page" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '24px' }}>
          <div className="avatar-ring speaking">
            <span className="avatar-icon">🛡️</span>
          </div>
          <h2 style={{ fontSize: '24px', fontWeight: 500 }}>Establishing Secure Voice Session...</h2>
          <div style={{ display: 'flex', gap: '8px' }}>
            <div className="status-dot blue status-pulse"></div>
            <div className="status-dot blue status-pulse" style={{ animationDelay: '0.2s' }}></div>
            <div className="status-dot blue status-pulse" style={{ animationDelay: '0.4s' }}></div>
          </div>
        </div>
        <div style={{ display: 'none' }}>{children}</div>
      </div>
    );
  }

  return (
    <div className="voice-call-page">
      <ConnectionStatus state={session.state} duration={duration} processingStage={session.processingStage} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' }}>
        
        {/* Avatar Area */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '24px 0 12px' }}>
          <VoiceAvatar isSpeaking={audioPlaying} isListening={isListening || bargingIn} />
          
          <div style={{ textAlign: 'center', marginTop: '16px' }}>
            <h2 style={{ margin: 0, fontSize: '20px', fontWeight: 600 }}>AI Help Desk Agent</h2>
            <LanguageBadge language={languageOverride || session.language} onOverride={setLanguageOverride} />
          </div>
        </div>

        {/* Chat Transcript Area */}
        <div className="chat-container" ref={scrollRef}>
          {history.map(msg => (
            <div key={msg.id} className={`chat-bubble chat-bubble-${msg.role}`}>
              {msg.text}
            </div>
          ))}
          {/* Temporary processing indicator */}
          {isProcessing && (
            <div className="chat-bubble chat-bubble-ai" style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)' }}>
               <div style={{ display: 'flex', gap: '4px' }}>
                 <div className="status-dot purple status-pulse"></div>
                 <div className="status-dot purple status-pulse" style={{ animationDelay: '0.2s' }}></div>
                 <div className="status-dot purple status-pulse" style={{ animationDelay: '0.4s' }}></div>
               </div>
            </div>
          )}
        </div>

        <CallControls onEndCall={onCancel} />

        {/* Hidden Engine Elements (VoiceRecorder, LiveKitAudioTransport) */}
        <div style={{ display: 'none' }}>
          {children}
        </div>

        {summaryData && (
          <CallSummaryScreen 
            summaryData={summaryData} 
            onRestart={() => window.location.reload()} 
          />
        )}
      </div>

      {/* 🐞 Floating Dev Diagnostics — DEV only */}
      {isDev && (
        <>
          {/* Bug FAB */}
          <button
            onClick={() => setIsDiagnosticsOpen(o => !o)}
            title="Developer Diagnostics"
            style={{
              position: 'fixed', bottom: '20px', right: '20px', zIndex: 9999,
              width: '40px', height: '40px', borderRadius: '50%',
              background: isDiagnosticsOpen ? 'rgba(0,255,0,0.15)' : 'rgba(0,0,0,0.6)',
              border: `1px solid ${isDiagnosticsOpen ? '#00ff00' : '#333'}`,
              fontSize: '20px', cursor: 'pointer', display: 'flex',
              alignItems: 'center', justifyContent: 'center',
              backdropFilter: 'blur(8px)',
              boxShadow: isDiagnosticsOpen ? '0 0 12px rgba(0,255,0,0.3)' : '0 2px 8px rgba(0,0,0,0.5)',
              transition: 'all 0.25s ease',
            }}
          >
            🐞
          </button>

          {/* Slide-up diagnostics panel */}
          <div
            style={{
              position: 'fixed', bottom: '68px', right: '16px', zIndex: 9998,
              width: '280px',
              background: '#0a0a0a',
              border: '1px solid #1a1a1a',
              borderRadius: '12px',
              fontFamily: 'monospace',
              fontSize: '12px',
              color: '#00ff00',
              boxShadow: '0 8px 32px rgba(0,0,0,0.8)',
              overflow: 'hidden',
              /* slide: max-height + opacity transition */
              maxHeight: isDiagnosticsOpen ? '400px' : '0px',
              opacity: isDiagnosticsOpen ? 1 : 0,
              padding: isDiagnosticsOpen ? '14px 16px' : '0 16px',
              transition: 'max-height 0.35s cubic-bezier(0.4,0,0.2,1), opacity 0.25s ease, padding 0.25s ease',
              pointerEvents: isDiagnosticsOpen ? 'auto' : 'none',
            }}
          >
            <div style={{ borderBottom: '1px solid #1e1e1e', paddingBottom: '6px', marginBottom: '10px',
                          display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: 700, letterSpacing: '0.05em' }}>[Dev] Diagnostics</span>
              <span style={{ fontSize: '10px', color: '#555' }}>🐞 debug</span>
            </div>
            <div className="diagnostics-row"><span className="diagnostics-label">State:</span> <span>{session.state}</span></div>
            <div className="diagnostics-row"><span className="diagnostics-label">LiveKit:</span> <span>{session.livekitEnabled ? 'Connected' : 'Disconnected'}</span></div>
            <div className="diagnostics-row"><span className="diagnostics-label">Session ID:</span> <span>{session.id ? session.id.slice(0, 8) + '...' : 'None'}</span></div>
            <div className="diagnostics-row"><span className="diagnostics-label">Language:</span> <span>{session.language || 'N/A'}</span></div>
            <div className="diagnostics-row"><span className="diagnostics-label">STT Conf:</span> <span>{session.confidence ? (session.confidence * 100).toFixed(1) + '%' : 'N/A'}</span></div>
            <div className="diagnostics-row"><span className="diagnostics-label">STT Latency:</span> <span>{session.latency ? session.latency + 'ms' : 'N/A'}</span></div>
            <div className="diagnostics-row"><span className="diagnostics-label">Verify Lat:</span> <span>{session.verifyLatency ? session.verifyLatency + 'ms' : 'N/A'}</span></div>
            <div className="diagnostics-row"><span className="diagnostics-label">Classify Lat:</span> <span>{session.classificationLatency ? session.classificationLatency + 'ms' : 'N/A'}</span></div>
            <div className="diagnostics-row"><span className="diagnostics-label">Total Pipe:</span> <span>{session.totalLatency ? session.totalLatency + 'ms' : 'N/A'}</span></div>
            <div className="diagnostics-row"><span className="diagnostics-label">Service No:</span> <span>{session.serviceNumber || 'N/A'}</span></div>
          </div>
        </>
      )}

    </div>
  );
}
