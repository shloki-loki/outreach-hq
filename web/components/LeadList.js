'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';

const TOP = 75;

const VIEWS = [
  { id: 'top', label: 'Top picks', test: (s, r) => r.researched && r.score >= TOP && r.open !== false && ['qualified', 'to_approve', 'followup_due', 'replied'].includes(s) },
  { id: 'play', label: 'In play', test: (s) => ['offer', 'interview', 'replied', 'followup_due', 'to_approve', 'qualified', 'contacted', 'applied'].includes(s) },
  { id: 'you', label: 'Needs you', test: (s) => ['replied', 'followup_due', 'to_approve'].includes(s) },
  { id: 'qualified', label: 'Qualified, untouched', test: (s) => s === 'qualified' },
  { id: 'captured', label: 'Contacted or applied', test: (s, r) => r.captured },
  { id: 'spec', label: 'No opening (speculative)', test: (s, r) => r.speculative && !['rejected', 'closed', 'skipped'].includes(s) },
  { id: 'new', label: 'Not researched yet', test: (s) => s === 'new' },
  { id: 'off', label: 'Rejected or closed', test: (s) => ['rejected', 'closed', 'skipped'].includes(s) },
  { id: 'all', label: 'All', test: () => true },
];

export default function LeadList({ rows, initialView = 'play' }) {
  const [view, setView] = useState(initialView);
  const [query, setQuery] = useState('');
  const counts = useMemo(() => Object.fromEntries(VIEWS.map((v) => [v.id, rows.filter((r) => v.test(r.status, r)).length])), [rows]);
  const shown = useMemo(() => {
    const active = VIEWS.find((v) => v.id === view) || VIEWS[0];
    const needle = query.trim().toLowerCase();
    return rows.filter((r) => active.test(r.status, r) && (!needle || r.search.includes(needle)));
  }, [rows, view, query]);

  return (
    <>
      <div className="filters">
        <div className="chips" role="group" aria-label="Filter leads">
          {VIEWS.map((v) => (
            <button key={v.id} type="button" className="chip" aria-pressed={view === v.id} onClick={() => setView(v.id)}>
              {v.label}<span className="n">{counts[v.id]}</span>
            </button>
          ))}
        </div>
        <input className="search" type="search" placeholder="Search company, role, city" value={query}
          onChange={(event) => setQuery(event.target.value)} aria-label="Search leads" />
      </div>
      {shown.length === 0 ? (
        <p className="empty">No leads in this view{query ? ' match that search' : ''}.</p>
      ) : (
        <ul className="leads">
          {shown.map((r) => (
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
                  {r.speculative ? <span className="tag">No opening</span> : null}
                  {r.applied ? <span className="tag">Applied</span> : null}
                  {r.open === false ? <span className="tag warn-tag">Posting closed</span> : null}
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
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
