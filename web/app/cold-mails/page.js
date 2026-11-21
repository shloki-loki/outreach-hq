import LeadList from '@/components/LeadList';
import TopBar from '@/components/TopBar';
import { requireSignIn } from '@/lib/auth';
import { loadBoard } from '@/lib/data';
import { STATUS } from '@/lib/status';

export const dynamic = 'force-dynamic';

export default async function ColdMailsPage() {
  await requireSignIn();
  const { leads, messages } = await loadBoard();
  const rows = leads.filter((lead) => lead.type === 'company').map((lead) => ({
    id: lead.id,
    company: lead.company,
    search: lead.company.toLowerCase(),
    status: lead.status,
    statusLabel: STATUS[lead.status].label,
    tone: STATUS[lead.status].tone,
    messageStatuses: lead.messages.map((message) => message.status),
    followupDue: Boolean(lead.followup?.due),
  }));

  return (
    <>
      <TopBar current="/cold-mails" toApprove={messages.filter((message) => message.status === 'draft').length} />
      <main>
        <div className="page-head">
          <h1>Cold Mails</h1>
          <p>Outreach to companies without a named opening. Open a company to review its emails and contacts.</p>
        </div>
        <LeadList rows={rows} initialView="all" coldMails />
      </main>
    </>
  );
}
