import Link from 'next/link';
import { TRACKS } from '@/lib/tracks';

// The same six results for each track, so the two can be compared like for like.
export default function TrackKpis({ track, stats }) {
  const base = TRACKS[track].href;
  const items = [
    { value: stats.sent, label: `Emails sent (${stats.followupsSent} follow-up${stats.followupsSent === 1 ? '' : 's'})`, view: track === 'cold' ? 'sent' : 'emailed' },
    { value: stats.replies, label: 'People who replied', view: 'replies', tone: 't-reply' },
    { value: stats.replyRate, label: `Reply rate (of ${stats.firstEmails} first emails)`, view: 'replies', tone: 't-reply' },
    { value: stats.bounceRate, label: `Bounce rate (${stats.bounced}; keep under 5%)`, view: 'bounced', tone: stats.bounceHigh ? 't-due' : '' },
    { value: stats.interviews, label: 'Interviews', view: 'interviews', tone: 'hot' },
    { value: stats.offers, label: 'Offers', view: 'offers', tone: 'hot' },
  ];
  return (
    <dl className="highlights six" aria-label={`${TRACKS[track].label} results`}>
      {items.map((item) => (
        <Link key={item.label} href={`${base}?view=${item.view}`} className={`highlight ${item.tone || ''}`}>
          <dd>{item.value}</dd><dt>{item.label}</dt>
        </Link>
      ))}
    </dl>
  );
}
