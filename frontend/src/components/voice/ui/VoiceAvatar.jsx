import React from 'react';
import Waveform from './Waveform';

function VoiceAvatar({ isSpeaking, isListening }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', margin: '40px 0' }}>
      <div className={`avatar-ring ${isSpeaking ? 'speaking' : ''}`}>
        <span className="avatar-icon">🛡️</span>
      </div>
      
      <div style={{ marginTop: '24px', height: '40px', display: 'flex', alignItems: 'center' }}>
        <Waveform isListening={isListening} isSpeaking={isSpeaking} />
      </div>
    </div>
  );
}

export default VoiceAvatar;
