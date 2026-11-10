// 모든 요청 앞단: 로그인(세션)이 없으면 데이터·화면을 내보내지 않고 로그인 화면만 보여 줍니다.
import { SESSION_COOKIE, getCookie, verify, configured } from './_lib.js';

export async function onRequest(context) {
  const { request, env, next } = context;
  const url = new URL(request.url);
  if (url.pathname.startsWith('/auth/')) return next();          // 로그인 흐름 자체는 통과
  if (url.pathname === '/robots.txt') return next();

  const session = await verify(env.SESSION_SECRET, getCookie(request, SESSION_COOKIE));
  if (session) {
    const res = await next();
    const out = new Response(res.body, res);
    out.headers.set('cache-control', 'no-store');
    return out;
  }
  if (url.pathname.startsWith('/api/')) {
    return new Response(JSON.stringify({ error: '로그인이 필요합니다.' }), {
      status: 401, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });
  }
  return new Response(loginPage(configured(env), url.searchParams.get('e')), {
    status: 401, headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store', 'x-robots-tag': 'noindex' } });
}

function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

function loginPage(ok, err) {
  const msg = ok ? (err ? esc(err) : '') : '로그인 설정이 아직 완료되지 않았습니다. 관리자에게 문의하세요.';
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>매입 계약 현황 · 로그인</title>
<style>
:root{color-scheme:light dark;--bg:#F8F9FB;--surface:#fff;--text:#111827;--text2:#6B7280;--border:#E5E7EB;--accent:#2563EB;--danger:#B91C1C}
@media (prefers-color-scheme:dark){:root{--bg:#0F1115;--surface:#171A21;--text:#F3F4F6;--text2:#9CA3AF;--border:#2A2F3A;--accent:#3B82F6;--danger:#F87171}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--text);font:400 14px/1.55 -apple-system,"Segoe UI","Malgun Gothic",sans-serif}
.card{width:min(420px,92vw);background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:28px}
h1{margin:0 0 4px;font-size:20px;letter-spacing:-.02em}p{margin:0 0 20px;color:var(--text2)}
a.btn{display:flex;align-items:center;justify-content:center;gap:10px;height:44px;border-radius:8px;background:var(--accent);color:#fff;text-decoration:none;font-weight:600}
a.btn[aria-disabled=true]{opacity:.45;pointer-events:none}.err{margin-top:14px;color:var(--danger);font-size:13px}
.ms{display:grid;grid-template-columns:9px 9px;gap:2px}.ms i{width:9px;height:9px;display:block}
</style></head><body><main class="card"><h1>매입 계약 현황 대시보드</h1><p>회사 Microsoft 계정으로 로그인하세요.</p>
<a class="btn" href="/auth/login" ${ok ? '' : 'aria-disabled="true"'}><span class="ms"><i style="background:#F25022"></i><i style="background:#7FBA00"></i><i style="background:#00A4EF"></i><i style="background:#FFB900"></i></span>Microsoft로 로그인</a>
${msg ? `<div class="err" role="alert">${msg}</div>` : ''}</main></body></html>`;
}
