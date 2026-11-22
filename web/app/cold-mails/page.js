import Link from 'next/link';
import LeadList from '@/components/LeadList';
import TopBar from '@/components/TopBar';
import TrackKpis from '@/components/TrackKpis';
import { requireSignIn } from '@/lib/auth';
import { loadBoard } from '@/lib/data';
import { formatDate } from '@/lib/status';
import { coldState, hadInterview, inTrack, replyCount, trackStats } from '@/lib/tracks';

export const dynamic = 'force-dynamic';

function activity(lead) {
  const sent = lead.messages.filter((m) => ['sent', 'replied', 'bounced'].includes(m.status));
  if (!sent.length) return '';
  const people = new Set(sent.map((m) => m.contact_id)).size;
  const last = sent.map((m) => m.sent_at || '').sort().at(-1);
  return `${people} ${people === 1 ? 'person' : 'people'} emailed${last ? `, last on ${formatDate(last)}` : ''}`;
}

export default async function ColdMailsPage({ searchParams }) {
  await requireSignIn();
  const { view } = await searchParams;
  const { leads: allLeads, messages } = await loadBoard();
  const leads = inTrack(allLeads, 'cold');
  const stats = trackStats(leads);
  const rows = leads.map((lead) => {
    const state = coldState(lead);
    return {
      id: lead.id,
      company: lead.company,
      search: (lead.company || '').toLowerCase(),
      status: state.status,
      statusLabel: state.label,
      tone: state.tone,
      rank: state.rank,
      messageStatuses: lead.messages.map((message) => message.status),
      followupDue: Boolean(lead.followup?.due),
      replies: replyCount(lead),
      interviewed: hadInterview(lead),
      offered: lead.outcome === 'offer',
      note: activity(lead),
    };
  }).sort((a, b) => a.rank - b.rank);
  const queue = [
    { label: 'Companies on the list', value: leads.length, href: '/cold-mails?view=all' },
    { label: 'Emails queued', value: stats.queued, href: '/cold-mails?view=queued', tone: 'hot' },
    { label: 'Emails to approve', value: stats.drafts, href: '/approvals?view=cold', tone: 't-approve' },
    { label: 'Follow-ups due', value: stats.followupsDue, href: '/cold-mails?view=followups', tone: 't-due' },
  ];

  return (
    <>
      <TopBar current="/cold-mails" toApprove={messages.filter((message) => message.status === 'draft').length} />
      <main>
        <div className="page-head">
          <h1>Cold Emails</h1>
          <p>Your founder list, counted on its own. Nothing the agent found is included here.</p>
        </div>
        <h2 className="section-label strip-label">Results</h2>
        <TrackKpis track="cold" stats={stats} />
        <h2 className="section-label strip-label">In progress</h2>
        <dl className="highlights four">
          {queue.map((item) => (
            <Link key={item.label} href={item.href} className={`highlight ${item.tone || ''}`}>
              <dd>{item.value}</dd><dt>{item.label}</dt>
            </Link>
          ))}
        </dl>
        <section className="section">
          <LeadList key={view || 'all'} rows={rows} initialView={view || 'all'} coldMails />
        </section>
      </main>
    </>
  );
}
