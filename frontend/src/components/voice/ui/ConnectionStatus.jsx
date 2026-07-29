import React, { useState, useEffect } from 'react';
import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

function ConnectionStatus({ state, duration, processingStage }) {
  const [fakedStage, setFakedStage] = useState(null);

  useEffect(() => {
    if (processingStage === 'classification') {
      const timer = setTimeout(() => {
        setFakedStage('Creating your ticket');
      }, 2500); // Transition after 2.5s
      return () => clearTimeout(timer);
    } else {
      setFakedStage(null);
    }
  }, [processingStage]);

  const formatTime = (seconds) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = (seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  const getStatusInfo = () => {
    if (processingStage === 'stt') return { text: 'Understanding your issue...', dot: 'purple' };
    if (processingStage === 'classification') return { text: fakedStage || 'Checking for similar incidents...', dot: 'purple' };

    switch(state) {
      case 'INIT':
      case 'GREETING': return { text: 'Establishing Secure Voice Session...', dot: 'orange' };
      case 'CAPTURING_SERVICE_NUMBER': 
      case 'CAPTURING_COMPLAINT':
      case 'ASK_ANOTHER_COMPLAINT': return { text: 'Listening', dot: 'green' };
      case 'CONFIRMING_SERVICE_NUMBER':
      case 'CLARIFICATION': return { text: 'Speaking', dot: 'blue' };
      case 'CLASSIFICATION': return { text: 'Checking for similar incidents...', dot: 'purple' };
      case 'OPERATOR_REVIEW': return { text: 'Ticket Created ✓', dot: 'green' };
      case 'COMPLETED': return { text: 'Call Ended', dot: 'red' };
      case 'ERROR': return { text: 'Disconnected', dot: 'red' };
      default: return { text: 'Connected', dot: 'green' };
    }
  };

  const { text, dot } = getStatusInfo();
  
  // Use status-pulse for active processing/listening states
  const showPulse = ['green', 'orange', 'purple'].includes(dot);

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '16px 24px',
      background: 'rgba(0, 0, 0, 0.2)',
      borderBottom: '1px solid rgba(255, 255, 255, 0.1)',
      zIndex: 20
    }}>
      <Link to="/" style={{ color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '8px', textDecoration: 'none' }}>
        <ArrowLeft size={20} />
        <span style={{ fontSize: '14px', fontWeight: 500 }}>Back</span>
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '14px', fontWeight: 600, color: 'rgba(255,255,255,0.9)' }}>
          🛡 Secure Voice Session
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(255,255,255,0.05)', padding: '6px 12px', borderRadius: '16px' }}>
          <div className={`status-dot ${dot} ${showPulse ? 'status-pulse' : ''}`}></div>
          <span style={{ fontSize: '12px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {text}
          </span>
        </div>
        
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 500, color: '#94a3b8' }}>
          {formatTime(duration)}
        </div>
      </div>
    </div>
  );
}

export default ConnectionStatus;
