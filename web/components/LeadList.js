'use client';

import Link from 'next/link';
import { useMemo, useState, useTransition } from 'react';
import { markApplied } from '@/app/actions';

const TOP = 75;

const VIEWS = [
  { id: 'apply', label: 'Apply today', test: (s, r) => r.canApply },
  { id: 'top', label: 'Top picks', test: (s, r) => r.researched && r.score >= TOP && r.open !== false && ['qualified', 'to_approve', 'followup_due', 'replied'].includes(s) },
  { id: 'play', label: 'In play', test: (s) => ['offer', 'interview', 'replied', 'followup_due', 'to_approve', 'qualified', 'contacted', 'applied'].includes(s) },
  { id: 'you', label: 'Needs you', test: (s) => ['replied', 'followup_due', 'to_approve'].includes(s) },
  { id: 'qualified', label: 'Qualified, untouched', test: (s) => s === 'qualified' },
  { id: 'captured', label: 'Contacted or applied', test: (s, r) => r.captured },
  { id: 'new', label: 'Not researched yet', test: (s, r) => s === 'new' && !r.binned },
  { id: 'bin', label: 'Bin (posting closed)', test: (s, r) => r.binned },
  { id: 'off', label: 'Rejected', test: (s, r) => ['rejected', 'closed', 'skipped'].includes(s) && !r.binned },
  { id: 'all', label: 'All', test: () => true },
];

const COLD_MAIL_VIEWS = [
  { id: 'all', label: 'All', test: () => true },
  { id: 'drafts', label: 'Drafts', test: (s, r) => r.messageStatuses.includes('draft') },
  { id: 'queued', label: 'Queued', test: (s, r) => r.messageStatuses.some((status) => ['approved', 'sending'].includes(status)) },
  { id: 'sent', label: 'Sent', test: (s, r) => r.messageStatuses.some((status) => ['sent', 'replied', 'bounced'].includes(status)) },
  { id: 'followups', label: 'Follow-ups due', test: (s, r) => r.followupDue },
  { id: 'replies', label: 'Replies', test: (s, r) => s === 'replied' || r.messageStatuses.includes('replied') },
];

export default function LeadList({ rows, initialView = 'play', coldMails = false }) {
  const views = coldMails ? COLD_MAIL_VIEWS : VIEWS;
  const [view, setView] = useState(initialView);
  const [query, setQuery] = useState('');
  const [applied, setApplied] = useState(() => new Set());
  const [status, setStatus] = useState('');
  const [pending, startTransition] = useTransition();

  async function copyNote(r) {
    const text = r.coverNote || r.genericNote;
    try { await navigator.clipboard.writeText(text); setStatus(`Cover note for ${r.company} copied${r.coverNote ? '' : ' (plain version)'}.`); }
    catch { setStatus('Could not copy automatically; open the lead to copy it.'); }
  }

  function done(r) {
    startTransition(async () => {
      const result = await markApplied(r.id);
      if (result && result.ok === false) { setStatus(result.error || 'Could not save.'); return; }
      setApplied((prev) => new Set(prev).add(r.id));
      setStatus(`Marked ${r.company} as applied.`);
    });
  }
  const counts = useMemo(() => Object.fromEntries(views.map((v) => [v.id, rows.filter((r) => v.test(r.status, r)).length])), [rows, views]);
  const shown = useMemo(() => {
    const active = views.find((v) => v.id === view) || views[0];
    const needle = query.trim().toLowerCase();
    const list = rows.filter((r) => active.test(r.status, r) && (!needle || r.search.includes(needle))
      && !(active.id === 'apply' && applied.has(r.id)));
    return active.id === 'apply' ? [...list].sort((a, b) => b.score - a.score) : list;
  }, [rows, views, view, query, applied]);

  return (
    <>
      <div className="filters">
        <div className="chips" role="group" aria-label="Filter leads">
          {views.map((v) => (
            <button key={v.id} type="button" className="chip" aria-pressed={view === v.id} onClick={() => setView(v.id)}>
              {v.label}<span className="n">{counts[v.id]}</span>
            </button>
          ))}
        </div>
        <input className="search" type="search" placeholder={coldMails ? "Search company" : "Search company, role, city"} value={query}
          onChange={(event) => setQuery(event.target.value)} aria-label="Search leads" />
      </div>
      <p role="status" aria-live="polite" className="muted">{status}</p>
      {shown.length === 0 ? (
        <p className="empty">No leads in this view{query ? ' match that search' : ''}.</p>
      ) : (
        <ul className="leads">
          {shown.map((r) => coldMails ? (
            <li key={r.id} className={`lead s-${r.status}`}>
              <h3><Link href={`/lead/${r.id}`}>{r.company}</Link></h3>
              <span className={`pill tone-${r.tone}`}>{r.statusLabel}</span>
            </li>
          ) : (
            <li key={r.id} className={`lead s-${r.status}`}>
              <div>
                <h3><Link href={`/lead/${r.id}`}>{r.title} <span className="at">· {r.company}</span></Link></h3>
                {r.verdict ? <p className="verdict">{r.verdict}</p> : <p className="verdict muted">Not researched yet: rule-based score only.</p>}
                <p className="chips-line">
                  <span className={`pill tone-${r.payTone}`}>{r.pay}</span>
                  {r.experience ? <span className={`tag ${r.stretch ? 'warn-tag' : ''}`}>{r.experience}{r.stretch ? ' · stretch' : ''}</span> : null}
                  <span className="tag">{r.location || 'Location not stated'}</span>
                  <span className={`pill tone-${r.address.tone}`}>{r.address.label}</span>
                  {r.connections ? <span className="pill tone-done">{r.connections} connection{r.connections > 1 ? 's' : ''} there</span> : null}
                  {r.applied ? <span className="tag">Applied</span> : null}
                  {r.open === false ? <span className="tag warn-tag">{r.binned ? 'In the Bin' : 'Posting closed'}</span> : null}
                  {r.machine ? <span className="tag" title="Researched on GitHub by the free model">Free-model research</span> : null}
                </p>
                <p className="lead-meta">
                  {r.tier ? <span>{r.tier}</span> : null}
                  <span className="sep">{r.source}</span>
                  {r.posted ? <span className="sep">{r.posted}</span> : null}
                  {r.checked != null ? <span className="sep">Checked {r.checked === 0 ? 'today' : `${r.checked}d ago`}</span> : (r.researched ? <span className="sep">Not re-checked since the old tracker</span> : null)}
                  {r.companyNote ? <span className="sep">{r.companyNote}</span> : null}
                </p>
                {r.note ? <p className="lead-note">{r.note}</p> : null}
              </div>
              <div className="lead-side">
                <span className="score" title="Fit score out of 100">{r.score}</span>
                <span className={`pill tone-${r.tone}`}>{r.statusLabel}</span>
                {r.canApply && !applied.has(r.id) ? (
                  <>
                    <a className="button primary" href={r.applyUrl} target="_blank" rel="noreferrer">Apply</a>
                    <button type="button" className="button" onClick={() => copyNote(r)}
                      title={r.coverNote ? 'Copy the cover note written for this job' : 'Copy a plain cover note (the written one is not ready yet)'}>
                      {r.coverNote ? 'Copy note' : 'Copy plain note'}
                    </button>
                    <button type="button" className="button go" disabled={pending} onClick={() => done(r)}>Mark applied</button>
                  </>
                ) : null}
                {applied.has(r.id) ? <span className="tag">Applied</span> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
