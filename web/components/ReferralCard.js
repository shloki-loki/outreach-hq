'use client';

import { useState, useTransition } from 'react';
import { saveReferral } from '@/app/actions';

const STATE = { suggested: ['Not asked yet', 'new'], sent: ['Asked', 'done'], replied: ['Replied', 'reply'], skipped: ['Skipped', 'off'] };

export default function ReferralCard({ leadId, referral }) {
  const key = referral.linkedin_url || referral.name;
  const [note, setNote] = useState(referral.note || '');
  const [feedback, setFeedback] = useState(null);
  const [pending, startTransition] = useTransition();
  const [label, tone] = STATE[referral.status] || STATE.suggested;

  const save = (status, text) => startTransition(async () => {
    const result = await saveReferral(leadId, key, note, status);
    setFeedback(result.ok === false ? { bad: true, text: result.error } : { text });
  });

  // Copies the note and opens their LinkedIn page. You paste and press send yourself;
  // nothing is sent on LinkedIn by this site.
  const copyAndOpen = async () => {
    try {
      await navigator.clipboard.writeText(note);
      setFeedback({ text: 'Note copied. Paste it into the LinkedIn message box, send it, then press "Mark as asked".' });
    } catch {
      setFeedback({ bad: true, text: 'Could not copy automatically. Select the note and copy it yourself.' });
    }
    if (referral.linkedin_url) window.open(referral.linkedin_url, '_blank', 'noopener');
  };

  return (
    <article className={`card ${referral.status === 'sent' || referral.status === 'replied' ? 's-sent' : ''}`}>
      <div className="card-head">
        <div>
          <h3>{referral.name}</h3>
          <div className="sub">{referral.position || 'Role not listed'}{referral.connected_on ? ` · connected ${referral.connected_on}` : ''}</div>
        </div>
        <span className={`pill tone-${tone}`}>{label}</span>
      </div>
      <label className="field"><span>Informal note ({note.length} characters). Edit it to sound like you two actually talk.</span>
        <textarea className="short" value={note} onChange={(event) => setNote(event.target.value)} disabled={pending}
          placeholder="The referral agent has not drafted a note for this person yet. You can write one here." />
      </label>
      <div className="button-row" style={{ marginTop: 12 }}>
        <button className="button go" disabled={pending || !note.trim()} onClick={copyAndOpen}>Copy note and open LinkedIn</button>
        {referral.status === 'suggested' ? (
          <button className="button" disabled={pending} onClick={() => save('sent', 'Marked as asked.')}>Mark as asked</button>
        ) : null}
        {referral.status === 'sent' ? (
          <button className="button" disabled={pending} onClick={() => save('replied', 'Marked as replied.')}>They replied</button>
        ) : null}
        <button className="button quiet" disabled={pending} onClick={() => save(referral.status, 'Note saved.')}>Save note</button>
        {referral.status === 'suggested' ? (
          <button className="button quiet danger" disabled={pending} onClick={() => save('skipped', 'Skipped.')}>Skip</button>
        ) : null}
        {feedback ? <span className={`feedback ${feedback.bad ? 'bad' : ''}`} role="status">{feedback.text}</span> : null}
      </div>
    </article>
  );
}
