// GET /api/data  -> { data: {hash, rows, count, warnings, sourceModified, syncedAt} | null, heartbeat: {...} | null, now }
// KV 바인딩 이름: CONTRACTS_KV  (Cloudflare Pages > 설정 > 함수 > KV 네임스페이스 바인딩)
// 이 경로도 Cloudflare Access(로그인) 보호 대상입니다. 데이터는 이 경로로만 나가고, 정적 파일에는 들어 있지 않습니다.
export async function onRequestGet({ env }) {
  if (!env.CONTRACTS_KV) {
    return json({ error: 'KV 바인딩(CONTRACTS_KV)이 설정되지 않았습니다.' }, 500);
  }
  const [data, heartbeat] = await Promise.all([
    env.CONTRACTS_KV.get('latest', 'json'),
    env.CONTRACTS_KV.get('heartbeat', 'json'),
  ]);
  return json({ data, heartbeat, now: new Date().toISOString() }, 200);
}

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' },
  });
}
