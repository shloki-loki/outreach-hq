import Link from 'next/link';
import ApplicationPacket from '@/components/ApplicationPacket';
import { notFound } from 'next/navigation';
import LeadControls from '@/components/LeadControls';
import LinkedInNotes from '@/components/LinkedInNotes';
import MessageCard from '@/components/MessageCard';
import AddConnection from '@/components/AddConnection';
import ReferralCard from '@/components/ReferralCard';
import TopBar from '@/components/TopBar';
import { requireSignIn } from '@/lib/auth';
import { loadBoard } from '@/lib/data';
import { sendingMode } from '@/lib/store';
import { EMAIL_BADGE, SOURCE_LABEL, STATUS, formatDate, formatDateTime } from '@/lib/status';
import { TRACKS, trackOf } from '@/lib/tracks';

export const dynamic = 'force-dynamic';

const ROLE = { recruiter: 'Recruiter', hiring_manager: 'Hiring manager', founder: 'Founder', employee: 'Works there', generic: 'Company address' };
const EVENT = {
  found: 'Found', imported: 'Imported', researched: 'Researched', contact_added: 'Person added', email_found: 'Email found',
  drafted: 'Email drafted', sent: 'Email sent', send_failed: 'Send failed', replied: 'Reply received', auto_reply: 'Auto-reply',
  bounced: 'Bounced', followup_due: 'Follow-up due', applied: 'Applied', applied_undone: 'Applied undone', outcome: 'Outcome',
  stage: 'Stage', referral_added: 'Connection added', referral_note: 'Referral note drafted', referral_sent: 'Referral asked', referral_replied: 'Referral replied',
  posting_closed: 'Posting closed', reopened: 'Posting reopened', people: 'People found', linkedin_draft: 'LinkedIn note drafted', apply_kit: 'Application answers ready', apply: 'Application',
};
const isUrl = (value) => /^https?:\/\//.test(value || '');

