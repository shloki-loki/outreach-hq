'use server';

// Everything the site can change. Each action checks the session itself.
// The site never sends email: approving only marks a message "approved"; the sender workflow
// (outreach/send.py) does the sending, with its own caps and checks.

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { assertSignedIn, endSession, passwordIsSet, passwordMatches, startSession } from '@/lib/auth';
import { Abort, addTimeline, dispatchCycle, nowIso, update } from '@/lib/store';

const clean = (value, max) => String(value ?? '').replace(/\r\n/g, '\n').trim().slice(0, max);

function refresh(leadId) {
  revalidatePath('/');
  revalidatePath('/cold-mails');
  revalidatePath('/approvals');
  revalidatePath('/progress');
  if (leadId) revalidatePath(`/lead/${leadId}`);
}

async function guarded(work) {
  await assertSignedIn();
  try {
    return (await work()) || { ok: true };
  } catch (error) {
    if (error instanceof Abort) return { ok: false, error: error.message };
    console.error(error);
    return { ok: false, error: `Could not save: ${error.message}` };
  }
}

export async function login(_previous, formData) {
  if (!passwordIsSet()) return { error: 'SITE_PASSWORD is not set on Vercel yet.' };
  await new Promise((resolve) => setTimeout(resolve, 600)); // slows guessing
  if (!passwordMatches(formData.get('password') || '')) return { error: 'Wrong password.' };
  await startSession();
  redirect('/');
}

export async function logout() {
  await endSession();
  redirect('/login');
}

// ---- messages -----------------------------------------------------------------------------

function editMessage(message, subject, body) {
  const nextSubject = clean(subject, 200);
  const nextBody = clean(body, 6000);
  if (!nextSubject || nextBody.length < 40) throw new Abort('The subject or body is empty.');
  if (nextSubject !== message.subject || `${nextBody}\n` !== message.body) {
    message.subject = nextSubject;
    message.body = `${nextBody}\n`;
    message.edited_by_shlok = true;
  }
}

export async function saveMessage(id, subject, body) {
  return guarded(async () => {
    let leadId;
    await update('messages', (data) => {
      const message = data.messages.find((m) => m.id === id);
      if (!message) throw new Abort('That message no longer exists.');
      if (message.status !== 'draft') throw new Abort(`This message is already ${message.status}; it can no longer be edited.`);
      editMessage(message, subject, body);
      leadId = message.lead_id;
    }, `site: edit ${id}`);
    refresh(leadId);
  });
}

export async function approveMessage(id, subject, body) {
  return guarded(async () => {
    let leadId;
    await update('messages', (data) => {
      const message = data.messages.find((m) => m.id === id);
      if (!message) throw new Abort('That message no longer exists.');
      if (message.status !== 'draft') throw new Abort(`Already ${message.status}. Nothing was changed.`);
      editMessage(message, subject, body);
      message.status = 'approved';
      message.approved_at = nowIso();
      message.error = null;
      leadId = message.lead_id;
    }, `site: approve ${id}`);
    const started = await dispatchCycle(`approved ${id}`);
    refresh(leadId);
    return { ok: true, note: started.started ? 'Approved. The sender is starting now.' : `Approved. ${started.note || ''}` };
  });
}

export async function approveMany(ids) {
  return guarded(async () => {
    let count = 0;
    await update('messages', (data) => {
      count = 0;
      for (const id of ids) {
        const message = data.messages.find((m) => m.id === id);
        if (message && message.status === 'draft') {
          message.status = 'approved';
          message.approved_at = nowIso();
          message.error = null;
          count += 1;
        }
      }
      if (!count) throw new Abort('Nothing left to approve.');
    }, `site: approve ${ids.length} messages`);
    const started = await dispatchCycle(`approved ${count} messages`);
    refresh();
    return { ok: true, note: `${count} approved. ${started.started ? 'The sender is starting now.' : started.note || ''}` };
  });
}

export async function unapproveMessage(id) {
  return guarded(async () => {
    await update('messages', (data) => {
      const message = data.messages.find((m) => m.id === id);
      if (!message || message.status !== 'approved') throw new Abort('Too late: it is no longer waiting to send.');
      message.status = 'draft';
      message.approved_at = null;
    }, `site: pull back ${id}`);
    refresh();
  });
}

