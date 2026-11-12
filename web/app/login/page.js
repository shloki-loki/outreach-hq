import { redirect } from 'next/navigation';
import { isSignedIn, passwordIsSet } from '@/lib/auth';
import LoginForm from '@/components/LoginForm';

export const dynamic = 'force-dynamic';

export default async function LoginPage() {
  if (await isSignedIn()) redirect('/');
  return (
    <div className="login">
      <LoginForm configured={passwordIsSet()} />
    </div>
  );
}
