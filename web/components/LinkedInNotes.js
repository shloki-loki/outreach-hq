'use client';
import { useState } from 'react';

// LinkedIn notes are drafted for Shlok to copy and send himself. Nothing is sent from this site.
export default function LinkedInNotes({ drafts }) {
  const [status, setStatus] = useState('');

  async function copy(label, value) {
    try { await navigator.clipboard.writeText(value); setStatus(`${label} copied. Paste it on LinkedIn.`); }
    catch { setStatus('Could not copy automatically. Select the text and copy it yourself.'); }
  }

  return (
    <>
      {drafts.map((draft) => (
        <div key={draft.contact_id} className="card" style={{ padding: 20, marginBottom: 14 }}>
          <h3 style={{ marginBottom: 4 }}>{draft.name}{draft.title ? <span style={{ fontWeight: 400, color: 'var(--muted)' }}> · {draft.title}</span> : null}</h3>
          <p className="section-label" style={{ marginTop: 12 }}>Connection note · {draft.connect.length} of 200 characters</p>
          <p className="prose" style={{ whiteSpace: 'pre-wrap' }}>{draft.connect}</p>
          <div className="button-row">
            <button className="button" type="button" onClick={() => copy('Connection note', draft.connect)}>Copy note</button>
          </div>
          <p className="section-label" style={{ marginTop: 16 }}>Message after they accept, or InMail · subject: {draft.inmail_subject}</p>
          <p className="prose" style={{ whiteSpace: 'pre-wrap' }}>{draft.inmail}</p>
          <div className="button-row">
            <button className="button" type="button" onClick={() => copy('Message', draft.inmail)}>Copy message</button>
            {/^https?:\/\//.test(draft.linkedin_url || '') ? (
              <a className="button primary" href={draft.linkedin_url} target="_blank" rel="noreferrer">Open their LinkedIn</a>
            ) : null}
          </div>
        </div>
      ))}
      <p role="status" aria-live="polite">{status}</p>
    </>
  );
}
