'use client';

// One InMail per job, the same text for every person listed (Shlok has LinkedIn Premium). He sends it himself.
import { useState } from 'react';

export default function InMailNote({ subject, body }) {
  const [status, setStatus] = useState('');
  async function copy(label, text) {
    try { await navigator.clipboard.writeText(text); setStatus(`${label} copied. Paste it into the InMail.`); }
    catch { setStatus('Could not copy automatically. Select the text and copy it yourself.'); }
  }
  return (
    <div className="card" style={{ padding: 20 }}>
      <p className="section-label" style={{ marginTop: 0 }}>InMail subject</p>
      <p className="prose">{subject}</p>
      <p className="section-label">InMail</p>
      <p className="prose" style={{ whiteSpace: 'pre-wrap' }}>{body}</p>
      <div className="button-row">
        <button type="button" className="button primary" onClick={() => copy('Message', body)}>Copy message</button>
        <button type="button" className="button" onClick={() => copy('Subject', subject)}>Copy subject</button>
      </div>
      <p role="status" aria-live="polite" className="muted">{status}</p>
    </div>
  );
}
