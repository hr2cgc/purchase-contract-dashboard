import { SESSION_COOKIE, cookie } from '../_lib.js';
export async function onRequest() {
  return new Response(null, { status: 302, headers: { location: '/', 'set-cookie': cookie(SESSION_COOKIE, '', 0), 'cache-control': 'no-store' } });
}
