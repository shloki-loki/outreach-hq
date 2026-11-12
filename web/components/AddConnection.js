'use client';

import { useState, useTransition } from 'react';
import { addReferral } from '@/app/actions';

// For someone the live LinkedIn search turned up who is not in the last export.
export default function AddConnection({ leadId }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [position, setPosition] = useState('');
  const [url, setUrl] = useState('');
  const [feedback, setFeedback] = useState(null);
  const [pending, startTransition] = useTransition();

  if (!open) {
    return <div className="button-row" style={{ marginTop: 12 }}><button className="button small" onClick={() => setOpen(true)}>Add a connection I found</button>
      {feedback ? <span className="feedback" role="status">{feedback.text}</span> : null}</div>;
  }
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <label className="field" style={{ marginTop: 0 }}><span>Name</span><input value={name} onChange={(e) => setName(e.target.value)} disabled={pending} /></label>
      <label className="field"><span>Their role there</span><input value={position} onChange={(e) => setPosition(e.target.value)} disabled={pending} /></label>
      <label className="field"><span>LinkedIn profile link</span><input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.linkedin.com/in/..." disabled={pending} /></label>
      <div className="button-row" style={{ marginTop: 12 }}>
        <button className="button go" disabled={pending || !name.trim()} onClick={() => startTransition(async () => {
          const result = await addReferral(leadId, name, position, url);
          if (result.ok === false) { setFeedback({ bad: true, text: result.error }); return; }
          setName(''); setPosition(''); setUrl(''); setOpen(false);
          setFeedback({ text: 'Added. A note for them is drafted on the next send-track run, or write one now.' });
        })}>{pending ? 'Saving…' : 'Add'}</button>
        <button className="button quiet" disabled={pending} onClick={() => setOpen(false)}>Cancel</button>
        {feedback?.bad ? <span className="feedback bad" role="alert">{feedback.text}</span> : null}
      </div>
    </div>
  );
}
