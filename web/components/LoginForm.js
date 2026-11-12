'use client';

import { useActionState } from 'react';
import { login } from '@/app/actions';

export default function LoginForm({ configured }) {
  const [state, action, pending] = useActionState(login, null);
  return (
    <form action={action}>
      <h1>Outreach HQ</h1>
      <p>Private. Enter the site password to continue.</p>
      {!configured ? <p className="warn">SITE_PASSWORD is not set on Vercel yet, so nobody can sign in.</p> : null}
      <input type="password" name="password" placeholder="Password" autoComplete="current-password" autoFocus required aria-label="Password" />
      <button className="button primary" type="submit" disabled={pending}>{pending ? 'Checking…' : 'Open'}</button>
      {state?.error ? <p className="feedback bad" role="alert">{state.error}</p> : null}
    </form>
  );
}
