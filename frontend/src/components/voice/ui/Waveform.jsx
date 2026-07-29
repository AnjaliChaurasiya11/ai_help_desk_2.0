import React from 'react';

function Waveform({ isListening, isSpeaking }) {
  if (!isListening && !isSpeaking) {
    return <div style={{ height: '32px', width: '120px' }}></div>; // placeholder
  }

  const bars = Array.from({ length: 8 });
  const typeClass = isListening ? 'user' : 'ai';

  return (
    <div style={{ display: 'flex', gap: '4px', alignItems: 'center', height: '32px' }}>
      {bars.map((_, i) => (
        <div 
          key={i} 
          className={`wave-bar ${typeClass}`} 
          style={{ animationDelay: `${i * 0.1}s` }}
        ></div>
      ))}
    </div>
  );
}

export default Waveform;
