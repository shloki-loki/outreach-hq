import Link from 'next/link';
import ApproveAll from '@/components/ApproveAll';
import MessageCard from '@/components/MessageCard';
import TopBar from '@/components/TopBar';
import { requireSignIn } from '@/lib/auth';
import { loadBoard } from '@/lib/data';
import { sendingMode } from '@/lib/store';
import { EMAIL_BADGE } from '@/lib/status';

export const dynamic = 'force-dynamic';

export default async function ApprovalsPage({ searchParams }) {
  await requireSignIn();
  const [{ leads, messages }, mode] = await Promise.all([loadBoard(), sendingMode()]);
  const { view } = await searchParams;
  const filters = [
    { id: 'all', label: 'All mail', href: '/approvals' },
    { id: 'jobs', label: 'Job outreach', href: '/approvals?view=jobs' },
    { id: 'cold', label: 'Cold Mails', href: '/approvals?view=cold' },
  ];
  const active = filters.find((filter) => filter.id === view)?.id || 'all';
  const matches = (lead) => active === 'all' || (active === 'cold' ? lead?.type === 'company' : Boolean(lead) && lead.type !== 'company');
  const leadById = Object.fromEntries(leads.map((lead) => [lead.id, lead]));
  const label = (message) => {
    const lead = leadById[message.lead_id];
    return lead ? `${lead.title} · ${lead.company}` : message.lead_id;
  };
  const badge = (message) => {
    const contact = (leadById[message.lead_id]?.contacts || []).find((c) => c.id === message.contact_id);
    return EMAIL_BADGE[contact?.email_status || message.email_status];
  };
  const by = (status) => messages.filter((m) => m.status === status && matches(leadById[m.lead_id]));
  const drafts = by('draft').sort((a, b) => (a.kind === b.kind ? (a.created_at < b.created_at ? -1 : 1) : a.kind === 'cold' ? 1 : -1));
  const waiting = by('approved');
  const trouble = [...by('failed'), ...by('sending')];
  const followDue = leads.filter((lead) => lead.followup?.due && matches(lead));
  const today = new Date(Date.now() + 5.5 * 3600 * 1000).toISOString().slice(0, 10);
  const sentToday = messages.filter((m) => (m.sent_at || '').startsWith(today)).length;

  return (
    <>
      <TopBar current="/approvals" toApprove={messages.filter((message) => message.status === 'draft').length} />
      <main>
        <div className="page-head">
          <h1>Approvals</h1>
          <p>Review drafts and check the send queue. {sentToday} sent today across all mail.</p>
        </div>
        <nav className="chips" aria-label="Filter approvals">
          {filters.map((filter) => (
            <Link key={filter.id} href={filter.href} className="chip link" aria-current={active === filter.id ? 'true' : undefined}>
              {filter.label}
            </Link>
          ))}
        </nav>
        {mode !== 'live' ? (
          <p className="banner">Dry run is on: approving marks an email as approved but nothing is sent. To go live, set <strong>mode = "live"</strong> in config/settings.toml after the test email to yourself works.</p>
        ) : null}

        {trouble.length > 0 ? (
          <section className="section">
            <h2 className="section-label">Needs a look<span className="n">{trouble.length}</span></h2>
            {trouble.map((message) => <MessageCard key={`${message.id}-${message.status}`} message={message} mode={mode} showLead leadLabel={label(message)} emailBadge={badge(message)} />)}
          </section>
        ) : null}

        <section className="section">
          <div className="card-head">
            <h2 className="section-label" style={{ margin: 0 }}>Waiting for you<span className="n">{drafts.length}</span></h2>
            <ApproveAll key={active} ids={drafts.map((m) => m.id)} mode={mode} />
          </div>
          {drafts.length === 0 ? <p className="empty">Nothing to approve. New drafts appear here after the send agent's next run.</p>
            : drafts.map((message) => <MessageCard key={`${message.id}-${message.status}`} message={message} mode={mode} showLead leadLabel={label(message)} emailBadge={badge(message)} />)}
        </section>

        {followDue.length > 0 ? (
          <section className="section">
            <h2 className="section-label">Follow-up due, draft not written yet<span className="n">{followDue.length}</span></h2>
            <ul className="list">{followDue.map((lead) => (
              <li key={lead.id}><span className="when">{lead.followup.kind === 'followup2' ? 'Second follow-up' : 'First follow-up'}</span>
                <span><a className="link" href={`/lead/${lead.id}`}>{lead.title} · {lead.company}</a>. The follow-up agent drafts it on its next run.</span></li>
            ))}</ul>
          </section>
        ) : null}

        {waiting.length > 0 ? (
          <section className="section">
            <h2 className="section-label">Approved, waiting to send<span className="n">{waiting.length}</span></h2>
            {waiting.map((message) => <MessageCard key={`${message.id}-${message.status}`} message={message} mode={mode} showLead leadLabel={label(message)} emailBadge={badge(message)} />)}
          </section>
        ) : null}
      </main>
    </>
  );
}
