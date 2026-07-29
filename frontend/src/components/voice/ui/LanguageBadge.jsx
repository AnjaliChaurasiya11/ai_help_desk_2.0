import React, { useState } from 'react';
import { Globe } from 'lucide-react';

function LanguageBadge({ language, onOverride }) {
  const [isOpen, setIsOpen] = useState(false);
  
  if (!language) return null;

  const languages = ['english', 'hindi', 'gujarati'];

  return (
    <div style={{ position: 'relative', marginTop: '8px' }}>
      <button 
        onClick={() => setIsOpen(!isOpen)}
        style={{
          background: 'rgba(255, 255, 255, 0.1)',
          border: '1px solid rgba(255, 255, 255, 0.2)',
          borderRadius: '20px',
          padding: '4px 12px',
          color: 'white',
          fontSize: '12px',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          cursor: 'pointer',
          transition: 'all 0.2s ease'
        }}
      >
        <Globe size={14} />
        {language.charAt(0).toUpperCase() + language.slice(1)}
      </button>

      {isOpen && (
        <div style={{
          position: 'absolute',
          top: '100%',
          left: '50%',
          transform: 'translateX(-50%)',
          marginTop: '8px',
          background: 'var(--surface-1)',
          border: '1px solid var(--border)',
          borderRadius: '8px',
          padding: '4px',
          zIndex: 50,
          boxShadow: 'var(--shadow-card)',
          width: '120px'
        }}>
          {languages.map(lang => (
            <button
              key={lang}
              onClick={() => {
                if (onOverride) onOverride(lang);
                setIsOpen(false);
              }}
              style={{
                width: '100%',
                padding: '6px 12px',
                textAlign: 'left',
                background: 'transparent',
                border: 'none',
                color: 'var(--text-primary)',
                fontSize: '13px',
                cursor: 'pointer',
                borderRadius: '4px',
              }}
              onMouseEnter={(e) => e.target.style.background = 'var(--surface-2)'}
              onMouseLeave={(e) => e.target.style.background = 'transparent'}
            >
              {lang.charAt(0).toUpperCase() + lang.slice(1)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default LanguageBadge;
