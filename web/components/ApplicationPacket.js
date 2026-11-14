'use client';
import { useState } from 'react';

export default function ApplicationPacket({ lead }) {
  const [copied, setCopied] = useState('');
  const answers = Object.entries(lead.apply?.answers || {});
  const draft = [...lead.messages].reverse().find(m => m.status === 'draft');
  const research = lead.research || {};
  const missing = [];
  if (!research.done) missing.push('Research needs completing');
  if (!research.hook || !research.hook_source) missing.push('A sourced company-specific observation is missing');
  if (!draft) missing.push('No email draft awaiting review');
  if (lead.apply_url && !answers.length) missing.push('Application answers need preparing');
  if (lead.open === false) missing.push('Posting is closed');
  async function copy(label, value) {
    try { await navigator.clipboard.writeText(value); setCopied(`${label} copied`); }
    catch { setCopied('Could not copy. Select the text below and copy it manually.'); }
  }
  return <section className="section" aria-label="Application packet">
    <h2 className="section-label">Your application packet</h2>
    <p className="prose">Review the company observation, your email and the answers here before applying.</p>
    {missing.length ? <ul className="reasons">{missing.map(x => <li key={x}>{x}</li>)}</ul> : <p className="prose">Materials assembled. Check the facts and wording before approving or submitting.</p>}
    {research.hook && <div className="card" style={{padding: 20, marginBottom: 16}}>
      <h3>Why this company, now</h3><p className="prose">{research.hook}</p>
      {/^https?:\/\//.test(research.hook_source || '') && <a className="link" href={research.hook_source} target="_blank" rel="noreferrer">Check the source</a>}
    </div>}
    {draft && <div className="card" style={{padding: 20, marginBottom: 16}}>
      <h3>{draft.subject}</h3><p className="prose" style={{whiteSpace:'pre-wrap'}}>{draft.body}</p>
      <button className="button" onClick={() => copy('Email', draft.body)}>Copy email</button>
      <a className="button" href="#emails">Edit and approve email</a>
    </div>}
    {answers.map(([question, answer]) => <div className="card" style={{padding:20, marginBottom:12}} key={question}>
      <h3>{question}</h3><p className="prose" style={{whiteSpace:'pre-wrap'}}>{String(answer)}</p>
      <button className="button" onClick={() => copy('Answer', String(answer))}>Copy answer</button>
      <span style={{marginLeft:12}}>{String(answer).trim().split(/\s+/).filter(Boolean).length} words</span>
    </div>)}
    <p role="status" aria-live="polite">{copied}</p>
  </section>;
}
