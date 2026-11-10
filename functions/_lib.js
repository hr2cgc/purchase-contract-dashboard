// 공용 도우미: 세션 쿠키 서명/검증, 쿠키 파싱
const enc = new TextEncoder();
export const SESSION_COOKIE = 'pcd_session';
export const FLOW_COOKIE = 'pcd_flow';

function b64u(buf) {
  let s = ''; const b = new Uint8Array(buf);
  for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function b64uToStr(s) {
  s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '=';
  const bin = atob(s); const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}
async function hmac(secret, data) {
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return b64u(await crypto.subtle.sign('HMAC', key, enc.encode(data)));
}
function safeEq(a, b) {
  if (a.length !== b.length) return false;
  let r = 0; for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}
export async function sign(secret, obj) {
  const body = b64u(enc.encode(JSON.stringify(obj)));
  return body + '.' + (await hmac(secret, body));
}
export async function verify(secret, token) {
  if (!token || !secret) return null;
  const i = token.lastIndexOf('.'); if (i < 1) return null;
  const body = token.slice(0, i), mac = token.slice(i + 1);
  if (!safeEq(mac, await hmac(secret, body))) return null;
  try {
    const obj = JSON.parse(b64uToStr(body));
    if (!obj.exp || Date.now() / 1000 > obj.exp) return null;
    return obj;
  } catch (e) { return null; }
}
export function getCookie(request, name) {
  const h = request.headers.get('cookie') || '';
  for (const part of h.split(/;\s*/)) { const k = part.indexOf('='); if (k > 0 && part.slice(0, k) === name) return part.slice(k + 1); }
  return '';
}
export function cookie(name, value, maxAge) {
  return `${name}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;
}
export function randomId(bytes = 24) { return b64u(crypto.getRandomValues(new Uint8Array(bytes))); }
export async function pkceChallenge(verifier) { return b64u(await crypto.subtle.digest('SHA-256', enc.encode(verifier))); }
export function decodeJwtPayload(jwt) { return JSON.parse(b64uToStr(jwt.split('.')[1])); }
export function configured(env) { return !!(env.MS_TENANT_ID && env.MS_CLIENT_ID && env.MS_CLIENT_SECRET && env.SESSION_SECRET); }
