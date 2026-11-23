import Link from 'next/link';
import { notFound } from 'next/navigation';
import InMailNote from '@/components/InMailNote';
import JobActions from '@/components/JobActions';
import MessageCard from '@/components/MessageCard';
import TopBar from '@/components/TopBar';
import { requireSignIn } from '@/lib/auth';
import { loadBoard } from '@/lib/data';
import { read, sendingMode } from '@/lib/store';
import { EMAIL_BADGE, SOURCE_LABEL, displayStatus, formatDate } from '@/lib/status';
import { TRACKS, trackOf } from '@/lib/tracks';

export const dynamic = 'force-dynamic';

// Simplified on Shlok's review (2026-11-23): apply, the people to InMail with one note, why it fits, the posting.
// Cover notes, application answers, notes and the connections search were removed.
const ROLE = { hiring_manager: 'Hiring manager', team_lead: 'Team lead', recruiter: 'Recruiter', founder: 'Founder',
  employee: 'Works there', generic: 'Company address' };
const ROLE_ORDER = ['hiring_manager', 'team_lead', 'recruiter', 'founder', 'employee'];
const isUrl = (value) => /^https?:\/\//.test(value || '');

async function findLead(id) {
  const { leads, messages } = await loadBoard();
  const lead = leads.find((item) => item.id === id);
  if (lead) return { lead, leads };
  const full = (await read('leads')).leads || [];  // not on the board (rejected or unresearched): read the full file
  const found = full.find((item) => item.id === id);
  if (!found) return { lead: null, leads };
  const mine = messages.filter((m) => m.lead_id === id);
  return { lead: { ...found, messages: mine, status: displayStatus(found, mine) }, leads };
}

export default async function LeadPage({ params }) {
  await requireSignIn();
  const { id } = await params;
  const [{ lead, leads }, mode] = await Promise.all([findLead(id), sendingMode()]);
  if (!lead) notFound();
  const toApprove = leads.reduce((sum, item) => sum + item.messages.filter((m) => m.status === 'draft').length, 0);
  const track = TRACKS[trackOf(lead)];
  const messages = [...lead.messages].sort((a, b) => (a.created_at < b.created_at ? -1 : 1));
  const contactById = Object.fromEntries((lead.contacts || []).map((c) => [c.id, c]));
  const people = (lead.contacts || []).filter((c) => isUrl(c.linkedin_url))
    .sort((a, b) => ROLE_ORDER.indexOf(a.role_type) - ROLE_ORDER.indexOf(b.role_type));
  const isJob = lead.type === 'job';
  const experience = lead.exp_min != null ? `Asks ${lead.exp_min}${lead.exp_max ? `–${lead.exp_max}` : '+'} years` : 'Experience not stated';

  return (
    <>
      <TopBar current={track.href} toApprove={toApprove} />
      <main>
        <Link href={track.href} className="back">← {track.label}</Link>
        <div className="page-head" style={{ paddingTop: 18 }}>
          <h1>{lead.title}</h1>
          <p><strong>{lead.company}</strong>{lead.company_note ? ` · ${lead.company_note}` : ''}</p>
          {lead.research?.headline ? <p style={{ color: 'var(--ink)', fontSize: 16 }}>{lead.research.headline}</p> : null}
          <p className="chips-line">
            {isJob ? <span className="tag">{experience}</span> : null}
            <span className="tag">{lead.location || 'Location not stated'}{lead.work_mode ? ` · ${lead.work_mode}` : ''}</span>
            {lead.pay?.stated ? <span className="tag">{lead.pay.stated}</span> : null}
            {lead.posted_at ? <span className="tag">Posted {formatDate(lead.posted_at)}</span> : null}
            {isUrl(lead.source_url) ? <a className="tag link" href={lead.source_url} target="_blank" rel="noreferrer">{SOURCE_LABEL[lead.source] || lead.source}</a> : null}
            {lead.open === false ? <span className="tag warn-tag">Posting closed</span> : null}
          </p>
        </div>

        {isJob ? (
          <section className="section">
            <JobActions lead={{ id: lead.id, apply_url: isUrl(lead.apply_url) ? lead.apply_url : '', applied_at: lead.applied_at,
              outcome: lead.outcome, stage: lead.stage }} />
          </section>
        ) : null}

        <section className="section">
          <h2 className="section-label">People to message on LinkedIn<span className="n">{people.length}</span></h2>
          {people.length === 0 ? (
            <p className="empty">Not looked up yet. The hiring manager, the team lead and the recruiter are found on LinkedIn for each job.</p>
          ) : (
            <div className="card">
              {people.map((person) => (
                <div key={person.id} className="person">
                  <div>
                    <h4>{person.name} <span style={{ fontWeight: 400, color: 'var(--muted)' }}>· {ROLE[person.role_type] || 'Works there'}</span></h4>
                    {person.title ? <p>{person.title}</p> : null}
                  </div>
                  <div className="right">
                    <a className="button small primary" href={person.linkedin_url} target="_blank" rel="noreferrer">Open LinkedIn</a>
                  </div>
                </div>
              ))}
            </div>
          )}
          {lead.inmail?.body ? <div style={{ marginTop: 14 }}><InMailNote subject={lead.inmail.subject} body={lead.inmail.body} /></div> : null}
        </section>

        {messages.length > 0 ? (
          <section className="section">
            <h2 id="emails" className="section-label">Emails<span className="n">{messages.length}</span></h2>
            {messages.map((message) => (
              <MessageCard key={`${message.id}-${message.status}`} message={message} mode={mode}
                emailBadge={EMAIL_BADGE[contactById[message.contact_id]?.email_status || message.email_status]} />
            ))}
          </section>
        ) : null}

        {lead.research?.fit_notes ? (
          <section className="section">
            <h2 className="section-label">Why it fits</h2>
            <p className="prose">{lead.research.fit_notes}</p>
            {lead.research?.pay_notes ? <p className="prose"><strong>Pay:</strong> {lead.research.pay_notes}</p> : null}
          </section>
        ) : null}

        {lead.jd ? (
          <section className="section">
            <h2 className="section-label">Job description</h2>
            <p className="prose" style={{ whiteSpace: 'pre-wrap' }}>{lead.jd}</p>
          </section>
        ) : null}
      </main>
    </>
  );
}
