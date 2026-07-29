import React, { useState } from 'react';
import { Mic, MicOff, Volume2, VolumeX, PhoneOff } from 'lucide-react';

function CallControls({ onEndCall }) {
  const [isMuted, setIsMuted] = useState(false);
  const [isSpeakerOn, setIsSpeakerOn] = useState(true);

  const buttonStyle = (active, danger) => ({
    width: '64px',
    height: '64px',
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    border: 'none',
    cursor: 'pointer',
    background: danger ? '#ef4444' : (active ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.05)'),
    color: 'white',
    transition: 'all 0.2s ease',
    boxShadow: danger ? '0 0 20px rgba(239, 68, 68, 0.4)' : 'none',
  });

  return (
    <div style={{ position: 'relative', display: 'flex', justifyContent: 'center', gap: '32px', padding: '32px', zIndex: 20 }}>

      <button 
        style={buttonStyle(isMuted, false)} 
        onClick={() => setIsMuted(!isMuted)}
        title={isMuted ? 'Unmute' : 'Mute'}
      >
        {isMuted ? <MicOff size={28} /> : <Mic size={28} />}
      </button>

      <button 
        style={buttonStyle(false, true)} 
        onClick={onEndCall}
        title="End Call"
      >
        <PhoneOff size={28} />
      </button>

      <button 
        style={buttonStyle(!isSpeakerOn, false)} 
        onClick={() => setIsSpeakerOn(!isSpeakerOn)}
        title={isSpeakerOn ? 'Speaker On' : 'Speaker Off'}
      >
        {isSpeakerOn ? <Volume2 size={28} /> : <VolumeX size={28} />}
      </button>
    </div>
  );
}

export default CallControls;
