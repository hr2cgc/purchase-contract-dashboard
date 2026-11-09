#!/usr/bin/env python3
"""Cloudflare Pages 배포용 폴더(dist/) 생성. 계약 데이터(data.js)는 절대 포함하지 않습니다.

  python scripts/make_dist.py
  npx wrangler pages deploy dist --project-name purchase-contract-dashboard
"""
import pathlib, shutil
root = pathlib.Path(__file__).resolve().parent.parent
dist = root / "dist"
if dist.exists():
    shutil.rmtree(dist)
dist.mkdir()
for name in ("index.html",):
    shutil.copy2(root / name, dist / name)
for d in ("fonts", "vendor"):
    shutil.copytree(root / d, dist / d)
(dist / "data.js").write_text("// 배포본에는 계약 데이터가 없습니다. /api/data (로그인 후)에서 받아옵니다.\nwindow.CONTRACTS = null;\n", encoding="utf-8")
(dist / "config.js").write_text("window.SYNC_URL = '/api/data';\nwindow.SYNC_INTERVAL_MS = 30000;\n", encoding="utf-8")
# 로그인 전 화면이 검색엔진/캐시에 남지 않게
(dist / "_headers").write_text("/*\n  X-Robots-Tag: noindex\n  Referrer-Policy: no-referrer\n  X-Content-Type-Options: nosniff\n", encoding="utf-8")
(dist / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
assert not any("CONTRACTS = [" in p.read_text(encoding="utf-8", errors="ignore") for p in dist.rglob("*.js") if "vendor" not in p.parts)
print("dist/ 생성 완료:", sorted(p.name for p in dist.iterdir()))
