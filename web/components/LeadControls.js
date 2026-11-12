'use client';

import { useState, useTransition } from 'react';
import { addNote, markApplied, setOutcome, setStage, undoApplied } from '@/app/actions';

export default function LeadControls({ lead }) {
  const [note, setNote] = useState('');
  const [feedback, setFeedback] = useState(null);
  const [pending, startTransition] = useTransition();
  const run = (work, text, after) => startTransition(async () => {
    const result = await work();
    setFeedback(result?.ok === false ? { bad: true, text: result.error } : { text });
    if (result?.ok !== false && after) after();
  });

  return (
    <div>
      <div className="button-row">
        {lead.apply_url ? <a className="button primary" href={lead.apply_url} target="_blank" rel="noreferrer">Open application</a> : null}
        {lead.applied_at ? (
          <button className="button" disabled={pending} onClick={() => run(() => undoApplied(lead.id), 'Marked as not applied.')}>Applied ✓ (undo)</button>
        ) : (
          <button className="button go" disabled={pending} onClick={() => run(() => markApplied(lead.id), 'Marked as applied.')}>I have applied</button>
        )}
        {lead.outcome !== 'interview' ? <button className="button" disabled={pending} onClick={() => run(() => setOutcome(lead.id, 'interview'), 'Marked as interview.')}>Interview</button> : null}
        {lead.outcome !== 'offer' ? <button className="button" disabled={pending} onClick={() => run(() => setOutcome(lead.id, 'offer'), 'Marked as offer.')}>Offer</button> : null}
        {lead.outcome !== 'rejected' ? <button className="button quiet danger" disabled={pending} onClick={() => run(() => setOutcome(lead.id, 'rejected'), 'Marked as rejected.')}>They said no</button> : null}
        {lead.outcome ? <button className="button quiet" disabled={pending} onClick={() => run(() => setOutcome(lead.id, 'none'), 'Outcome cleared.')}>Clear outcome</button> : null}
        {lead.stage === 'skipped' || lead.stage === 'rejected' ? (
          <button className="button quiet" disabled={pending} onClick={() => run(() => setStage(lead.id, 'qualified'), 'Back in play.')}>Put back in play</button>
        ) : (
          <button className="button quiet danger" disabled={pending} onClick={() => run(() => setStage(lead.id, 'skipped'), 'Skipped.')}>Not interested</button>
        )}
      </div>
      <label className="field"><span>Add a note</span>
        <textarea className="short" style={{ minHeight: 70 }} value={note} onChange={(event) => setNote(event.target.value)} disabled={pending}
          placeholder="Anything worth remembering: who you spoke to, what they said, next step." />
      </label>
      <div className="button-row" style={{ marginTop: 10 }}>
        <button className="button small" disabled={pending || !note.trim()} onClick={() => run(() => addNote(lead.id, note), 'Note added.', () => setNote(''))}>Save note</button>
        {feedback ? <span className={`feedback ${feedback.bad ? 'bad' : ''}`} role="status">{feedback.text}</span> : null}
      </div>
    </div>
  );
}
