'use client';

// Agent Leads (Shlok's reviews of 2026-11-23 and 2026-11-24): three tabs.
//   To apply: listed jobs not applied to by any route. Apply opens the posting and marks it applied (Undo is there).
//   Applied: green rows with Interview / Rejected / No response. A job with nothing new for 4 days is pinned on top
//            under "Check in" until he presses "I followed up" or records an outcome.
//   Closed: rejected or no response.

import Link from 'next/link';
import { useMemo, useState, useTransition } from 'react';
import { checkIn, markApplied, setOutcome, undoApplied } from '@/app/actions';

function ago(days) {
  if (days == null) return '';
  return days === 0 ? 'today' : days === 1 ? 'yesterday' : `${days} days ago`;
}

const OUTCOME_LABEL = { interview: 'Interview', offer: 'Offer', rejected: 'Rejected', closed: 'No response' };

export default function JobList({ rows, initialTab = 'todo' }) {
  const [tab, setTab] = useState(initialTab);
  const [query, setQuery] = useState('');
  const [local, setLocal] = useState(() => new Map()); // id -> { applied?, outcome?, checkedIn? } set on this page
  const [status, setStatus] = useState('');
  const [, startTransition] = useTransition();

  const view = (r) => {
    const here = local.get(r.id) || {};
    const applied = 'applied' in here ? here.applied : Boolean(r.appliedAt);
    const outcome = 'outcome' in here ? here.outcome : r.outcome;
    const closed = ['rejected', 'closed'].includes(outcome);
    const checkIn = applied && !closed && !['interview', 'offer'].includes(outcome) && !here.checkedIn
      && (here.applied ? false : r.checkIn);
    return { applied, outcome, closed, checkIn, fresh: Boolean(here.applied) };
  };

  function save(r, patch, work, text) {
    const before = local.get(r.id) || {};
    setLocal((prev) => new Map(prev).set(r.id, { ...before, ...patch }));
    setStatus(text);
    startTransition(async () => {
      const result = await work();
      if (result && result.ok === false) {
        setLocal((prev) => new Map(prev).set(r.id, before));
        setStatus(result.error || 'Could not save. Try again.');
      }
    });
  }

  const apply = (r) => save(r, { applied: true }, () => markApplied(r.id),
    `${r.company} marked applied. It is under Applied; press Undo there if you did not finish.`);
  const undo = (r) => save(r, { applied: false }, () => undoApplied(r.id), `${r.company} is back under To apply.`);
  const outcome = (r, value) => save(r, { outcome: value }, () => setOutcome(r.id, value),
    `${r.company}: ${OUTCOME_LABEL[value]}.${['rejected', 'closed'].includes(value) ? ' Moved to Closed.' : ''}`);
  const reopen = (r) => save(r, { outcome: null }, () => setOutcome(r.id, 'none'), `${r.company} is back under Applied.`);
  const followed = (r) => save(r, { checkedIn: true }, () => checkIn(r.id),
    `${r.company}: noted. It comes back here if nothing changes in 4 days.`);

  const lists = useMemo(() => {
    const todo = [], done = [], closed = [];
    for (const r of rows) {
      const v = view(r);
      if (v.applied && v.closed) closed.push(r);
      else if (v.applied) done.push(r);
      else if (r.listed) todo.push(r);
    }
    done.sort((a, b) => Number(view(b).checkIn) - Number(view(a).checkIn));
    return { todo, done, closed };
  }, [rows, local]); // eslint-disable-line react-hooks/exhaustive-deps

  const needle = query.trim().toLowerCase();
  const shown = lists[tab].filter((r) => !needle || r.search.includes(needle));
  const dueCount = lists.done.filter((r) => view(r).checkIn).length;
  const tabs = [['todo', 'To apply', lists.todo.length], ['done', 'Applied', lists.done.length], ['closed', 'Closed', lists.closed.length]];

  return (
    <>
      <div className="filters">
        <div className="chips" role="group" aria-label="Choose a list">
          {tabs.map(([key, label, n]) => (
            <button key={key} type="button" className="chip" aria-pressed={tab === key} onClick={() => setTab(key)}>
              {label}<span className="n">{n}</span>
            </button>
          ))}
        </div>
        <input className="search" type="search" placeholder="Search company, role, city" value={query}
          onChange={(event) => setQuery(event.target.value)} aria-label="Search jobs" />
      </div>
      {tab === 'done' && dueCount ? (
        <p className="banner">{dueCount} {dueCount === 1 ? 'job has' : 'jobs have'} had nothing new for 4 days or more. They are at the top under Check in: message the people on the job page, then press I followed up, or mark the result.</p>
      ) : null}
      <p role="status" aria-live="polite" className="muted">{status}</p>
      {shown.length === 0 ? (
        <p className="empty">{{ todo: 'Nothing left to apply to', done: 'No applications yet', closed: 'Nothing closed yet' }[tab]}{needle ? ' that matches that search' : ''}.</p>
      ) : (
        <ul className="leads">
          {shown.map((r) => {
            const v = view(r);
            const cls = v.closed ? ' is-closed' : v.applied ? ' is-applied' : '';
            return (
              <li key={r.id} className={`job${cls}${v.checkIn ? ' is-due' : ''}`}>
                <div>
                  <h3><Link href={`/lead/${r.id}`}>{r.title} <span className="at">· {r.company}</span></Link></h3>
                  {r.verdict ? <p className="verdict">{r.verdict}</p> : null}
                  {r.manual && r.note ? <p className="verdict">{r.note}</p> : null}
                  <p className="chips-line">
                    {v.checkIn ? <span className="tag due-tag">Check in · quiet {r.quietDays} days</span> : null}
                    {v.outcome ? <span className="tag">{OUTCOME_LABEL[v.outcome]}</span> : null}
                    {r.manual ? <span className="tag muted-tag">Added by you</span> : null}
                    {r.experience ? <span className={`tag${r.experienceKnown ? '' : ' muted-tag'}`}>{r.experience}</span> : null}
                    {r.location ? <span className="tag">{r.location}</span> : null}
                    {!v.applied && r.posted ? <span className="tag">{r.posted}</span> : null}
                    {r.people ? <span className="tag">{r.people} {r.people === 1 ? 'person' : 'people'} to message</span> : null}
                  </p>
                  {v.applied ? (
                    <p className="lead-meta">
                      <span>Applied {ago(v.fresh ? 0 : r.appliedDays)}</span>
                      {r.followUp && !OUTCOME_LABEL[v.outcome] ? <span className="sep">{r.followUp}</span> : null}
                    </p>
                  ) : null}
                </div>
                <div className="lead-side button-row">
                  {!v.applied ? (
                    r.applyUrl ? <a className="button primary" href={r.applyUrl} target="_blank" rel="noreferrer" onClick={() => apply(r)}>Apply</a>
                      : <button type="button" className="button primary" onClick={() => apply(r)}>Mark applied</button>
                  ) : v.closed ? (
                    <button type="button" className="button small" onClick={() => reopen(r)}>Reopen</button>
                  ) : (
                    <>
                      {v.checkIn ? <button type="button" className="button small primary" onClick={() => followed(r)}>I followed up</button> : null}
                      {v.outcome !== 'interview' ? <button type="button" className="button small" onClick={() => outcome(r, 'interview')}>Interview</button> : null}
                      <button type="button" className="button small" onClick={() => outcome(r, 'rejected')}>Rejected</button>
                      <button type="button" className="button small" onClick={() => outcome(r, 'closed')}>No response</button>
                      {v.fresh || (r.appliedAt && !r.followUp && !v.outcome) ? <button type="button" className="button small quiet" onClick={() => undo(r)}>Undo</button> : null}
                    </>
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
