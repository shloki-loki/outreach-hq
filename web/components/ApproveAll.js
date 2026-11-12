'use client';

import { useState, useTransition } from 'react';
import { approveMany } from '@/app/actions';

export default function ApproveAll({ ids, mode }) {
  const [feedback, setFeedback] = useState(null);
  const [armed, setArmed] = useState(false);
  const [pending, startTransition] = useTransition();
  if (ids.length < 2) return null;
  return (
    <div className="button-row">
      {armed ? (
        <>
          <button className="button go small" disabled={pending} onClick={() => startTransition(async () => {
            const result = await approveMany(ids);
            setArmed(false);
            setFeedback(result.ok === false ? { bad: true, text: result.error } : { text: result.note });
          })}>{pending ? 'Working…' : `Yes, approve all ${ids.length} as written`}</button>
          <button className="button small quiet" disabled={pending} onClick={() => setArmed(false)}>Cancel</button>
        </>
      ) : (
        <button className="button small" onClick={() => setArmed(true)}>Approve all {ids.length}{mode === 'live' ? ' and send' : ' (dry run)'}</button>
      )}
      {feedback ? <span className={`feedback ${feedback.bad ? 'bad' : ''}`} role="status">{feedback.text}</span> : null}
    </div>
  );
}
