import Link from 'next/link';

export default function NotFound() {
  return (
    <main><div className="page-head"><h1>Not found</h1><p>That page or lead does not exist. <Link className="link" href="/">Back to leads</Link></p></div></main>
  );
}
