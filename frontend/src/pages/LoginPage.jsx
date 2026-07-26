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

        <div style={{
          textAlign: 'center', marginTop: 24, paddingTop: 16,
          borderTop: '1px solid var(--border)'
        }}>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: 8 }}>
            Looking for an existing ticket?
          </p>
          <Link to="/track" className="btn btn-outline btn-sm" style={{ width: '100%', justifyContent: 'center' }}>
            🔍 Track a Complaint
          </Link>
        </div>
      </div>
    </div>
  );
}