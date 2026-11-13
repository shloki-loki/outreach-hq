import Link from 'next/link';
import TopBar from '@/components/TopBar';
import { requireSignIn } from '@/lib/auth';
import { read } from '@/lib/store';

export const dynamic = 'force-dynamic';

const WHO = {
  'lead-scout/scrape': 'Lead scout (job boards)', 'lead-scout': 'Lead scout', 'email-finder': 'Email finder',
  'send-track': 'Send and track', 'send-track/send': 'Sender', 'follow-up/track': 'Inbox check',
  'follow-up': 'Follow-up', 'follow-up/digest': 'Morning digest', supervisor: 'Supervisor', session: 'Claude session',
};
const KIND = {
  run: ['Ran', 'tone-done'], failed: ['Run failed', 'tone-off'], issue: ['Problem', 'tone-due'],
  debug: ['Diagnosis', 'tone-approve'], fix: ['Fixed', 'tone-done'], update: ['Change', 'tone-new'],
  review: ['Daily review', 'tone-reply'], note: ['Note', 'tone-new'],
};
const VIEWS = [
  ['all', 'Everything', null],
  ['problems', 'Problems and fixes', ['issue', 'failed', 'debug', 'fix']],
  ['changes', 'Changes and reviews', ['update', 'review', 'note']],
  ['runs', 'Agent runs', ['run', 'failed']],
];
const IST = { timeZone: 'Asia/Kolkata' };
const dayOf = (iso) => new Date(iso).toLocaleDateString('en-IN', { ...IST, weekday: 'long', day: 'numeric', month: 'long' });
const timeOf = (iso) => new Date(iso).toLocaleTimeString('en-IN', { ...IST, hour: 'numeric', minute: '2-digit', hour12: true });

export default async function LogPage({ searchParams }) {
  await requireSignIn();
  const { view = 'all' } = await searchParams;
  const [journal, messages, issues] = await Promise.all([read('journal'), read('messages'), read('issues')]);
  const entries = [...(journal.entries || [])].reverse();
  const kinds = (VIEWS.find(([key]) => key === view) || VIEWS[0])[2];
  const shown = entries.filter((entry) => !kinds || kinds.includes(entry.kind)).slice(0, 400);
  const open = (issues.issues || []).filter((issue) => issue.status === 'open').length;
  const days = [];
  for (const entry of shown) {
    const day = dayOf(entry.at);
    if (!days.length || days[days.length - 1].day !== day) days.push({ day, entries: [] });
    days[days.length - 1].entries.push(entry);
  }

  return (
    <>
      <TopBar current="/log" toApprove={(messages.messages || []).filter((m) => m.status === 'draft').length} />
      <main>
        <div className="page-head">
          <h1>Supervisor log</h1>
          <p>Everything that happened, newest first: each agent run, each problem with its diagnosis and fix,
            and each change made to the system. {open ? `${open} problem${open > 1 ? 's are' : ' is'} open.` : 'No problems are open.'}</p>
        </div>
        <nav className="chips" style={{ margin: '22px 0 6px' }} aria-label="Filter the log">
          {VIEWS.map(([key, label, only]) => (
            <Link key={key} href={key === 'all' ? '/log' : `/log?view=${key}`} className="chip link" aria-current={view === key || (key === 'all' && !kinds) ? 'true' : undefined}>
              {label}<span className="n">{entries.filter((entry) => !only || only.includes(entry.kind)).length}</span>
            </Link>
          ))}
        </nav>
        {days.length === 0 ? <p className="empty" style={{ marginTop: 24 }}>Nothing logged here yet.</p> : days.map(({ day, entries: rows }) => (
          <section className="section" key={day}>
            <h2 className="section-label">{day}<span className="n">{rows.length}</span></h2>
            <ul className="list log">{rows.map((entry) => {
              const [label, tone] = KIND[entry.kind] || [entry.kind, 'tone-new'];
              return (
                <li key={entry.id}>
                  <span className="when">{timeOf(entry.at)}<br />{WHO[entry.by] || entry.by}</span>
                  <span>
                    <span className={`tag ${tone}`}>{label}</span>{' '}
                    {['run', 'failed'].includes(entry.kind) ? null : <strong>{entry.title.replace(/^(Diagnosis|Solved): /, '')}</strong>}
                    {entry.ref ? <span className="ref"> {entry.ref}</span> : null}
                    {entry.detail ? <span className="detail">{entry.detail}</span> : null}
                  </span>
                </li>
              );
            })}</ul>
          </section>
        ))}
      </main>
    </>
  );
}
