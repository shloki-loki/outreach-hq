import { redirect } from 'next/navigation';
import JobList from '@/components/JobList';
import TopBar from '@/components/TopBar';
import TrackKpis from '@/components/TrackKpis';
import { requireSignIn } from '@/lib/auth';
import { loadBoard } from '@/lib/data';
import { STATUS, daysAgo } from '@/lib/status';
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

function followUp(lead) {
  if (['interview', 'offer'].includes(lead.status)) return STATUS[lead.status].label;
  if (lead.status === 'replied') return 'They replied';
  if (lead.status === 'followup_due') return 'Follow-up due';
  const sent = lead.messages.filter((m) => ['sent', 'replied', 'bounced'].includes(m.status));
  if (sent.length > 1) return `${sent.length - 1} follow-up${sent.length > 2 ? 's' : ''} sent`;
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
    .filter((lead) => lead.applied_at || (lead.stage === 'qualified' && lead.open !== false
      && !['rejected', 'closed', 'skipped'].includes(lead.status)))
    .map((lead) => ({
      id: lead.id, title: lead.title, company: lead.company, location: lead.location, score: lead.score?.total ?? 0,
      verdict: verdict(lead),
      experience: experience(lead) || 'Experience not stated', experienceKnown: lead.exp_min != null,
      posted: lead.posted_at && daysAgo(lead.posted_at) !== null ? `Posted ${daysAgo(lead.posted_at)}d ago` : '',
      people: (lead.contacts || []).filter((c) => c.linkedin_url).length,
      listed: lead.stage === 'qualified' && lead.open !== false,
      appliedAt: lead.applied_at || null, appliedDays: daysAgo(lead.applied_at), followUp: followUp(lead),
      applyUrl: /^https?:\/\//.test(lead.apply_url || '') ? lead.apply_url : '',
      search: `${lead.company} ${lead.title} ${lead.location}`.toLowerCase(),
    }))
    .sort((a, b) => (a.appliedAt && b.appliedAt ? (a.appliedAt < b.appliedAt ? 1 : -1) : b.score - a.score));

  return (
    <>
      <TopBar current="/" toApprove={toApprove} />
      <main>
        <div className="page-head">
          <h1>Agent Leads</h1>
          <p>Jobs you can apply to: the full posting was read, and none asks more than 3 years. Apply opens the posting and moves the job to Applied.</p>
        </div>
        <TrackKpis track="jobs" stats={stats} />
        <section className="section">
          <JobList rows={rows} initialTab={view === 'applied' || view === 'followups' ? 'done' : 'todo'} />
        </section>
      </main>
    </>
  );
}
