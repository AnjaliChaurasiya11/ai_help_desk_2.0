import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

const AUTO_CLOSE_SECONDS = 12;

function CallSummaryScreen({ summaryData, onRestart }) {
  const [countdown, setCountdown] = useState(AUTO_CLOSE_SECONDS);

  useEffect(() => {
    if (!summaryData) return;
    const interval = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          clearInterval(interval);
          // navigate to home after countdown
          window.location.href = '/';
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [summaryData]);

  if (!summaryData) return null;

  const severityColor = {
    critical: '#ef4444',
    high: '#f97316',
    medium: '#eab308',
    normal: '#22c55e',
    low: '#94a3b8',
  }[summaryData.severity?.toLowerCase()] || '#94a3b8';

  return (
    <div style={{
      position: 'absolute', inset: 0, zIndex: 100,
      background: 'rgba(15, 23, 42, 0.96)',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      padding: '24px', backdropFilter: 'blur(12px)'
    }}>
      <div style={{
        background: 'var(--surface-1)', border: '1px solid var(--border)',
        borderRadius: '24px', padding: '40px', width: '100%', maxWidth: '520px',
        boxShadow: 'var(--shadow-card)', textAlign: 'center', animation: 'fadeInUp 0.5s ease forwards'
      }}>
        {/* Success icon */}
        <div style={{
          width: '72px', height: '72px', background: 'rgba(34, 197, 94, 0.1)',
          border: '2px solid rgba(34, 197, 94, 0.4)',
          borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '36px', margin: '0 auto 20px'
        }}>
          ✓
        </div>

        <h2 style={{ fontSize: '22px', fontWeight: 600, marginBottom: '6px' }}>Ticket Created Successfully</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '14px', marginBottom: '28px' }}>
          Your issue has been logged. Our team will get back to you.
        </p>

        {/* Ticket details grid */}
        <div style={{ background: 'var(--surface-2)', borderRadius: '14px', padding: '20px', textAlign: 'left', marginBottom: '24px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>

            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>Ticket Number</div>
              <div style={{ fontSize: '15px', fontWeight: 700, color: 'var(--accent)', fontFamily: 'monospace' }}>
                {summaryData.ticketNumber || 'N/A'}
              </div>
            </div>

            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>Status</div>
              <div style={{ fontSize: '14px', fontWeight: 600, color: '#22c55e' }}>{summaryData.status || 'Open'}</div>
            </div>

            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>Fault Type</div>
              <div style={{ fontSize: '14px', textTransform: 'capitalize' }}>{summaryData.faultType || 'Other'}</div>
            </div>

            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>Severity</div>
              <div style={{ fontSize: '14px', fontWeight: 600, color: severityColor, textTransform: 'capitalize' }}>
                {summaryData.severity || 'Normal'}
              </div>
            </div>
          </div>

          {summaryData.application && (
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>Application</div>
              <div style={{ fontSize: '14px', fontWeight: 500 }}>{summaryData.application}</div>
            </div>
          )}

          {summaryData.summary && (
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>Complaint Summary</div>
              <div style={{ fontSize: '13px', fontStyle: 'italic', lineHeight: '1.6', color: 'var(--text-secondary)' }}>
                "{summaryData.summary}"
              </div>
            </div>
          )}
        </div>

        {/* Auto-close countdown */}
        <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '20px' }}>
          Returning to home in <strong style={{ color: 'var(--accent)' }}>{countdown}s</strong>
        </p>

        {/* Actions */}
        <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
          <button
            onClick={onRestart}
            style={{
              padding: '10px 20px', background: 'var(--surface-3)', border: '1px solid var(--border)',
              color: 'var(--text-primary)', borderRadius: '8px', cursor: 'pointer', fontWeight: 500, fontSize: '14px'
            }}
          >
            Report Another
          </button>

          <Link to="/" style={{
            padding: '10px 20px', background: 'var(--accent)', border: 'none',
            color: 'white', borderRadius: '8px', cursor: 'pointer', fontWeight: 500,
            textDecoration: 'none', display: 'inline-flex', alignItems: 'center', fontSize: '14px'
          }}>
            Go Home
          </Link>
        </div>
      </div>
    </div>
  );
}

export default CallSummaryScreen;
