'use client';

import Link from 'next/link';
import { useState, useTransition } from 'react';
import { approveMessage, retryMessage, saveMessage, skipMessage, unapproveMessage } from '@/app/actions';

const KIND = { cold: 'Cold email', followup1: 'Follow-up 1', followup2: 'Follow-up 2' };
const STATE = {
  draft: ['Needs your approval', 'approve'], approved: ['Approved, waiting to send', 'ready'],
  sending: ['Sending', 'ready'], sent: ['Sent', 'done'], replied: ['Replied', 'reply'],
  failed: ['Send failed', 'off'], bounced: ['Bounced', 'off'], skipped: ['Skipped', 'new'],
};

export default function MessageCard({ message, emailBadge, leadLabel, showLead = false, mode }) {
  const [subject, setSubject] = useState(message.subject);
  const [body, setBody] = useState(message.body.trimEnd());
  const [feedback, setFeedback] = useState(null);
  const [pending, startTransition] = useTransition();
  const words = body.trim() ? body.trim().split(/\s+/).length : 0;
  const [label, tone] = STATE[message.status] || [message.status, 'new'];
  const unverified = ['guess', 'catch-all'].includes(message.email_status);

  const run = (work) => startTransition(async () => {
    setFeedback(null);
    const result = await work();
    setFeedback(result?.ok === false ? { bad: true, text: result.error } : { text: result?.note || 'Saved.' });
  });

  return (
    <article className={`card s-${message.status}`}>
      <div className="card-head">
        <div>
          <h3>{KIND[message.kind] || message.kind} to {message.to_name || message.to}</h3>
          <div className="sub">
            {message.to}
            {showLead && leadLabel ? <> · <Link className="link" href={`/lead/${message.lead_id}`}>{leadLabel}</Link></> : null}
          </div>
        </div>
        <div className="button-row">
          {message.speculative ? <span className="tag" title="This company has no named opening. The email asks, it does not apply.">No opening: speculative note</span> : null}
          {message.play ? <span className="tag" title="Which play from the email playbook this draft uses">Play: {message.play}</span> : null}
          {message.created_by === 'writer' ? <span className="tag" title="Written on GitHub by the free model; passed every code check and a recipient read">Free-model draft</span> : null}
          {emailBadge ? <span className={`pill tone-${emailBadge.tone}`}>{emailBadge.label}</span> : null}
          <span className={`pill tone-${tone}`}>{label}</span>
        </div>
      </div>

      {message.status === 'draft' ? (
        <>
          {unverified ? <p className="warn">This address is an unverified guess, so it may bounce. At most 3 of these are sent per day.</p> : null}
          {message.promise ? <p className="hook">If they say yes, you deliver: {message.promise}</p> : null}
          {message.hook ? (
            <p className="hook">Opener is based on: {message.hook}
              {message.hook_source ? <> (<a href={message.hook_source} target="_blank" rel="noreferrer">source</a>)</> : null}
            </p>
          ) : null}
          <label className="field"><span>Subject</span>
            <input value={subject} onChange={(event) => setSubject(event.target.value)} disabled={pending} />
          </label>
          <label className="field"><span>Email ({words} words). Your signature and portfolio link are added on send.</span>
            <textarea className={message.kind === 'cold' ? '' : 'short'} value={body} onChange={(event) => setBody(event.target.value)} disabled={pending} />
          </label>
          <div className="button-row" style={{ marginTop: 12 }}>
            <button className="button go" disabled={pending} onClick={() => run(() => approveMessage(message.id, subject, body))}>
              {pending ? 'Working…' : mode === 'live' ? 'Approve and send' : 'Approve (dry run)'}
            </button>
            <button className="button" disabled={pending} onClick={() => run(() => saveMessage(message.id, subject, body))}>Save edits</button>
            <button className="button quiet danger" disabled={pending} onClick={() => run(() => skipMessage(message.id))}>Skip</button>
            {feedback ? <span className={`feedback ${feedback.bad ? 'bad' : ''}`} role="status">{feedback.text}</span> : null}
          </div>
        </>
      ) : (
        <>
          <p className="body-text"><strong>{message.subject}</strong>{'\n\n'}{message.body.trimEnd()}</p>
          {message.status === 'replied' && message.reply ? (
            <div className="reply"><strong>{message.reply.from}</strong> replied: {message.reply.snippet || '(open Gmail to read it)'}</div>
          ) : null}
          {message.error && ['failed', 'skipped', 'approved'].includes(message.status) ? <p className="warn" style={{ marginTop: 12 }}>{message.error}</p> : null}
          <div className="button-row" style={{ marginTop: 12 }}>
            {message.status === 'approved' ? (
              <button className="button small" disabled={pending} onClick={() => run(() => unapproveMessage(message.id))}>Pull back to draft</button>
            ) : null}
            {message.status === 'failed' ? (
              <>
                <button className="button small go" disabled={pending} onClick={() => run(() => retryMessage(message.id))}>Retry</button>
                <button className="button small quiet danger" disabled={pending} onClick={() => run(() => skipMessage(message.id))}>Skip</button>
              </>
            ) : null}
            {message.sent_at ? <span className="sub" style={{ fontSize: 12.5, color: 'var(--muted)' }}>Sent {new Date(message.sent_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' })}</span> : null}
            {feedback ? <span className={`feedback ${feedback.bad ? 'bad' : ''}`} role="status">{feedback.text}</span> : null}
          </div>
        </>
      )}
    </article>
  );
}
