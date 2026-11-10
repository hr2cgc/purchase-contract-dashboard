// /auth/login : Microsoft 로그인 화면으로 보냄 (Authorization Code + PKCE)
import { FLOW_COOKIE, sign, cookie, randomId, pkceChallenge, configured } from '../_lib.js';

export async function onRequestGet({ request, env }) {
  if (!configured(env)) return new Response('로그인 설정이 완료되지 않았습니다.', { status: 503 });
  const url = new URL(request.url);
  const state = randomId(), nonce = randomId(), verifier = randomId(32);
  const flow = await sign(env.SESSION_SECRET, { state, nonce, verifier, exp: Math.floor(Date.now() / 1000) + 600 });
  const auth = new URL(`https://login.microsoftonline.com/${env.MS_TENANT_ID}/oauth2/v2.0/authorize`);
  auth.search = new URLSearchParams({
    client_id: env.MS_CLIENT_ID, response_type: 'code', response_mode: 'query',
    redirect_uri: `${url.origin}/auth/callback`, scope: 'openid profile email',
    state, nonce, code_challenge: await pkceChallenge(verifier), code_challenge_method: 'S256',
  }).toString();
  return new Response(null, { status: 302, headers: { location: auth.toString(), 'set-cookie': cookie(FLOW_COOKIE, flow, 600), 'cache-control': 'no-store' } });
}
