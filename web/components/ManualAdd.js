'use client';

// Add a job he applied to on his own (Shlok, 2026-11-24): company and a note, role and link optional.
// It is saved as applied today and shows green under Applied, with the same check-in reminder.
import { useState, useTransition } from 'react';
import { addManualJob } from '@/app/actions';

export default function ManualAdd() {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ company: '', role: '', link: '', note: '' });
  const [status, setStatus] = useState('');
  const [pending, startTransition] = useTransition();
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  function submit(event) {
    event.preventDefault();
    startTransition(async () => {
      const result = await addManualJob(form.company, form.note, form.role, form.link);
      if (result?.ok === false) { setStatus(result.error); return; }
      setStatus(`${form.company} added under Applied.`);
      setForm({ company: '', role: '', link: '', note: '' });
      setOpen(false);
    });
  }

  if (!open) {
    return (
      <div className="button-row">
        <button type="button" className="button" onClick={() => { setOpen(true); setStatus(''); }}>+ Add a job you applied to</button>
        <span role="status" aria-live="polite" className="muted">{status}</span>
      </div>
    );
  }
  return (
    <form className="card manual-add" style={{ padding: 16 }} onSubmit={submit}>
      <label>Company<input className="search" required value={form.company} onChange={set('company')} maxLength={120} /></label>
      <label>Role (optional)<input className="search" value={form.role} onChange={set('role')} maxLength={160} /></label>
      <label className="full">Link (optional)<input className="search" type="url" value={form.link} onChange={set('link')} placeholder="https://" /></label>
      <label className="full">Note<textarea className="search" required rows={3} value={form.note} onChange={set('note')} maxLength={2000}
        placeholder="Who you spoke to, how you applied, what to do next" /></label>
      <div className="button-row full">
        <button type="submit" className="button primary" disabled={pending}>{pending ? 'Saving…' : 'Save as applied'}</button>
        <button type="button" className="button quiet" onClick={() => setOpen(false)}>Cancel</button>
        <span role="status" aria-live="polite" className="muted">{status}</span>
      </div>
    </form>
  );
}
