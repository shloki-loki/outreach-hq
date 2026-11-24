'use client';

// The people to InMail for one job and the one note that goes to all of them (Shlok has LinkedIn Premium).
// The note is checked by the pipeline (messages.check_linkedin); each copy fills in that person's first name.
// Shlok opens the profile and sends it himself. Nothing is sent from here.
import { useState } from 'react';

const ROLE = { hiring_manager: 'Hiring manager', team_lead: 'Team lead', recruiter: 'Recruiter', founder: 'Founder',
  employee: 'Works there' };

const firstName = (name) => (name || '').trim().split(/\s+/)[0] || '';

export default function InMailNote({ people, note }) {
  const [status, setStatus] = useState('');
  async function copy(label, text) {
    try { await navigator.clipboard.writeText(text); setStatus(`${label} copied. Paste it into the InMail.`); }
    catch { setStatus('Could not copy automatically. Select the text and copy it yourself.'); }
  }
  const preview = note?.body ? note.body.replace('{first_name}', '<first name>') : '';
  return (
    <>
      {people.length === 0 ? (
        <p className="empty">Not looked up yet. The hiring manager, the team lead and the recruiter are found on LinkedIn for each job.</p>
      ) : (
        <div className="card">
          {people.map((person) => (
            <div key={person.id} className="person">
              <div>
                <h4>{person.name} <span style={{ fontWeight: 400, color: 'var(--muted)' }}>· {ROLE[person.role_type] || 'Works there'}</span></h4>
                {person.title ? <p>{person.title}</p> : null}
              </div>
              <div className="right button-row">
                <a className="button small primary" href={person.linkedin_url} target="_blank" rel="noreferrer">Open LinkedIn</a>
                {note?.body ? (
                  <button type="button" className="button small"
                    onClick={() => copy(`Note for ${firstName(person.name)}`, note.body.replace('{first_name}', firstName(person.name)))}>
                    Copy note
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
      {note?.body ? (
        <div className="card" style={{ padding: 20, marginTop: 14 }}>
          <p className="section-label" style={{ marginTop: 0 }}>InMail subject</p>
          <p className="prose">{note.subject}</p>
          <p className="section-label">InMail (the same for everyone above; Copy note fills in the name)</p>
          <p className="prose" style={{ whiteSpace: 'pre-wrap' }}>{preview}</p>
          <div className="button-row">
            <button type="button" className="button" onClick={() => copy('Subject', note.subject)}>Copy subject</button>
          </div>
        </div>
      ) : null}
      <p role="status" aria-live="polite" className="muted">{status}</p>
    </>
  );
}
