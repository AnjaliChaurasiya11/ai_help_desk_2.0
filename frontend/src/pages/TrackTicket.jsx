import { useState } from 'react';
import { Link } from 'react-router-dom';

export default function TrackTicket() {
  const [ticketId, setTicketId] = useState('');
  const [ticket, setTicket] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleTrack = async (e) => {
    e.preventDefault();
    if (!ticketId.trim()) return;

    setLoading(true);
    setError(null);
    setTicket(null);

    try {
      const response = await fetch(`http://localhost:8001/api/tickets/track/${ticketId.trim()}`);
      if (!response.ok) {
        if (response.status === 404) {
          throw new Error('Ticket not found. Please check the Ticket ID.');
        }
        throw new Error('Failed to fetch ticket. Please try again later.');
      }
      
      const data = await response.json();
      setTicket(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'open': return 'var(--accent)';
      case 'assigned': return '#8b5cf6';
      case 'in_progress': return '#f59e0b';
      case 'resolved': return '#10b981';
      case 'closed': return '#6b7280';
      default: return 'var(--text-muted)';
    }
  };

  const getSeverityColor = (severity) => {
    switch (severity) {
      case 'critical': return 'var(--critical)';
      case 'high': return '#f97316';
      case 'medium': return '#eab308';
      case 'low': return '#3b82f6';
      case 'normal': return '#3b82f6';
      default: return 'var(--text-muted)';
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    return new Date(dateStr).toLocaleString();
  };

  const STAGES = ['open', 'assigned', 'in_progress', 'resolved', 'closed'];
  
  const getStageIndex = (status) => {
    return STAGES.indexOf(status);
  };

  return (
    <div className="login-page">
      <div className="login-card" style={{ maxWidth: 500, width: '100%' }}>
        <div className="login-emblem" style={{ background: 'var(--surface-3)' }}>
          🔍
        </div>

        <div className="text-center mb-4">
          <h2 style={{ marginBottom: 6 }}>Track Complaint</h2>
          <p style={{
            fontSize: '0.72rem', color: 'var(--text-muted)',
            textTransform: 'uppercase', letterSpacing: '0.1em',
          }}>
            Check the real-time status of your ticket
          </p>
        </div>

        <div className="divider" />

        <form onSubmit={handleTrack} style={{ marginBottom: 24 }}>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: 6 }}>
              Ticket ID
            </label>
            <input
              type="text"
              placeholder="e.g. TIC-202607-0001"
              value={ticketId}
              onChange={(e) => setTicketId(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 14px',
                background: 'var(--navy-950)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                fontSize: '0.9rem',
                outline: 'none',
              }}
            />
          </div>
          <button
            type="submit"
            className="btn btn-primary w-full"
            disabled={loading || !ticketId.trim()}
            style={{ justifyContent: 'center', width: '100%' }}
          >
            {loading ? 'Searching...' : 'Track Ticket'}
          </button>
        </form>

        {error && (
          <div className="alert alert-error mb-4">
            ⚠️ {error}
          </div>
        )}

        {ticket && (
          <div style={{
            background: 'var(--navy-900)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-lg)',
            padding: '20px',
            animation: 'fadeIn 0.3s ease-out'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {ticket.ticket_number}
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 4 }}>
                  Submitted on {formatDate(ticket.created_at)}
                </div>
              </div>
              <div style={{
                background: 'var(--navy-800)',
                border: `1px solid ${getStatusColor(ticket.status)}40`,
                color: getStatusColor(ticket.status),
                padding: '4px 10px',
                borderRadius: '12px',
                fontSize: '0.75rem',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.05em'
              }}>
                {ticket.status.replace('_', ' ')}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
              <div>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 4 }}>Application</div>
                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>{ticket.primary_application_name || 'Unclassified'}</div>
              </div>
              <div>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 4 }}>Fault Type</div>
                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>{ticket.fault_type || 'Unknown'}</div>
              </div>
              <div>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 4 }}>Severity</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: getSeverityColor(ticket.severity) }} />
                  <span style={{ textTransform: 'capitalize' }}>{ticket.severity || 'Normal'}</span>
                </div>
              </div>
            </div>

            <div style={{ marginBottom: 8, fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-primary)' }}>Progress Timeline</div>
            <div style={{ position: 'relative', paddingTop: 12, paddingBottom: 12 }}>
              {/* Timeline Track */}
              <div style={{
                position: 'absolute',
                top: 20, left: 16, right: 16,
                height: 2, background: 'var(--border)',
                zIndex: 0
              }} />
              
              {/* Fill track line up to current status */}
              <div style={{
                position: 'absolute',
                top: 20, left: 16, 
                width: `calc(${(getStageIndex(ticket.status) / (STAGES.length - 1)) * 100}% - 32px)`,
                height: 2, background: 'var(--accent)',
                zIndex: 0, transition: 'width 0.5s ease'
              }} />

              <div style={{
                display: 'flex', justifyContent: 'space-between', position: 'relative', zIndex: 1
              }}>
                {STAGES.map((stage, idx) => {
                  const currentIdx = getStageIndex(ticket.status);
                  const isCompleted = idx <= currentIdx;
                  const isActive = idx === currentIdx;
                  
                  return (
                    <div key={stage} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                      <div style={{
                        width: 16, height: 16, borderRadius: '50%',
                        background: isActive ? 'var(--navy-900)' : (isCompleted ? 'var(--accent)' : 'var(--navy-800)'),
                        border: `2px solid ${isCompleted ? 'var(--accent)' : 'var(--border)'}`,
                        boxShadow: isActive ? '0 0 0 4px var(--accent-alpha)' : 'none',
                        transition: 'all 0.3s ease'
                      }} />
                      <span style={{ 
                        fontSize: '0.65rem', 
                        textTransform: 'uppercase',
                        color: isCompleted ? 'var(--text-primary)' : 'var(--text-muted)',
                        fontWeight: isActive ? 600 : 400
                      }}>
                        {stage.replace('_', ' ')}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        <div style={{
          textAlign: 'center', marginTop: 24, paddingTop: 16,
          borderTop: '1px solid var(--border)'
        }}>
          <Link to="/" className="btn btn-outline btn-sm" style={{ width: '100%', justifyContent: 'center' }}>
            🔙 Back to Login
          </Link>
        </div>
      </div>
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