export async function skipMessage(id) {
  return guarded(async () => {
    let leadId;
    await update('messages', (data) => {
      const message = data.messages.find((m) => m.id === id);
      if (!message || !['draft', 'approved', 'failed'].includes(message.status)) throw new Abort('This message can no longer be skipped.');
      message.status = 'skipped';
      message.error = 'Skipped by Shlok.';
      leadId = message.lead_id;
    }, `site: skip ${id}`);
    refresh(leadId);
  });
}

export async function retryMessage(id) {
  return guarded(async () => {
    await update('messages', (data) => {
      const message = data.messages.find((m) => m.id === id);
      if (!message || message.status !== 'failed') throw new Abort('Only a failed message can be retried.');
      message.status = 'approved';
      message.approved_at = nowIso();
      message.error = null;
      message.message_id = null;
    }, `site: retry ${id}`);
    const started = await dispatchCycle(`retry ${id}`);
    refresh();
    return { ok: true, note: started.started ? 'Queued again. The sender is starting now.' : `Queued again. ${started.note || ''}` };
  });
}

// ---- leads --------------------------------------------------------------------------------

async function editLead(leadId, change, message) {
  return guarded(async () => {
    await update('leads', (data) => {
      const lead = data.leads.find((l) => l.id === leadId);
      if (!lead) throw new Abort('That lead no longer exists.');
      change(lead);
    }, message);
    refresh(leadId);
  });
}

export async function markApplied(leadId) {
  return editLead(leadId, (lead) => {
    lead.applied_at = lead.applied_at || nowIso();
    lead.apply = { ...(lead.apply || {}), status: 'applied' };
    addTimeline(lead, 'shlok', 'applied', 'application submitted');
  }, `site: applied ${leadId}`);
}

export async function undoApplied(leadId) {
  return editLead(leadId, (lead) => {
    lead.applied_at = null;
    lead.apply = { ...(lead.apply || {}), status: 'not_started' };
    addTimeline(lead, 'shlok', 'applied_undone', '');
  }, `site: un-applied ${leadId}`);
}

export async function setOutcome(leadId, outcome) {
  if (!['interview', 'offer', 'rejected', 'closed', 'none'].includes(outcome)) return { ok: false, error: 'Unknown outcome.' };
  return editLead(leadId, (lead) => {
    lead.outcome = outcome === 'none' ? null : outcome;
    lead.outcome_at = lead.outcome ? nowIso() : null;
    if (lead.outcome) lead.followup = { due: false, kind: null, since: null };
    addTimeline(lead, 'shlok', 'outcome', outcome);
  }, `site: outcome ${leadId} ${outcome}`);
}

// "I followed up" on an applied job that went quiet: restarts the 4-day check-in clock (2026-11-24).
export async function checkIn(leadId) {
  return editLead(leadId, (lead) => {
    lead.checked_in_at = nowIso();
    addTimeline(lead, 'shlok', 'checked_in', 'followed up on LinkedIn or by email');
  }, `site: checked in ${leadId}`);
}

