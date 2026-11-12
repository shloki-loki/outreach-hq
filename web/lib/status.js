// One status per lead, for colour coding. Mirrors display_status() in outreach/leads.py: keep both in step.

export function displayStatus(lead, messages) {
  if (lead.stage === 'skipped') return 'skipped';
  if (['offer', 'interview', 'rejected', 'closed'].includes(lead.outcome)) return lead.outcome;
  if (lead.stage === 'rejected') return 'rejected';
  if (lead.replied_at || messages.some((m) => m.status === 'replied')) return 'replied';
  if (lead.followup?.due) return 'followup_due';
  if (messages.some((m) => ['draft', 'approved', 'sending', 'failed'].includes(m.status))) return 'to_approve';
  const sent = messages.some((m) => m.status === 'sent') || (lead.referrals || []).some((r) => r.status === 'sent');
  if (sent || lead.first_contacted_at) return 'contacted';
  if (lead.applied_at) return 'applied';
  return lead.stage === 'qualified' ? 'qualified' : 'new';
}

// tone -> CSS class .tone-<tone>
export const STATUS = {
  offer: { label: 'Offer', tone: 'win', rank: 0 },
  interview: { label: 'Interview', tone: 'win', rank: 1 },
  replied: { label: 'Replied', tone: 'reply', rank: 2 },
  followup_due: { label: 'Follow-up due', tone: 'due', rank: 3 },
  to_approve: { label: 'Needs your approval', tone: 'approve', rank: 4 },
  qualified: { label: 'Qualified', tone: 'ready', rank: 5 },
  contacted: { label: 'Contacted', tone: 'done', rank: 6 },
  applied: { label: 'Applied', tone: 'done', rank: 7 },
  new: { label: 'New, not researched', tone: 'new', rank: 8 },
  rejected: { label: 'Rejected', tone: 'off', rank: 9 },
  closed: { label: 'Closed', tone: 'off', rank: 10 },
  skipped: { label: 'Skipped', tone: 'off', rank: 11 },
};

export const NEEDS_YOU = ['replied', 'followup_due', 'to_approve', 'qualified'];
export const IN_PLAY = ['offer', 'interview', 'replied', 'followup_due', 'to_approve', 'qualified', 'contacted', 'applied'];

export const EMAIL_BADGE = {
  published: { label: 'Published address', tone: 'done' },
  verified: { label: 'Verified', tone: 'done' },
  hunter: { label: 'Likely', tone: 'ready' },
  pattern: { label: 'Company pattern', tone: 'ready' },
  'catch-all': { label: 'Unverifiable', tone: 'due' },
  guess: { label: 'Guess', tone: 'due' },
  bounced: { label: 'Bounced', tone: 'off' },
  invalid: { label: 'Invalid', tone: 'off' },
  none: { label: 'No address', tone: 'new' },
};

export const SOURCE_LABEL = {
  greenhouse: 'Company careers page', lever: 'Company careers page', ashby: 'Company careers page',
  linkedin: 'LinkedIn Jobs', linkedin_post: 'LinkedIn hiring post', instahyre: 'Instahyre', yc: 'Y Combinator',
  naukri: 'Naukri', wellfound: 'Wellfound', hiringcafe: 'Hiring Cafe', iimjobs: 'IIMJobs', web: 'Web search',
};

export function formatDate(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso).slice(0, 10);
  return date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' });
}

export function formatDateTime(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return date.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' });
}

export function daysAgo(iso) {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  return Math.max(0, Math.floor((Date.now() - then) / 86400000));
}
