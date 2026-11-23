'use client';

// The few things Shlok does on a job (2026-11-23): apply, undo, mark an interview, or drop it.
import { useState, useTransition } from 'react';
import { markApplied, setOutcome, setStage, undoApplied } from '@/app/actions';

export default function JobActions({ lead }) {
  const [applied, setApplied] = useState(Boolean(lead.applied_at));
  const [feedback, setFeedback] = useState('');
  const [, startTransition] = useTransition();
  const run = (work, text, onFail) => startTransition(async () => {
    const result = await work();
    if (result?.ok === false) { setFeedback(result.error || 'Could not save.'); if (onFail) onFail(); }
    else setFeedback(text);
  });

  return (
    <div className={`job-actions${applied ? ' is-applied' : ''}`}>
      <div className="button-row">
        {applied ? (
          <>
            <span className="pill tone-done">Applied</span>
            <button type="button" className="button" onClick={() => { setApplied(false); run(() => undoApplied(lead.id), 'Back under To apply.', () => setApplied(true)); }}>Undo</button>
          </>
        ) : lead.apply_url ? (
          <a className="button primary" href={lead.apply_url} target="_blank" rel="noreferrer"
            onClick={() => { setApplied(true); run(() => markApplied(lead.id), 'Marked applied.', () => setApplied(false)); }}>Apply</a>
        ) : <span className="muted">No apply link</span>}
        {lead.outcome !== 'interview'
          ? <button type="button" className="button quiet" onClick={() => run(() => setOutcome(lead.id, 'interview'), 'Marked as an interview.')}>Got an interview</button>
          : <span className="pill tone-win">Interview</span>}
        {!applied && lead.stage === 'qualified'
          ? <button type="button" className="button quiet" onClick={() => run(() => setStage(lead.id, 'skipped'), 'Removed from your list.')}>Not for me</button>
          : null}
      </div>
      <p role="status" aria-live="polite" className="muted">{feedback}</p>
    </div>
  );
}
