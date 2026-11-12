import Link from 'next/link';
import LeadList from '@/components/LeadList';
import TopBar from '@/components/TopBar';
import { requireSignIn } from '@/lib/auth';
import { counts, loadBoard } from '@/lib/data';
import { SOURCE_LABEL, STATUS, daysAgo } from '@/lib/status';

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

function payTone(fit = '') {
  if (fit.startsWith('In range')) return 'done';
  if (fit.startsWith('Possibly') || fit.startsWith('Likely in range')) return 'ready';
  if (fit.startsWith('Below') || fit.startsWith('Likely below')) return 'off';
  return 'new';
}

function payLabel(pay = {}) {
  const fit = pay.fit || 'Unknown';
  const range = pay.min_lpa && pay.max_lpa && pay.min_lpa !== pay.max_lpa ? `₹${pay.min_lpa}–${pay.max_lpa} LPA`
    : pay.max_lpa ? `₹${pay.max_lpa} LPA` : '';
  if (fit === 'Unknown') return 'Pay not known';
  return range ? `${range} · ${fit.replace(/\s*\(.*\)/, '')}` : fit;
}

function experience(lead) {
  if (lead.exp_min != null) return `Asks ${lead.exp_min}${lead.exp_max ? `–${lead.exp_max}` : '+'} yrs`;
  return '';
}

function address(lead) {
  const usable = (lead.contacts || []).filter((c) => c.email && !['bounced', 'invalid'].includes(c.email_status));
  if (usable.some((c) => c.email_status === 'verified')) return { label: 'Verified address', tone: 'done' };
  if (usable.some((c) => c.email_status === 'published')) return { label: 'Address from the posting', tone: 'done' };
  if (usable.some((c) => ['pattern', 'hunter'].includes(c.email_status))) return { label: 'Likely address', tone: 'ready' };
  if (usable.length) return { label: 'Unverified address', tone: 'due' };
  if ((lead.contacts || []).some((c) => c.name)) return { label: 'Person found, no address', tone: 'new' };
  return { label: 'No person yet', tone: 'new' };
}

function latestNote(lead) {
  if (lead.status === 'replied') {
    const reply = lead.messages.find((m) => m.status === 'replied')?.reply;
    return reply ? `Reply from ${reply.from}: “${(reply.snippet || '').slice(0, 110)}”` : 'They replied.';
  }
  if (lead.status === 'followup_due') return 'No reply yet. A follow-up is due and is being drafted.';
  if (lead.status === 'to_approve') {
    const failed = lead.messages.find((m) => m.status === 'failed');
    if (failed) return `A send failed: ${failed.error || 'unknown error'}`;
    const waiting = lead.messages.filter((m) => m.status === 'approved').length;
    const drafts = lead.messages.filter((m) => m.status === 'draft').length;
    return drafts ? `${drafts} draft${drafts > 1 ? 's' : ''} waiting for your approval.` : `${waiting} approved, waiting to send.`;
  }
  if (lead.status === 'contacted') {
    const sent = lead.messages.filter((m) => m.status === 'sent').sort((a, b) => (a.sent_at < b.sent_at ? 1 : -1))[0];
    if (sent) return `Emailed ${sent.to_name || sent.to} ${daysAgo(sent.sent_at) === 0 ? 'today' : `${daysAgo(sent.sent_at)}d ago`}.`;
    return 'Referral request sent.';
  }
  if (lead.status === 'rejected' && lead.reject_reason) return `Dropped: ${lead.reject_reason}`;
  if (lead.status === 'qualified' && !lead.contacts?.some((c) => c.email)) return 'Qualified. No email address found yet.';
  return '';
}

