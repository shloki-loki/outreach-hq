import { read } from '@/lib/store';
import { STATUS, displayStatus } from '@/lib/status';

// Leads with their messages and display status attached. Reads board.json, the small copy of leads.json the
// pipeline writes for the site; falls back to leads.json until the first board exists.
export async function loadBoard() {
  const [boardFile, messageFile] = await Promise.all([read('board'), read('messages')]);
  const leadFile = boardFile?.leads ? boardFile : await read('leads');
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
