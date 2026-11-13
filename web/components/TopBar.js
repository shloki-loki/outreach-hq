import Link from 'next/link';
import { logout } from '@/app/actions';
import { sendingMode } from '@/lib/store';

const TABS = [
  { href: '/', label: 'Leads' },
  { href: '/approvals', label: 'Approvals' },
  { href: '/progress', label: 'Progress' },
  { href: '/log', label: 'Log' },
];

export default async function TopBar({ current, toApprove = 0 }) {
  const mode = await sendingMode();
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link href="/" className="brand">Outreach HQ</Link>
        <span className={`mode ${mode === 'live' ? '' : 'dry'}`} title={mode === 'live'
          ? 'Approved emails are sent.' : 'Dry run: approved emails are held, nothing is sent.'}>
          <span />{mode === 'live' ? 'Sending is live' : mode === 'dry_run' ? 'Dry run, nothing is sent' : 'Mode unknown'}
        </span>
        <nav className="tabs" aria-label="Sections">
          {TABS.map((tab) => (
            <Link key={tab.href} href={tab.href} className="tab" aria-current={current === tab.href ? 'page' : undefined}>
              {tab.label}
              {tab.href === '/approvals' && toApprove > 0 ? <span className="count">{toApprove}</span> : null}
            </Link>
          ))}
        </nav>
        <form action={logout}><button className="signout" type="submit">Sign out</button></form>
      </div>
    </header>
  );
}