export default async function LeadsPage({ searchParams }) {
  await requireSignIn();
  const { view } = await searchParams;
  const { leads } = await loadBoard();
  const tally = counts(leads);
  const toApprove = leads.reduce((sum, lead) => sum + lead.messages.filter((m) => m.status === 'draft').length, 0);
  const rows = leads.map((lead) => ({
    id: lead.id, title: lead.title, company: lead.company, location: lead.location, status: lead.status,
    statusLabel: STATUS[lead.status].label, tone: STATUS[lead.status].tone, score: lead.score?.total ?? 0,
    pay: payLabel(lead.pay), payTone: payTone(lead.pay?.fit), source: SOURCE_LABEL[lead.source] || lead.source,
    verdict: verdict(lead), experience: experience(lead), address: address(lead), tier: (lead.tier || '').replace(/^\d\s*-\s*/, ''),
    companyNote: (lead.company_note || '').replace(/^Not found.*$/i, '').slice(0, 90), researched: Boolean(lead.research?.done),
    checked: lead.research?.researched_at ? daysAgo(lead.research.researched_at) : null,
    posted: lead.posted_at && daysAgo(lead.posted_at) !== null ? `Posted ${daysAgo(lead.posted_at)}d ago` : '',
    open: lead.open, stretch: lead.stretch, applied: Boolean(lead.applied_at) && lead.status !== 'applied',
    emails: (lead.contacts || []).filter((c) => c.email && !['bounced', 'invalid'].includes(c.email_status)).length,
    connections: (lead.referrals || []).length, note: latestNote(lead),
    captured: Boolean(lead.first_contacted_at || lead.applied_at), speculative: lead.type === 'company',
    search: `${lead.company} ${lead.title} ${lead.location} ${lead.tier || ''}`.toLowerCase(),
  }));
  const strip = [
    { label: 'Emails to approve', value: toApprove, href: '/approvals', tone: 't-approve' },
    { label: 'Follow-ups due', value: tally.followup_due || 0, href: '/?view=you', tone: 't-due' },
    { label: 'Replies', value: tally.replied || 0, href: '/?view=you', tone: 't-reply' },
    { label: 'Qualified, untouched', value: tally.qualified || 0, href: '/?view=qualified', tone: '' },
    { label: 'Contacted or applied', value: leads.filter((l) => l.first_contacted_at || l.applied_at).length, href: '/?view=captured', tone: 'hot' },
    { label: 'Interviews and offers', value: (tally.interview || 0) + (tally.offer || 0), href: '/?view=captured', tone: 'hot' },
  ];

  return (
    <>
      <TopBar current="/" toApprove={toApprove} />
      <main>
        <div className="page-head">
          <h1>Leads</h1>
          <p>Each row carries its own verdict: why it fits, the pay, the experience asked and whether there is a verified address. Top picks are the researched leads scoring 75 or more. A row turns green once you have emailed someone there or applied.</p>
        </div>
        <dl className="highlights six">
          {strip.map((item) => (
            <Link key={item.label} href={item.href} className={`highlight ${item.tone}`}>
              <dd>{item.value}</dd><dt>{item.label}</dt>
            </Link>
          ))}
        </dl>
        <section className="section">
          <ul className="legend" aria-label="Colour key">
            <li><span className="dot" style={{ background: 'var(--new-bar)' }} />Not researched</li>
            <li><span className="dot" style={{ background: 'var(--ready-bar)' }} />Qualified</li>
            <li><span className="dot" style={{ background: 'var(--approve-bar)' }} />Needs your approval</li>
            <li><span className="dot" style={{ background: 'var(--done-bar)' }} />Contacted or applied</li>
            <li><span className="dot" style={{ background: 'var(--due-bar)' }} />Follow-up due</li>
            <li><span className="dot" style={{ background: 'var(--reply-bar)' }} />Replied</li>
            <li><span className="dot" style={{ background: 'var(--win-bar)' }} />Interview or offer</li>
            <li><span className="dot" style={{ background: 'var(--off-bar)' }} />Rejected or closed</li>
          </ul>
          <LeadList key={view || 'top'} rows={rows} initialView={view || 'top'} />
        </section>
      </main>
    </>
  );
}
