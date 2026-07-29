import { useAuth } from 'react-oidc-context';
import { Link } from 'react-router-dom';

export default function LoginPage() {
  const auth = useAuth();

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-emblem">🛡️</div>

        <div className="text-center mb-4">
          <h2 style={{ marginBottom: 6 }}>AI Help Desk</h2>
          <p style={{
            fontSize: '0.72rem', color: 'var(--text-muted)',
            textTransform: 'uppercase', letterSpacing: '0.1em',
          }}>
            IT Support Portal — Authorised Access Only
          </p>
        </div>

        <div className="divider" />

        <div style={{
          background: 'var(--navy-800)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-md)',
          padding: '11px 14px',
          marginBottom: 20,
          fontSize: '0.8rem',
          color: 'var(--text-secondary)',
          display: 'flex', gap: 9, alignItems: 'flex-start',
        }}>
          <span style={{ fontSize: 15, flexShrink: 0 }}>🔐</span>
          <span>Authenticate with your Service Number to access the help desk system.</span>
        </div>

        <button
          onClick={() => auth.signinRedirect()}
          className="btn btn-primary btn-lg w-full"
          style={{ justifyContent: 'center', width: '100%' }}
        >
          🔑 Login with Service Number
        </button>

        <p style={{
          textAlign: 'center', fontSize: '0.68rem',
          color: 'var(--text-muted)', marginTop: 18,
        }}>
          Authorised personnel only. All access is logged and monitored.
        </p>

        {auth.error && (
          <div className="alert alert-error mt-3">
            ⚠️ {auth.error.message}
          </div>
        )}

      </div>

      {/* Side Track Tab (Red Arrow) */}
      <Link
        to="/track"
        style={{
          position: 'fixed',
          left: 0,
          top: '120px',
          backgroundColor: 'var(--danger)',
          padding: '10px 24px 10px 16px',
          clipPath: 'polygon(0% 0%, 85% 0%, 100% 50%, 85% 100%, 0% 100%)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-start',
          textDecoration: 'none',
          zIndex: 1000,
          transition: 'transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), background-color 0.2s',
          filter: 'drop-shadow(2px 4px 6px rgba(0,0,0,0.4))',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.transform = 'translateX(6px)';
          e.currentTarget.style.backgroundColor = '#dc2626';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = 'translateX(0)';
          e.currentTarget.style.backgroundColor = 'var(--danger)';
        }}
      >
        <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'rgba(255,255,255,0.85)' }}>
          Existing ticket?
        </div>
        <div style={{ fontSize: '0.9rem', fontWeight: '700', color: '#ffffff', marginTop: '1px', display: 'flex', alignItems: 'center', gap: '4px' }}>
          Track Complaint
        </div>
      </Link>

      {/* Live AI Support Tab (Blue Arrow) */}
      <Link
        to="/live-support"
        className="live-ai-entry-card"
        style={{
          position: 'fixed',
          left: 0,
          top: '200px',
          backgroundColor: 'var(--accent)',
          padding: '10px 24px 10px 16px',
          clipPath: 'polygon(0% 0%, 85% 0%, 100% 50%, 85% 100%, 0% 100%)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-start',
          textDecoration: 'none',
          zIndex: 1000,
          transition: 'transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), background-color 0.2s',
          filter: 'drop-shadow(2px 4px 6px rgba(0,0,0,0.4))',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.transform = 'translateX(6px)';
          e.currentTarget.style.backgroundColor = 'var(--accent-dim)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = 'translateX(0)';
          e.currentTarget.style.backgroundColor = 'var(--accent)';
        }}
      >
        <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'rgba(255,255,255,0.85)' }}>
          📞 Live AI Support
        </div>
        <div style={{ fontSize: '0.9rem', fontWeight: '700', color: '#ffffff', marginTop: '1px', display: 'flex', alignItems: 'center', gap: '4px' }}>
          Talk to AI Help Desk
        </div>
      </Link>
    </div>
  );
}