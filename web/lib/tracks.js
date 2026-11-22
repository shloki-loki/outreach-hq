// The two tracks of the search. Every page that separates or counts them uses these functions.
// Agent Leads: everything the agent found (job boards, hiring posts, YC), and the outreach about those leads.
// Cold Emails: the founder list Shlok supplied. Split by where a lead came from, so no lead is in both.

const COLD_SOURCES = new Set(['founder_reoutreach']);
const DELIVERED = ['sent', 'replied', 'bounced'];

export const TRACKS = {
  jobs: { label: 'Agent Leads', href: '/', about: 'Leads the agent found, with their applications and outreach.' },
  cold: { label: 'Cold Emails', href: '/cold-mails', about: 'Emails to the founder list.' },
};

export const trackOf = (lead) => (COLD_SOURCES.has(lead.source) ? 'cold' : 'jobs');
export const inTrack = (leads, track) => leads.filter((lead) => trackOf(lead) === track);
export const pct = (part, whole) => (whole ? `${((part / whole) * 100).toFixed(1).replace(/\.0$/, '')}%` : 'n/a');

// People who replied. The lead's status can't be used: it turns into Interview or Offer later.
export function replyCount(lead) {
  const people = new Set(lead.messages.filter((m) => m.status === 'replied').map((m) => m.contact_id)).size;
  return people || (lead.replied_at ? 1 : 0);
}

// An interview still counts after an offer or a no. Only "Clear outcome" takes it back.
export function hadInterview(lead) {
  if (['interview', 'offer'].includes(lead.outcome)) return true;
  let reached = false;
  for (const event of lead.timeline || []) {
    if (event.event !== 'outcome') continue;
    if (['interview', 'offer'].includes(event.detail)) reached = true;
    if (event.detail === 'none') reached = false;
  }
  return reached;
}

export function trackStats(leads) {
  const messages = leads.flatMap((lead) => lead.messages);
  const delivered = messages.filter((m) => DELIVERED.includes(m.status));
  const firstEmails = delivered.filter((m) => m.kind === 'cold').length;
  const bounced = delivered.filter((m) => m.status === 'bounced').length;
  const replies = leads.reduce((sum, lead) => sum + replyCount(lead), 0);
  return {
    sent: delivered.length,
    firstEmails,
    followupsSent: delivered.length - firstEmails,
    replies,
    replyRate: pct(replies, firstEmails),
    bounced,
    bounceRate: pct(bounced, delivered.length),
    bounceHigh: bounced / Math.max(1, delivered.length) > 0.05,
    interviews: leads.filter(hadInterview).length,
    offers: leads.filter((lead) => lead.outcome === 'offer').length,
    drafts: messages.filter((m) => m.status === 'draft').length,
    queued: messages.filter((m) => ['approved', 'sending'].includes(m.status)).length,
    followupsDue: leads.filter((lead) => lead.followup?.due).length,
  };
}

// The job statuses read wrongly for cold email: a queued template would show as "Needs your approval".
export function coldState(lead) {
  const has = (...statuses) => lead.messages.some((m) => statuses.includes(m.status));
  const state = (status, label, tone, rank) => ({ status, label, tone, rank });
  if (lead.outcome === 'offer') return state('offer', 'Offer', 'win', 0);
  if (lead.outcome === 'interview') return state('interview', 'Interview', 'win', 1);
  if (['rejected', 'skipped', 'closed'].includes(lead.status)) return state(lead.status, 'Not in play', 'off', 11);
  if (replyCount(lead)) return state('replied', 'Replied', 'reply', 2);
  if (lead.followup?.due) return state('followup_due', 'Follow-up due', 'due', 3);
  if (has('draft')) return state('to_approve', 'Draft to approve', 'approve', 4);
  if (has('sent')) return state('contacted', has('approved', 'sending') ? 'Emailed, more queued' : 'Emailed', 'done', 5);
  if (has('approved', 'sending')) return state('qualified', 'Queued', 'ready', 6);
  if (has('failed')) return state('followup_due', 'Send failed', 'due', 7);
  if (has('bounced')) return state('closed', 'Bounced', 'off', 8);
  return state('new', 'Not emailed yet', 'new', 9);
}
