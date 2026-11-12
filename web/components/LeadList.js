'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';

const VIEWS = [
  { id: 'play', label: 'In play', test: (s) => ['offer', 'interview', 'replied', 'followup_due', 'to_approve', 'qualified', 'contacted', 'applied'].includes(s) },
  { id: 'you', label: 'Needs you', test: (s) => ['replied', 'followup_due', 'to_approve'].includes(s) },
  { id: 'qualified', label: 'Qualified, untouched', test: (s) => s === 'qualified' },
  { id: 'captured', label: 'Contacted or applied', test: (s, r) => r.captured },
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
                <p className="lead-meta">
                  <span>{r.location || 'Location not stated'}</span>
                  <span className="sep">Pay: {r.pay}</span>
                  <span className="sep">{r.source}</span>
                  {r.posted ? <span className="sep">{r.posted}</span> : null}
                  {r.open === false ? <span className="sep">Posting closed</span> : null}
                </p>
                {r.note ? <p className="lead-note">{r.note}</p> : null}
              </div>
              <div className="lead-side">
                {r.emails ? <span className="tag">{r.emails} email{r.emails > 1 ? 's' : ''} found</span> : null}
                {r.connections ? <span className="tag">{r.connections} connection{r.connections > 1 ? 's' : ''}</span> : null}
                {r.applied ? <span className="tag">Applied</span> : null}
                {r.stretch ? <span className="tag">Stretch</span> : null}
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