// A job he applied to on his own, added so he remembers it (2026-11-24). Saved as applied today.
export async function addManualJob(company, note, role, link) {
  const name = clean(company, 120);
  const text = clean(note, 2000);
  const title = clean(role, 160);
  const url = clean(link, 500);
  if (!name) return { ok: false, error: 'The company name is needed.' };
  if (!text) return { ok: false, error: 'Add a short note so you remember it.' };
  if (url && !/^https?:\/\/\S+$/.test(url)) return { ok: false, error: 'The link should start with http:// or https://.' };
  let id = null;
  const result = await guarded(async () => {
    await update('leads', (data) => {
      const isBoard = 'generated_from' in data;
      if (!isBoard) {
        const highest = Math.max(0, ...data.leads.map((l) => Number(String(l.id).slice(1)) || 0));
        id = `L${String(highest + 1).padStart(4, '0')}`;
      } else if (!id || data.leads.some((l) => l.id === id)) return;
      const at = nowIso();
      const lead = {
        id, legacy_id: null, key: `manual|${name.toLowerCase()}|${title.toLowerCase()}|${at}`, type: 'job',
        company: name, company_domain: '', company_url: '', company_linkedin: '', company_note: '',
        title: title || 'Role not noted', tier: null, location: '', location_bucket: '', work_mode: '',
        source: 'manual', source_id: id, source_url: url, apply_url: url,
        sources: [{ source: 'manual', url, seen: at.slice(0, 10) }], posted_at: null,
        first_seen: at.slice(0, 10), last_seen: at.slice(0, 10), open: true, jd: '',
        exp_min: null, exp_max: null, exp_text: '', stretch: false, pay: {},
        score: { rules: 0, research: null, total: 0, reasons: ['added by Shlok'] },
        research: { done: false, fit_notes: '', pay_notes: '', culture_notes: '', hook: '', hook_source: '', researched_at: null },
        stage: 'qualified', outcome: null, applied_at: at, apply: { status: 'applied', notes: '', answers: {} },
        first_contacted_at: null, replied_at: null, contacts: [], referrals: [],
        followup: { due: false, kind: null, since: null }, notes: [{ at, by: 'shlok', text }],
        timeline: [], created_at: at, updated_at: at,
      };
      addTimeline(lead, 'shlok', 'applied', 'added by hand as applied');
      data.leads.push(lead);
    }, `site: manual job ${name}`);
    refresh();
  });
  return result.ok === false ? result : { ok: true, id };
}

export async function setStage(leadId, stage) {
  if (!['qualified', 'skipped'].includes(stage)) return { ok: false, error: 'Unknown stage.' };
  return editLead(leadId, (lead) => {
    lead.stage = stage;
    addTimeline(lead, 'shlok', 'stage', stage === 'skipped' ? 'not interested' : 'moved back to qualified');
  }, `site: stage ${leadId} ${stage}`);
}

export async function addNote(leadId, text) {
  const note = clean(text, 2000);
  if (!note) return { ok: false, error: 'The note is empty.' };
  return editLead(leadId, (lead) => {
    lead.notes = lead.notes || [];
    lead.notes.push({ at: nowIso(), by: 'shlok', text: note });
    lead.updated_at = nowIso();
  }, `site: note ${leadId}`);
}

export async function addReferral(leadId, name, position, linkedinUrl) {
  const person = clean(name, 120);
  const url = clean(linkedinUrl, 300);
  if (!person) return { ok: false, error: 'A name is needed.' };
  if (url && !/^https:\/\/([a-z]+\.)?linkedin\.com\/in\//i.test(url)) return { ok: false, error: 'That is not a LinkedIn profile link (it should start with https://www.linkedin.com/in/).' };
  return editLead(leadId, (lead) => {
    lead.referrals = lead.referrals || [];
    if (lead.referrals.some((r) => (url && r.linkedin_url === url) || r.name.toLowerCase() === person.toLowerCase())) throw new Abort('They are already listed on this lead.');
    lead.referrals.push({ name: person, position: clean(position, 160), linkedin_url: url, connected_on: '', status: 'suggested', note: '', sent_at: null, added_by: 'shlok' });
    addTimeline(lead, 'shlok', 'referral_added', `${person} added from a live LinkedIn search`);
  }, `site: add connection ${leadId}`);
}

export async function saveReferral(leadId, linkedinUrl, note, status) {
  if (!['suggested', 'sent', 'replied', 'skipped'].includes(status)) return { ok: false, error: 'Unknown status.' };
  return editLead(leadId, (lead) => {
    const referral = (lead.referrals || []).find((r) => (r.linkedin_url || r.name) === linkedinUrl);
    if (!referral) throw new Abort('That connection is no longer listed on this lead.');
    referral.note = clean(note, 1500);
    if (referral.status !== status) {
      referral.status = status;
      if (status === 'sent') {
        referral.sent_at = nowIso();
        lead.first_contacted_at = lead.first_contacted_at || nowIso();
        addTimeline(lead, 'shlok', 'referral_sent', `asked ${referral.name} on LinkedIn`);
      } else if (status === 'replied') {
        addTimeline(lead, 'shlok', 'referral_replied', `${referral.name} replied`);
      }
    }
  }, `site: referral ${leadId}`);
}
