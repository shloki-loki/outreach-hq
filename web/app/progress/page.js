import TopBar from '@/components/TopBar';
import TrackKpis from '@/components/TrackKpis';
import { requireSignIn } from '@/lib/auth';
import { loadBoard } from '@/lib/data';
import { read, sendingMode } from '@/lib/store';
import { SOURCE_LABEL, formatDateTime } from '@/lib/status';
import { TRACKS, hadInterview, inTrack, replyCount, trackStats } from '@/lib/tracks';

export const dynamic = 'force-dynamic';

const AGENT = {
  'lead-scout/scrape': 'Lead scout: job boards', 'lead-scout': 'Lead scout: research and emails',
  'send-track': 'Send and track: drafting', 'send-track/send': 'Send and track: sender',
  'follow-up/track': 'Follow-up: inbox and timers', 'follow-up': 'Follow-up: drafting',
  'follow-up/digest': 'Follow-up: morning digest', supervisor: 'Supervisor',
};
function funnel(track, leads) {
  const end = [
    ['Replied', leads.filter((l) => replyCount(l) > 0).length],
    ['Interviews', leads.filter(hadInterview).length],
    ['Offers', leads.filter((l) => l.outcome === 'offer').length],
  ];
  const reached = (lead) => lead.messages.some((m) => ['sent', 'replied'].includes(m.status));
  if (track === 'cold') return [['Companies', leads.length], ['Emailed', leads.filter(reached).length], ...end];
  return [
    ['Leads found', leads.length],
    ['Researched', leads.filter((l) => l.research?.done).length],
    ['Qualified', leads.filter((l) => l.stage === 'qualified').length],
    ['Contacted or applied', leads.filter((l) => l.first_contacted_at || l.applied_at || reached(l)).length],
    ...end,
  ];
}

function lastDays(leads) {
  const messages = leads.flatMap((lead) => lead.messages);
  const days = [];
  for (let back = 20; back >= 0; back -= 1) {
    const key = new Date(Date.now() + 5.5 * 3600 * 1000 - back * 86400000).toISOString().slice(0, 10);
    days.push({ key,
      sent: messages.filter((m) => ['sent', 'replied', 'bounced'].includes(m.status) && (m.sent_at || '').startsWith(key)).length,
      replies: messages.filter((m) => (m.reply?.at || '').startsWith(key)).length });
  }
  return days;
}

function TrackProgress({ track, leads, children }) {
  const { label, about } = TRACKS[track];
  const stages = funnel(track, leads);
  const top = Math.max(1, stages[0][1]);
  const days = lastDays(leads);
  const peak = Math.max(1, ...days.map((d) => d.sent + d.replies));
  return (
    <section className="track" aria-labelledby={`${track}-title`}>
      <h2 id={`${track}-title`} className="track-title">{label}</h2>
      <p className="prose">{about}</p>
      <TrackKpis track={track} stats={trackStats(leads)} />
      <div className="section">
        <h3 className="section-label">Funnel</h3>
        <ul className="funnel">{stages.map(([name, value]) => (
          <li key={name}><span>{name}</span><span className="bar"><span style={{ width: `${(value / top) * 100}%` }} /></span><b>{value}</b></li>
        ))}</ul>
      </div>
      <div className="section">
        <h3 className="section-label">Last 21 days: emails sent (green) and replies (pink)</h3>
        <ul className="days" aria-label={`${label}: emails sent and replies per day`}>{days.map((day) => (
          <li key={day.key} title={`${day.key}: ${day.sent} sent, ${day.replies} replies`}>
            {day.replies ? <span className="rep" style={{ height: `${(day.replies / peak) * 100}%` }} /> : null}
            <span className="sent" style={{ height: `${(day.sent / peak) * 100}%` }} />
          </li>
        ))}</ul>
      </div>
      {children}
    </section>
  );
}

export default async function ProgressPage() {
  await requireSignIn();
  const [{ leads, messages }, issuesFile, runsFile, metricsFile, mode] = await Promise.all([
    loadBoard(), read('issues'), read('runs'), read('metrics'), sendingMode()]);
  const toApprove = messages.filter((m) => m.status === 'draft').length;
  const agentLeads = inTrack(leads, 'jobs');
  const sources = {};
  for (const lead of agentLeads) {
    const name = SOURCE_LABEL[lead.source] || lead.source || 'Other';
    sources[name] = sources[name] || { found: 0, qualified: 0, captured: 0, replied: 0 };
    sources[name].found += 1;
    if (lead.stage === 'qualified') sources[name].qualified += 1;
    if (lead.first_contacted_at || lead.applied_at) sources[name].captured += 1;
    if (replyCount(lead)) sources[name].replied += 1;
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
          <p>Agent Leads and Cold Emails, counted separately, then whether every agent is running.</p>
        </div>
        <TrackProgress track="jobs" leads={agentLeads}>
        <div className="section">
          <h3 className="section-label">By source</h3>
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Source</th><th>Found</th><th>Qualified</th><th>Contacted or applied</th><th>Replied</th></tr></thead>
            <tbody>{Object.entries(sources).sort((a, b) => b[1].found - a[1].found).map(([name, row]) => (
              <tr key={name}><td>{name}</td><td>{row.found}</td><td>{row.qualified}</td><td>{row.captured}</td><td>{row.replied}</td></tr>
            ))}</tbody>
          </table></div>
        </div>
        </TrackProgress>
        <TrackProgress track="cold" leads={inTrack(leads, 'cold')} />

        <section className="section system">
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