export default async function LeadPage({ params }) {
  await requireSignIn();
  const { id } = await params;
  const [{ leads }, mode] = await Promise.all([loadBoard(), sendingMode()]);
  const lead = leads.find((item) => item.id === id);
  if (!lead) notFound();
  const toApprove = leads.reduce((sum, item) => sum + item.messages.filter((m) => m.status === 'draft').length, 0);
  const status = STATUS[lead.status];
  const track = TRACKS[trackOf(lead)];
  const messages = [...lead.messages].sort((a, b) => (a.created_at < b.created_at ? -1 : 1));
  const referrals = lead.referrals || [];
  const companyName = (lead.company || '').replace(/\(.*?\)/g, '').trim();
  const answers = Object.entries(lead.apply?.answers || {});
  const contactById = Object.fromEntries((lead.contacts || []).map((c) => [c.id, c]));
  const controls = { id: lead.id, apply_url: isUrl(lead.apply_url) ? lead.apply_url : '', applied_at: lead.applied_at, outcome: lead.outcome, stage: lead.stage };

  return (
    <>
      <TopBar current={track.href} toApprove={toApprove} />
      <main>
        <Link href={track.href} className="back">← {track.label}</Link>
        <div className="page-head" style={{ paddingTop: 18 }}>
          <div className="button-row" style={{ marginBottom: 12 }}>
            <span className={`pill tone-${status.tone}`}>{status.label}</span>
            {lead.stretch ? <span className="tag">Stretch on seniority</span> : null}
            {lead.open === false ? <span className="tag">{lead.bin ? 'In the Bin: posting closed' : 'Posting closed'}</span> : null}
            {lead.research?.by === 'research-worker' ? <span className="tag" title="Researched on GitHub by the free model; every claim passed code checks, and Claude reviews a sample">Researched by the free model{lead.research.review === 'pending' ? ' · not yet reviewed' : ''}</span> : null}
            {lead.type === 'company' ? <span className="tag">No named opening: speculative note to the founders</span> : null}
            {lead.legacy_id ? <span className="tag">Old tracker {lead.legacy_id}</span> : null}
          </div>
          <h1>{lead.title}</h1>
          <p><strong>{lead.company}</strong>{lead.company_note ? ` · ${lead.company_note}` : ''}</p>
          {lead.research?.headline ? <p style={{ color: 'var(--ink)', fontSize: 16 }}>{lead.research.headline}</p> : null}
          <p style={{ fontSize: 13 }}>
            {lead.research?.done ? (lead.research.researched_at ? `Posting and company checked ${formatDate(lead.research.researched_at)}.` : 'Researched in the earlier tracker and not re-checked since: the posting may have closed.') : 'Not researched yet: nothing here has been checked beyond the rules.'}
            {lead.open === false ? (lead.bin ? ` Moved to the Bin ${formatDate(lead.bin.at)}: ${lead.bin.reason}.` : ' The posting has since closed.') : ''}
          </p>
        </div>

        <ApplicationPacket lead={lead} />

        <dl className="facts">
          <div><dt>Fit score</dt><dd>{lead.score?.total ?? 0} / 100</dd></div>
          <div><dt>Location</dt><dd>{lead.location || 'Not stated'}{lead.work_mode ? ` · ${lead.work_mode}` : ''}</dd></div>
          <div><dt>Pay</dt><dd>{lead.pay?.fit || 'Unknown'}{lead.pay?.stated ? ` · ${lead.pay.stated}` : ''}</dd></div>
          <div><dt>Experience asked</dt><dd>{lead.exp_min != null ? `${lead.exp_min}${lead.exp_max ? `-${lead.exp_max}` : '+'} years` : (lead.exp_text || 'Not stated')}</dd></div>
          <div><dt>Role type</dt><dd>{lead.tier || 'Other'}</dd></div>
          <div><dt>Found on</dt><dd>{isUrl(lead.source_url) ? <a className="link" href={lead.source_url} target="_blank" rel="noreferrer">{SOURCE_LABEL[lead.source] || lead.source}</a> : (SOURCE_LABEL[lead.source] || lead.source)}</dd></div>
          <div><dt>Posted</dt><dd>{formatDate(lead.posted_at) || 'Unknown'}</dd></div>
          <div><dt>First seen</dt><dd>{formatDate(lead.first_seen)}</dd></div>
        </dl>

        <section className="section">
          <h2 className="section-label">What to do</h2>
          <LeadControls lead={controls} />
        </section>

        <section className="section">
          <h2 id="emails" className="section-label">Emails<span className="n">{messages.length}</span></h2>
          {messages.length === 0 ? (
            <p className="empty">No email drafted yet. {lead.stage === 'qualified' ? 'The send agent drafts one once a person and an address are found.' : 'This lead has not been qualified.'}</p>
          ) : messages.map((message) => (
            <MessageCard key={`${message.id}-${message.status}`} message={message} mode={mode}
              emailBadge={EMAIL_BADGE[contactById[message.contact_id]?.email_status || message.email_status]} />
          ))}
        </section>

        <section className="section">
          <h2 className="section-label">LinkedIn notes to send yourself<span className="n">{(lead.linkedin_drafts || []).length}</span></h2>
          {(lead.linkedin_drafts || []).length === 0 ? (
            <p className="empty">{lead.stage === 'qualified' ? 'None yet. People at the company are looked up on LinkedIn and a note and a message are drafted for each.' : 'Drafted once the lead is qualified.'}</p>
          ) : (
            <>
              <p className="prose">Drafted for you to copy. Nothing is sent on LinkedIn by this system. Free accounts get a few personalised notes a month, so the message is drafted too.</p>
              <LinkedInNotes drafts={lead.linkedin_drafts} />
            </>
          )}
        </section>

        <section className="section">
          <h2 className="section-label">My LinkedIn connections here<span className="n">{referrals.length}</span></h2>
          <p className="prose">The list below comes from your last LinkedIn export, so it misses anyone you connected with since. The live search is always current: it opens LinkedIn's own search of your connections for this company.</p>
          <div className="button-row" style={{ marginBottom: 14 }}>
            <a className="button primary" target="_blank" rel="noreferrer" href={`https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(companyName)}&network=%5B%22F%22%5D&origin=FACETED_SEARCH`}>Search my connections at {companyName} (live)</a>
            <a className="button" target="_blank" rel="noreferrer" href={`https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(companyName)}&network=%5B%22S%22%5D&origin=FACETED_SEARCH`}>Friends of friends there</a>
          </div>
          {referrals.length === 0 ? (
            <p className="empty">Nobody from your last export lists {companyName} as their company.</p>
          ) : referrals.map((referral) => <ReferralCard key={referral.linkedin_url || referral.name} leadId={lead.id} referral={referral} />)}
          <AddConnection leadId={lead.id} />
        </section>

        <section className="section">
          <h2 className="section-label">People<span className="n">{(lead.contacts || []).length}</span></h2>
          {(lead.contacts || []).length === 0 ? <p className="empty">Nobody found yet.</p> : (
            <div className="card">
              {lead.contacts.map((contact) => {
                const badge = EMAIL_BADGE[contact.email ? contact.email_status : 'none'] || EMAIL_BADGE.none;
                return (
                  <div key={contact.id} className="person">
                    <div>
                      <h4>{contact.name || 'Company address'} <span style={{ fontWeight: 400, color: 'var(--muted)' }}>· {ROLE[contact.role_type] || contact.role_type}</span></h4>
                      <p>{[contact.title, contact.why].filter(Boolean).join(' · ')}</p>
                      {contact.email ? <p>{contact.email}{contact.email_source ? ` · ${contact.email_source}` : ''}</p> : null}
                    </div>
                    <div className="right">
                      <span className={`pill tone-${badge.tone}`}>{badge.label}</span>
                      {isUrl(contact.linkedin_url) ? <a className="button small" href={contact.linkedin_url} target="_blank" rel="noreferrer">LinkedIn</a> : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="section">
          <h2 className="section-label">Why it fits</h2>
          {lead.research?.fit_notes ? <p className="prose">{lead.research.fit_notes}</p> : <p className="prose">Not researched yet. Rule-based score only.</p>}
          {lead.research?.pay_notes || lead.pay?.source ? <p className="prose"><strong>Pay evidence:</strong> {lead.research?.pay_notes || lead.pay.source}</p> : null}
          {lead.research?.culture_notes ? <p className="prose"><strong>Company:</strong> {lead.research.culture_notes}</p> : null}
          {(lead.research?.sources || []).length ? (
            <p className="prose"><strong>Sources:</strong> {lead.research.sources.map((source, index) => (
              <span key={source.url}>{index ? ' · ' : ''}<a className="link" href={source.url} target="_blank" rel="noreferrer">{source.title || source.id}</a></span>
            ))}</p>
          ) : null}
          {lead.reject_reason ? <p className="prose"><strong>Dropped because:</strong> {lead.reject_reason}</p> : null}
          <ul className="reasons">{(lead.score?.reasons || []).map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </section>

        {answers.length > 0 || lead.apply?.notes ? (
          <section className="section">
            <h2 className="section-label">Application answers, ready to paste</h2>
            {lead.apply?.notes ? <p className="prose">{lead.apply.notes}</p> : null}
            <dl className="answers">{answers.map(([question, answer]) => <div key={question}><dt>{question}</dt><dd>{String(answer)}</dd></div>)}</dl>
          </section>
        ) : null}

        {(lead.notes || []).length > 0 ? (
          <section className="section">
            <h2 className="section-label">Notes</h2>
            <ul className="list">{[...lead.notes].reverse().map((note, index) => (
              <li key={index}><span className="when">{formatDateTime(note.at)} · {note.by}</span><span style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{note.text}</span></li>
            ))}</ul>
          </section>
        ) : null}

        {lead.jd ? (
          <section className="section">
            <h2 className="section-label">Job description</h2>
            <p className="prose">{lead.jd}</p>
          </section>
        ) : null}

        <section className="section">
          <h2 className="section-label">History</h2>
          <ul className="list">{[...(lead.timeline || [])].reverse().map((entry, index) => (
            <li key={index}><span className="when">{formatDateTime(entry.at)}</span><span><strong>{EVENT[entry.event] || entry.event}</strong>{entry.detail ? ` · ${entry.detail}` : ''} <span style={{ color: 'var(--faint)' }}>({entry.actor})</span></span></li>
          ))}</ul>
        </section>
      </main>
    </>
  );
}
