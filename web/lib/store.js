// The site's view of the data store: the JSON files on the repo's `data` branch.
// Production reads and writes them through the GitHub API (token in Vercel env).
// Local preview (DATA_DIR set) reads and writes the files on disk instead.
// Every write is read-modify-write guarded by the file's sha, retried on conflict, so the site,
// the GitHub workflows and the agents on the Mac never overwrite each other.

import { promises as fs } from 'fs';
import path from 'path';

const API = 'https://api.github.com';
const DEFAULTS = {
  leads: { leads: [] }, messages: { messages: [] }, issues: { issues: [] }, runs: { runs: [] },
  metrics: { days: {} }, connections: { imported_at: null, connections: [] },
};

function localDir() {
  return process.env.DATA_DIR ? path.resolve(/* turbopackIgnore: true */ process.cwd(), process.env.DATA_DIR) : null;
}

function repo() {
  const { GITHUB_TOKEN, GITHUB_REPO } = process.env;
  if (!GITHUB_TOKEN || !GITHUB_REPO) throw new Error('GITHUB_TOKEN and GITHUB_REPO are not set on Vercel (see SETUP.md).');
  return { token: GITHUB_TOKEN, name: GITHUB_REPO, branch: process.env.DATA_BRANCH || 'data' };
}

async function gh(url, options = {}) {
  const { token } = repo();
  const response = await fetch(`${API}${url}`, {
    ...options,
    cache: 'no-store',
    headers: {
      Authorization: `Bearer ${token}`,
      'X-GitHub-Api-Version': '2022-11-28',
      Accept: 'application/vnd.github+json',
      ...(options.headers || {}),
    },
  });
  return response;
}

async function readRemote(name) {
  const { name: repoName, branch } = repo();
  const response = await gh(`/repos/${repoName}/contents/${name}.json?ref=${branch}`);
  if (response.status === 404) return { value: structuredClone(DEFAULTS[name] ?? {}), sha: null };
  if (!response.ok) throw new Error(`GitHub read of ${name}.json failed: ${response.status} ${await response.text()}`);
  const meta = await response.json();
  let text;
  if (meta.content && meta.encoding === 'base64') {
    text = Buffer.from(meta.content, 'base64').toString('utf8');
  } else {
    // Files over 1 MB come back without content; fetch the blob itself.
    const blob = await gh(`/repos/${repoName}/git/blobs/${meta.sha}`, { headers: { Accept: 'application/vnd.github.raw+json' } });
    if (!blob.ok) throw new Error(`GitHub blob read of ${name}.json failed: ${blob.status}`);
    text = await blob.text();
  }
  return { value: JSON.parse(text), sha: meta.sha };
}

export async function read(name) {
  const dir = localDir();
  if (dir) {
    try {
      return JSON.parse(await fs.readFile(path.join(dir, `${name}.json`), 'utf8'));
    } catch (error) {
      if (error.code === 'ENOENT') return structuredClone(DEFAULTS[name] ?? {});
      throw error;
    }
  }
  return (await readRemote(name)).value;
}

export class Abort extends Error {}

// `change(value)` edits the parsed file in place. Throw `new Abort(reason)` to stop without writing.
export async function update(name, change, message) {
  const dir = localDir();
  if (dir) {
    const value = await read(name);
    const result = await change(value);
    const file = path.join(dir, `${name}.json`);
    await fs.writeFile(`${file}.tmp`, JSON.stringify(value, null, 1) + '\n', 'utf8');
    await fs.rename(`${file}.tmp`, file);
    return result;
  }
  const { name: repoName, branch } = repo();
  let lastError = '';
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const { value, sha } = await readRemote(name);
    const result = await change(value);
    const response = await gh(`/repos/${repoName}/contents/${name}.json`, {
      method: 'PUT',
      body: JSON.stringify({
        message,
        branch,
        sha: sha || undefined,
        content: Buffer.from(JSON.stringify(value, null, 1) + '\n', 'utf8').toString('base64'),
        committer: { name: 'outreach-hq site', email: 'outreach-hq@users.noreply.github.com' },
      }),
    });
    if (response.ok) return result;
    lastError = `${response.status} ${await response.text()}`;
    if (![409, 422].includes(response.status)) break; // only a sha conflict is worth retrying
    await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
  }
  throw new Error(`Could not save ${name}.json: ${lastError}`);
}

// Start the send-and-track workflow now, so an approved email goes out within a minute or two.
export async function dispatchCycle(reason) {
  if (localDir()) return { started: false, note: 'local preview: the workflow is not started' };
  const { name: repoName } = repo();
  const response = await gh(`/repos/${repoName}/actions/workflows/cycle.yml/dispatches`, {
    method: 'POST',
    body: JSON.stringify({ ref: 'main', inputs: { reason: String(reason).slice(0, 100) } }),
  });
  if (!response.ok) return { started: false, note: `could not start the sender: ${response.status}` };
  return { started: true };
}

// "dry_run" or "live", read from config/settings.toml on main.
export async function sendingMode() {
  try {
    let text;
    if (localDir()) {
      text = await fs.readFile(path.resolve(/* turbopackIgnore: true */ process.cwd(), '../config/settings.toml'), 'utf8');
    } else {
      const { name: repoName } = repo();
      const response = await gh(`/repos/${repoName}/contents/config/settings.toml?ref=main`, {
        headers: { Accept: 'application/vnd.github.raw+json' },
      });
      if (!response.ok) return 'unknown';
      text = await response.text();
    }
    return (text.match(/^mode\s*=\s*"(\w+)"/m) || [])[1] || 'unknown';
  } catch {
    return 'unknown';
  }
}

export function nowIso() {
  // IST timestamp in the same shape the Python side writes.
  const ist = new Date(Date.now() + 5.5 * 3600 * 1000);
  return `${ist.toISOString().slice(0, 19)}+05:30`;
}

export function addTimeline(lead, actor, event, detail = '') {
  lead.timeline = lead.timeline || [];
  lead.timeline.push({ at: nowIso(), actor, event, detail });
  lead.updated_at = nowIso();
}
