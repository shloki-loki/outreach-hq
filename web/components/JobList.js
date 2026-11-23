'use client';

// Agent Leads, simplified on Shlok's review (2026-11-23): two tabs, one Apply button, applied rows turn green.
// Clicking Apply opens the posting and marks the job applied at once; Undo is there if he did not finish.

import Link from 'next/link';
import { useMemo, useState, useTransition } from 'react';
import { markApplied, undoApplied } from '@/app/actions';

function ago(days) {
  if (days == null) return '';
  return days === 0 ? 'today' : days === 1 ? 'yesterday' : `${days} days ago`;
}

export default function JobList({ rows, initialTab = 'todo' }) {
  const [tab, setTab] = useState(initialTab);
  const [query, setQuery] = useState('');
  const [applied, setApplied] = useState(() => new Map()); // id -> true (applied here) | false (undone here)
  const [status, setStatus] = useState('');
  const [, startTransition] = useTransition();

  const isApplied = (r) => (applied.has(r.id) ? applied.get(r.id) : Boolean(r.appliedAt));

  function apply(r) {
    setApplied((prev) => new Map(prev).set(r.id, true));
    setStatus(`${r.company} marked applied. It moved to Applied; press Undo there if you did not finish.`);
    startTransition(async () => {
      const result = await markApplied(r.id);
      if (result && result.ok === false) {
        setApplied((prev) => new Map(prev).set(r.id, false));
        setStatus(result.error || 'Could not save. Try again.');
      }
    });
  }

  function undo(r) {
    setApplied((prev) => new Map(prev).set(r.id, false));
    setStatus(`${r.company} is back under To apply.`);
    startTransition(async () => {
      const result = await undoApplied(r.id);
      if (result && result.ok === false) {
        setApplied((prev) => new Map(prev).set(r.id, true));
        setStatus(result.error || 'Could not save. Try again.');
      }
    });
  }

  const todo = useMemo(() => rows.filter((r) => r.listed && !isApplied(r)), [rows, applied]); // eslint-disable-line react-hooks/exhaustive-deps
  const done = useMemo(() => rows.filter((r) => isApplied(r)), [rows, applied]); // eslint-disable-line react-hooks/exhaustive-deps
  const needle = query.trim().toLowerCase();
  const shown = (tab === 'todo' ? todo : done).filter((r) => !needle || r.search.includes(needle));

  return (
    <>
      <div className="filters">
        <div className="chips" role="group" aria-label="Choose a list">
          <button type="button" className="chip" aria-pressed={tab === 'todo'} onClick={() => setTab('todo')}>
            To apply<span className="n">{todo.length}</span>
          </button>
          <button type="button" className="chip" aria-pressed={tab === 'done'} onClick={() => setTab('done')}>
            Applied<span className="n">{done.length}</span>
          </button>
        </div>
        <input className="search" type="search" placeholder="Search company, role, city" value={query}
          onChange={(event) => setQuery(event.target.value)} aria-label="Search jobs" />
      </div>
      <p role="status" aria-live="polite" className="muted">{status}</p>
      {shown.length === 0 ? (
        <p className="empty">{tab === 'todo' ? 'Nothing left to apply to' : 'No applications yet'}{needle ? ' that matches that search' : ''}.</p>
      ) : (
        <ul className="leads">
          {shown.map((r) => {
            const on = isApplied(r);
            return (
              <li key={r.id} className={`job${on ? ' is-applied' : ''}`}>
                <div>
                  <h3><Link href={`/lead/${r.id}`}>{r.title} <span className="at">· {r.company}</span></Link></h3>
                  {r.verdict ? <p className="verdict">{r.verdict}</p> : null}
                  <p className="chips-line">
                    <span className={`tag${r.experienceKnown ? '' : ' muted-tag'}`}>{r.experience}</span>
                    {r.location ? <span className="tag">{r.location}</span> : null}
                    {r.posted ? <span className="tag">{r.posted}</span> : null}
                    {r.people ? <span className="tag">{r.people} {r.people === 1 ? 'person' : 'people'} to message</span> : null}
                  </p>
                  {on ? (
                    <p className="lead-meta">
                      <span>Applied {ago(applied.get(r.id) ? 0 : r.appliedDays)}</span>
                      {r.followUp ? <span className="sep">{r.followUp}</span> : null}
                    </p>
                  ) : null}
                </div>
                <div className="lead-side">
                  {on ? (
                    <button type="button" className="button" onClick={() => undo(r)}>Undo</button>
                  ) : r.applyUrl ? (
                    <a className="button primary" href={r.applyUrl} target="_blank" rel="noreferrer" onClick={() => apply(r)}>Apply</a>
                  ) : (
                    <span className="muted">No apply link</span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
