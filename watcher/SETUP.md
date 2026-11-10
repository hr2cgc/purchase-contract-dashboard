# 자동 반영 설정 (한 번만, 약 20분)

## 0. 준비 (내 PC)
1. Python 설치 후 `install-openpyxl.bat` 더블클릭 (또는 `py -m pip install openpyxl`)
2. 원본 폴더가 OneDrive 로 PC 에 동기화돼 있어야 합니다(탐색기에서 `매입 계약 진행 현황.xlsx` 가 보이고, 초록 체크 또는 "항상 이 디바이스에 유지"). 아니면 SharePoint/Teams 파일 탭에서 "OneDrive에 바로 가기 추가" 또는 "동기화".
3. 파일 경로 확인 후 `watcher/config.example.json` 을 `config.json` 으로 복사.

## 1. Cloudflare (무료 계정)
1. dash.cloudflare.com 가입 → Workers & Pages → KV → **Create namespace** `contracts` → Namespace ID 복사
2. 계정 ID: 대시보드 우측 사이드바 Account ID
3. My Profile → API Tokens → Create Token → Custom: 권한 `Account / Workers KV Storage / Edit` 만. 토큰 복사
4. 위 세 값을 `watcher/config.json` 에 입력

## 2. 배포
```
py scripts/make_dist.py
npx wrangler login
npx wrangler pages deploy dist --project-name purchase-contract-dashboard
```
(Node.js 필요. 첫 배포 시 프로젝트 생성 질문에 Production 브랜치 main)
- Pages 프로젝트 → Settings → Bindings(Functions) → KV namespace 추가: 변수명 `CONTRACTS_KV`, 네임스페이스 `contracts` → **다시 배포**
- `functions/` 폴더가 있는 위치(프로젝트 루트)에서 위 명령을 실행해야 `/api/data` 가 함께 배포됩니다.

## 3. 접근 제한 (필수 — 이걸 해야 계약 정보가 비공개)
1. dash.cloudflare.com → Zero Trust (무료 플랜, 50명까지) → Access → Applications → Add → Self-hosted
2. 도메인: `purchase-contract-dashboard.pages.dev` (Pages 의 `*.` 미리보기 주소도 같이 보호 권장)
3. Policy: Allow → Emails ending in `@회사도메인` → 로그인 방법 One-time PIN
4. 직원은 URL 접속 → 회사 이메일 입력 → 메일로 온 6자리 코드 입력 (GitHub·Claude 계정 불필요)

## 4. 감시 프로그램 실행
```
py watcher\watcher.py --dry-run     # 변환 결과만 확인
py watcher\watcher.py               # 계속 실행
```
- 부팅 시 자동 실행: 작업 스케줄러 → 로그온 시 `pythonw.exe C:\...\watcher\watcher.py` (시작 위치: 프로젝트 폴더)
- 로그: `watcher/watcher.log`

## 5. 직원 로그인 (Microsoft 회사 계정) — Cloudflare Zero Trust(카드 등록) 대신 사용
1. entra.microsoft.com → App registrations → New registration → 이름 `BX 매입계약 대시보드`, **Single tenant**, Redirect URI(Web): `https://purchase-contract-dashboard.pages.dev/auth/callback`
2. 앱 화면의 Application (client) ID, Directory (tenant) ID 확인
3. Certificates & secrets → New client secret → **값(Value)** 복사 (한 번만 보임, 채팅에 붙여 넣지 말 것)
4. wrangler.toml 에 추가:
```
[vars]
MS_TENANT_ID = "<tenant id>"
MS_CLIENT_ID = "<client id>"
ALLOWED_EMAIL_DOMAIN = "dtonic.io"
```
5. 비밀값 등록(프로젝트 폴더에서):
```
npx wrangler pages secret put MS_CLIENT_SECRET --project-name purchase-contract-dashboard
npx wrangler pages secret put SESSION_SECRET --project-name purchase-contract-dashboard
```
   (SESSION_SECRET 은 임의의 긴 문자열 32자 이상: `py -c "import secrets;print(secrets.token_urlsafe(48))"` 결과를 붙여 넣기)
6. 다시 배포: `py scripts\make_dist.py` → `npx wrangler pages deploy`
