import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import VoiceSessionPanel from '../components/voice/VoiceSessionPanel';

export default function LiveCallContainer() {
  const navigate = useNavigate();
  const [summaryData, setSummaryData] = useState(null);

  const handleClassificationComplete = (intakeResponse, voiceForm) => {
    setSummaryData({
      ticketNumber: intakeResponse.ticket_number || `#${intakeResponse.intake_id}`,
      application: intakeResponse.application || null,
      status: 'Open',
      faultType: intakeResponse.fault_type_proposal,
      severity: intakeResponse.severity_proposal,
      summary: intakeResponse.ai_summary || voiceForm.raw_text
    });
  };

  const handleCancel = () => {
    navigate('/');
  };

  return (
    <VoiceSessionPanel 
      variant="live"
      onCancel={handleCancel}
      onCallEnded={() => {}}
      onClassificationComplete={handleClassificationComplete}
      summaryData={summaryData}
    />
  );
}
