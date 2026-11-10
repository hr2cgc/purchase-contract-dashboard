// /auth/callback : Microsoft 이 돌려준 code 를 토큰으로 바꾸고, 우리 회사(tenant) 계정이면 세션 쿠키 발급
import { FLOW_COOKIE, SESSION_COOKIE, getCookie, sign, verify, cookie, decodeJwtPayload, configured } from '../_lib.js';

const SESSION_HOURS = 12;

function back(msg) {
  return new Response(null, { status: 302, headers: { location: '/?e=' + encodeURIComponent(msg), 'set-cookie': cookie(FLOW_COOKIE, '', 0), 'cache-control': 'no-store' } });
}

export async function onRequestGet({ request, env }) {
  if (!configured(env)) return back('로그인 설정이 완료되지 않았습니다.');
  const url = new URL(request.url);
  if (url.searchParams.get('error')) return back('로그인이 취소되었거나 거부되었습니다.');
  const flow = await verify(env.SESSION_SECRET, getCookie(request, FLOW_COOKIE));
  const code = url.searchParams.get('code');
  if (!flow || !code || url.searchParams.get('state') !== flow.state) return back('로그인 시간이 만료되었습니다. 다시 시도해 주세요.');

  const tokenRes = await fetch(`https://login.microsoftonline.com/${env.MS_TENANT_ID}/oauth2/v2.0/token`, {
    method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: env.MS_CLIENT_ID, client_secret: env.MS_CLIENT_SECRET, grant_type: 'authorization_code', code,
      redirect_uri: `${url.origin}/auth/callback`, code_verifier: flow.verifier, scope: 'openid profile email',
    }).toString(),
  });
  if (!tokenRes.ok) return back('Microsoft 인증에 실패했습니다.');
  const tok = await tokenRes.json();
  if (!tok.id_token) return back('Microsoft 인증 응답이 올바르지 않습니다.');
  // 토큰 엔드포인트(TLS)에서 직접 받은 id_token 이므로 OIDC 규칙상 서명 재검증은 생략하고 클레임만 확인
  const c = decodeJwtPayload(tok.id_token);
  const now = Date.now() / 1000;
  if (c.tid !== env.MS_TENANT_ID || c.aud !== env.MS_CLIENT_ID || c.nonce !== flow.nonce || !(c.exp > now))
    return back('우리 회사 계정으로만 로그인할 수 있습니다.');
  const email = (c.preferred_username || c.email || '').toLowerCase();
  if (env.ALLOWED_EMAIL_DOMAIN && !email.endsWith('@' + env.ALLOWED_EMAIL_DOMAIN.toLowerCase()))
    return back('허용되지 않은 계정입니다.');

  const session = await sign(env.SESSION_SECRET, { name: c.name || '', email, exp: Math.floor(now) + SESSION_HOURS * 3600 });
  const headers = new Headers({ location: '/', 'cache-control': 'no-store' });
  headers.append('set-cookie', cookie(SESSION_COOKIE, session, SESSION_HOURS * 3600));
  headers.append('set-cookie', cookie(FLOW_COOKIE, '', 0));
  return new Response(null, { status: 302, headers });
}
