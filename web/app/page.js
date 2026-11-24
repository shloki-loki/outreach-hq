import { redirect } from 'next/navigation';
import JobList from '@/components/JobList';
import ManualAdd from '@/components/ManualAdd';
import TopBar from '@/components/TopBar';
import TrackKpis from '@/components/TrackKpis';
import { requireSignIn } from '@/lib/auth';
import { loadBoard } from '@/lib/data';
import { daysAgo } from '@/lib/status';
import { inTrack, trackStats } from '@/lib/tracks';

export const dynamic = 'force-dynamic';

function verdict(lead) {
  if (lead.research?.headline) return lead.research.headline;
  const notes = (lead.research?.fit_notes || '').trim();
  if (notes) {
    const first = notes.split(/(?<=[.!?])\s+/)[0];
    return first.length > 170 ? `${first.slice(0, 167)}…` : first;
  }
  return '';
}

function experience(lead) {
  if (lead.exp_min != null) return `Asks ${lead.exp_min}${lead.exp_max ? `–${lead.exp_max}` : '+'} yrs`;
  return '';
}

const SENT = ['sent', 'replied', 'bounced'];
const CHECK_IN_DAYS = 4; // Shlok, 2026-11-24: nudge him when an applied job has had nothing new for 3-4 days

// Applied means he applied by any route: the Apply button, an email that went out, a reply or an outcome.
// (2026-11-24: a job applied to by email kept showing under To apply.)
function appliedAt(lead) {
  if (lead.applied_at) return lead.applied_at;
  const sent = lead.messages.filter((m) => SENT.includes(m.status) && m.sent_at).map((m) => m.sent_at).sort();
  if (sent.length) return sent[0];
  if (lead.replied_at) return lead.replied_at;
  if (lead.outcome) return lead.outcome_at || lead.first_contacted_at || lead.first_seen || null;
  return null;
}

function lastActivity(lead, applied) {
  const times = [applied, lead.replied_at, lead.outcome_at, lead.checked_in_at,
    ...lead.messages.map((m) => m.sent_at), ...(lead.notes || []).map((n) => n.at)].filter(Boolean);
  return times.sort().pop() || null;
}

function followUp(lead) {
  if (lead.outcome === 'interview') return 'Interview';
  if (lead.outcome === 'offer') return 'Offer';
  if (lead.outcome === 'rejected') return 'Rejected';
  if (lead.outcome === 'closed') return 'No response';
  if (lead.status === 'replied') return 'They replied';
  if (lead.status === 'followup_due') return 'Email follow-up due';
  const sent = lead.messages.filter((m) => SENT.includes(m.status));
  if (sent.length > 1) return `${sent.length - 1} email follow-up${sent.length > 2 ? 's' : ''} sent`;
  if (sent.length === 1) return 'Emailed once, no reply yet';
  return '';
}

export default async function LeadsPage({ searchParams }) {
  await requireSignIn();
  const { view } = await searchParams;
  if (view === 'spec') redirect('/cold-mails');
  const { leads: allLeads, messages } = await loadBoard();
  const leads = inTrack(allLeads, 'jobs').filter((lead) => lead.type === 'job');
  const stats = trackStats(inTrack(allLeads, 'jobs'));
  const toApprove = messages.filter((message) => message.status === 'draft').length;
  const rows = leads
    .map((lead) => ({ lead, applied: appliedAt(lead) }))
    .filter(({ lead, applied }) => applied || (lead.stage === 'qualified' && lead.open !== false
      && !['rejected', 'closed', 'skipped'].includes(lead.status)))
    .map(({ lead, applied }) => {
      const closed = ['rejected', 'closed'].includes(lead.outcome);
      const quiet = daysAgo(lastActivity(lead, applied));
      return {
        id: lead.id, title: lead.title, company: lead.company, location: lead.location, score: lead.score?.total ?? 0,
        verdict: verdict(lead), manual: lead.source === 'manual', note: (lead.notes || []).slice(-1)[0]?.text || '',
        experience: experience(lead) || (lead.source === 'manual' ? '' : 'Experience not stated'), experienceKnown: lead.exp_min != null,
        posted: lead.posted_at && daysAgo(lead.posted_at) !== null ? `Posted ${daysAgo(lead.posted_at)}d ago` : '',
        people: (lead.contacts || []).filter((c) => c.linkedin_url).length,
        listed: lead.stage === 'qualified' && lead.open !== false,
        appliedAt: applied, appliedDays: daysAgo(applied), followUp: followUp(lead), outcome: lead.outcome || null,
        closed, checkIn: Boolean(applied) && !closed && !['interview', 'offer'].includes(lead.outcome)
          && lead.status !== 'replied' && quiet !== null && quiet >= CHECK_IN_DAYS,
        quietDays: quiet,
        applyUrl: /^https?:\/\//.test(lead.apply_url || '') ? lead.apply_url : '',
        search: `${lead.company} ${lead.title} ${lead.location || ''}`.toLowerCase(),
      };
    })
    .sort((a, b) => (a.appliedAt && b.appliedAt ? (a.appliedAt < b.appliedAt ? 1 : -1) : b.score - a.score));

  return (
    <>
      <TopBar current="/" toApprove={toApprove} />
      <main>
        <div className="page-head">
          <h1>Agent Leads</h1>
          <p>To apply: jobs where the full posting was read and none asks more than 3 years. Applied: everything you applied to or emailed, with a check-in reminder after 4 quiet days. Closed: rejected or no response.</p>
        </div>
        <TrackKpis track="jobs" stats={stats} />
        <section className="section">
          <div style={{ marginBottom: 14 }}><ManualAdd /></div>
          <JobList rows={rows} initialTab={view === 'applied' || view === 'followups' ? 'done' : view === 'closed' ? 'closed' : 'todo'} />
        </section>
      </main>
    </>
  );
}
