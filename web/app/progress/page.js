import TopBar from '@/components/TopBar';
import { requireSignIn } from '@/lib/auth';
import { counts, loadBoard } from '@/lib/data';
import { read, sendingMode } from '@/lib/store';
import { SOURCE_LABEL, formatDateTime } from '@/lib/status';

export const dynamic = 'force-dynamic';

const AGENT = {
  'lead-scout/scrape': 'Lead scout: job boards', 'lead-scout': 'Lead scout: research and emails',
  'send-track': 'Send and track: drafting', 'send-track/send': 'Send and track: sender',
  'follow-up/track': 'Follow-up: inbox and timers', 'follow-up': 'Follow-up: drafting',
  'follow-up/digest': 'Follow-up: morning digest', supervisor: 'Supervisor',
};
const pct = (part, whole) => (whole ? `${Math.round((part / whole) * 100)}%` : 'n/a');

export default async function ProgressPage() {
  await requireSignIn();
  const [{ leads, messages }, issuesFile, runsFile, metricsFile, mode] = await Promise.all([
    loadBoard(), read('issues'), read('runs'), read('metrics'), sendingMode()]);
  const tally = counts(leads);
  const toApprove = messages.filter((m) => m.status === 'draft').length;
  const delivered = messages.filter((m) => ['sent', 'replied', 'bounced'].includes(m.status));
  const cold = delivered.filter((m) => m.kind === 'cold');
  const repliedPeople = new Set(messages.filter((m) => m.status === 'replied').map((m) => `${m.lead_id}:${m.contact_id}`)).size;
  const bounced = delivered.filter((m) => m.status === 'bounced').length;
  const captured = leads.filter((l) => l.first_contacted_at || l.applied_at || l.messages.some((m) => ['sent', 'replied'].includes(m.status))).length;
  const stages = [
    ['Leads found', leads.length],
    ['Researched', leads.filter((l) => l.research?.done).length],
    ['Qualified', leads.filter((l) => l.stage === 'qualified').length],
    ['Contacted or applied', captured],
    ['Replied', leads.filter((l) => l.replied_at).length],
    ['Interviews', leads.filter((l) => ['interview', 'offer'].includes(l.outcome)).length],
    ['Offers', tally.offer || 0],
  ];
  const top = Math.max(1, stages[0][1]);

  const days = [];
  for (let back = 20; back >= 0; back -= 1) {
    const key = new Date(Date.now() + 5.5 * 3600 * 1000 - back * 86400000).toISOString().slice(0, 10);
    days.push({ key, sent: delivered.filter((m) => (m.sent_at || '').startsWith(key)).length,
      replies: messages.filter((m) => (m.reply?.at || '').startsWith(key)).length });
  }
  const peak = Math.max(1, ...days.map((d) => d.sent + d.replies));

  const sources = {};
  for (const lead of leads) {
    const name = SOURCE_LABEL[lead.source] || lead.source || 'Other';
    sources[name] = sources[name] || { found: 0, qualified: 0, captured: 0, replied: 0 };
    sources[name].found += 1;
    if (lead.stage === 'qualified') sources[name].qualified += 1;
    if (lead.first_contacted_at || lead.applied_at) sources[name].captured += 1;
    if (lead.replied_at) sources[name].replied += 1;
  }
  const latest = {};
  for (const run of runsFile.runs || []) latest[run.agent] = run;
  const openIssues = (issuesFile.issues || []).filter((i) => i.status === 'open');
  const solved = (issuesFile.issues || []).filter((i) => i.status !== 'open').slice(-8).reverse();
  const snapshots = Object.keys(metricsFile.days || {}).length;

  return (
    <>
      <TopBar current="/progress" toApprove={toApprove} />
      <main>
        <div className="page-head">
          <h1>Progress</h1>
          <p>Where the search stands, what converts, and whether every agent is running.</p>
        </div>
        <dl className="highlights six">
          <div className="highlight"><dd>{cold.length}</dd><dt>Cold emails sent</dt></div>
          <div className="highlight t-reply"><dd>{pct(repliedPeople, cold.length)}</dd><dt>Reply rate ({repliedPeople} people)</dt></div>
          <div className={`highlight ${bounced / Math.max(1, delivered.length) > 0.05 ? 't-due' : ''}`}><dd>{pct(bounced, delivered.length)}</dd><dt>Bounce rate (keep under 5%)</dt></div>
          <div className="highlight"><dd>{leads.filter((l) => l.applied_at).length}</dd><dt>Applications</dt></div>
          <div className="highlight"><dd>{leads.reduce((n, l) => n + (l.referrals || []).filter((r) => ['sent', 'replied'].includes(r.status)).length, 0)}</dd><dt>Referrals asked</dt></div>
          <div className="highlight hot"><dd>{(tally.interview || 0) + (tally.offer || 0)}</dd><dt>Interviews and offers</dt></div>
        </dl>

        <section className="section">
          <h2 className="section-label">Funnel</h2>
          <ul className="funnel">{stages.map(([name, value]) => (
            <li key={name}><span>{name}</span><span className="bar"><span style={{ width: `${(value / top) * 100}%` }} /></span><b>{value}</b></li>
          ))}</ul>
        </section>

        <section className="section">
          <h2 className="section-label">Last 21 days: emails sent (green) and replies (pink)</h2>
          <ul className="days" aria-label="Emails sent and replies per day">{days.map((day) => (
            <li key={day.key} title={`${day.key}: ${day.sent} sent, ${day.replies} replies`}>
              {day.replies ? <span className="rep" style={{ height: `${(day.replies / peak) * 100}%` }} /> : null}
              <span className="sent" style={{ height: `${(day.sent / peak) * 100}%` }} />
            </li>
          ))}</ul>
        </section>

        <section className="section">
          <h2 className="section-label">By source</h2>
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Source</th><th>Found</th><th>Qualified</th><th>Contacted or applied</th><th>Replied</th></tr></thead>
            <tbody>{Object.entries(sources).sort((a, b) => b[1].found - a[1].found).map(([name, row]) => (
              <tr key={name}><td>{name}</td><td>{row.found}</td><td>{row.qualified}</td><td>{row.captured}</td><td>{row.replied}</td></tr>
            ))}</tbody>
          </table></div>
        </section>

        <section className="section">
          <h2 className="section-label">Agents</h2>
          <p className="prose">Sending mode: <strong>{mode === 'live' ? 'live' : mode === 'dry_run' ? 'dry run (nothing is sent)' : 'unknown'}</strong>. Daily snapshots stored: {snapshots}.</p>
          {Object.keys(latest).length === 0 ? <p className="empty">No agent has reported a run yet.</p> : (
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Agent</th><th>Last run</th><th>Result</th></tr></thead>
              <tbody>{Object.entries(latest).sort((a, b) => (a[1].at < b[1].at ? 1 : -1)).map(([agent, run]) => (
                <tr key={agent}><td><span className={`health ${run.ok ? '' : 'bad'}`} />{AGENT[agent] || agent}</td><td style={{ whiteSpace: 'nowrap' }}>{formatDateTime(run.at)}</td><td>{run.summary}</td></tr>
              ))}</tbody>
            </table></div>
          )}
        </section>

        <section className="section">
          <h2 className="section-label">Open issues<span className="n">{openIssues.length}</span></h2>
          <p className="prose">Every run, problem, diagnosis and fix is in the <a href="/log" style={{ color: 'var(--accent)' }}>supervisor log</a>.</p>
          {openIssues.length === 0 ? <p className="empty">No open issues.</p> : (
            <ul className="list">{openIssues.map((issue) => (
              <li key={issue.id}><span className="when">{formatDateTime(issue.last_seen)}<br />{issue.agent}{issue.count > 1 ? ` · seen ${issue.count}x` : ''}</span>
                <span><strong>{issue.title}</strong><br />{issue.detail}{issue.remedy ? <><br /><strong>Remedy:</strong> {issue.remedy}</> : null}</span></li>
            ))}</ul>
          )}
        </section>

        {solved.length > 0 ? (
          <section className="section">
            <h2 className="section-label">Recently solved</h2>
            <ul className="list">{solved.map((issue) => (
              <li key={issue.id}><span className="when">{formatDateTime(issue.resolved_at)}</span><span><strong>{issue.title}</strong>{issue.remedy ? ` · ${issue.remedy}` : ''}</span></li>
            ))}</ul>
          </section>
        ) : null}
      </main>
    </>
  );
}
