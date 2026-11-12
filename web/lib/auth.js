// One password, one signed cookie. Checked inside every page and every server action, so there is
// no single gate (such as a middleware) whose bypass would open the site.

import { createHash, createHmac, timingSafeEqual } from 'crypto';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

const COOKIE = 'ohq_session';
const THIRTY_DAYS = 30 * 24 * 3600;

const digest = (text) => createHash('sha256').update(String(text)).digest();
const signingKey = () => digest(`outreach-hq:cookie:${process.env.SITE_PASSWORD}`);
const sign = (payload) => createHmac('sha256', signingKey()).update(payload).digest('hex');

// Local preview without a password: only when not in production AND reading local files.
export function openForLocalPreview() {
  return process.env.NODE_ENV !== 'production' && Boolean(process.env.DATA_DIR) && !process.env.SITE_PASSWORD;
}

export function passwordIsSet() {
  return Boolean(process.env.SITE_PASSWORD);
}

export function passwordMatches(given) {
  if (!passwordIsSet()) return false;
  return timingSafeEqual(digest(given), digest(process.env.SITE_PASSWORD));
}

export async function startSession() {
  const expires = Math.floor(Date.now() / 1000) + THIRTY_DAYS;
  (await cookies()).set(COOKIE, `${expires}.${sign(String(expires))}`, {
    httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: THIRTY_DAYS,
  });
}

export async function endSession() {
  (await cookies()).delete(COOKIE);
}

export async function isSignedIn() {
  if (openForLocalPreview()) return true;
  if (!passwordIsSet()) return false;
  const value = (await cookies()).get(COOKIE)?.value || '';
  const [expires, signature] = value.split('.');
  if (!expires || !signature || Number(expires) < Date.now() / 1000) return false;
  const expected = Buffer.from(sign(expires), 'hex');
  const given = Buffer.from(signature, 'hex');
  return expected.length === given.length && timingSafeEqual(expected, given);
}

// For pages: send a stranger to the login screen.
export async function requireSignIn() {
  if (!(await isSignedIn())) redirect('/login');
}

// For server actions: refuse outright.
export async function assertSignedIn() {
  if (!(await isSignedIn())) throw new Error('Not signed in.');
}
