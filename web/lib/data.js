import { read } from '@/lib/store';
import { STATUS, displayStatus } from '@/lib/status';

// Leads with their messages and display status attached.
export async function loadBoard() {
  const [leadFile, messageFile] = await Promise.all([read('leads'), read('messages')]);
  const byLead = new Map();
  for (const message of messageFile.messages || []) {
    if (!byLead.has(message.lead_id)) byLead.set(message.lead_id, []);
    byLead.get(message.lead_id).push(message);
  }
  const leads = (leadFile.leads || []).map((lead) => {
    const messages = byLead.get(lead.id) || [];
    return { ...lead, messages, status: displayStatus(lead, messages) };
  });
  leads.sort((a, b) => STATUS[a.status].rank - STATUS[b.status].rank || (b.score?.total || 0) - (a.score?.total || 0));
  return { leads, messages: messageFile.messages || [] };
}

export function counts(leads) {
  const tally = {};
  for (const lead of leads) tally[lead.status] = (tally[lead.status] || 0) + 1;
  return tally;
}
