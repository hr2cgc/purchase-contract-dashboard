#!/usr/bin/env python3
"""OneDrive 동기화 폴더의 '매입 계약 진행 현황.xlsx' 를 감시해서 Cloudflare KV 에 올리는 프로그램.

- AI/Claude 를 쓰지 않는 일반 프로그램입니다. 이 PC 가 켜져 있고 OneDrive 가 동기화 중일 때 동작합니다.
- 파일이 바뀌면(수정시각·크기) 임시 복사본을 만들어 읽고(저장 중/잠금이면 재시도),
  기존 변환 규칙(scripts/build_data.py)으로 검증한 뒤, 내용 해시가 직전과 다를 때만 업로드합니다.
- 변환 실패·업로드 실패 시에는 마지막 정상 데이터를 그대로 두고, 오류만 상태(heartbeat)에 남깁니다.
- 설정: watcher/config.json (config.example.json 참고). 토큰이 들어 있으니 절대 GitHub 에 올리지 마세요.

실행:  python watcher\\watcher.py            (계속 실행)
       python watcher\\watcher.py --once     (한 번만 확인하고 종료)
       python watcher\\watcher.py --dry-run  (업로드 없이 변환 결과만 확인)
"""
import sys, os, json, time, hashlib, shutil, tempfile, pathlib, datetime, urllib.request, urllib.error, traceback

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "scripts"))
import build_data  # noqa: E402  (기존 변환 규칙 재사용)

KST = datetime.timezone(datetime.timedelta(hours=9))
CONFIG_PATH = pathlib.Path(os.environ.get("WATCHER_CONFIG", ROOT / "config.json"))
STATE_PATH = ROOT / ".watcher_state.json"
LOG_PATH = ROOT / "watcher.log"


def now_iso():
    return datetime.datetime.now(KST).isoformat(timespec="seconds")


def log(msg):
    line = f"{now_iso()} {msg}"
    print(line, flush=True)
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 1_000_000:
            LOG_PATH.replace(LOG_PATH.with_suffix(".log.old"))
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_config():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for k in ("xlsx_path", "cf_account_id", "cf_kv_namespace_id", "cf_api_token"):
        if not cfg.get(k) or str(cfg[k]).startswith("여기에"):
            raise SystemExit(f"config.json 의 '{k}' 값을 채워 주세요.")
    cfg.setdefault("poll_seconds", 5)
    cfg.setdefault("heartbeat_seconds", 300)     # KV 무료 쓰기 한도(하루 1,000회) 안에서 하루 288회
    cfg.setdefault("settle_seconds", 3)
    return cfg


def load_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(st):
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_PATH)


def kv_put(cfg, key, obj):
    base = cfg.get("cf_api_base", "https://api.cloudflare.com/client/v4")
    url = (f"{base}/accounts/{cfg['cf_account_id']}"
           f"/storage/kv/namespaces/{cfg['cf_kv_namespace_id']}/values/{key}")
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="PUT", headers={
        "Authorization": f"Bearer {cfg['cf_api_token']}", "Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"KV 업로드 실패 HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
    if not res.get("success"):
        raise RuntimeError(f"KV 업로드 실패: {res.get('errors')}")


def snapshot(path, retries=6, wait=2.0):
    """엑셀이 열려 있거나 동기화 중이어도 읽을 수 있게 임시 폴더로 복사. 실패하면 잠시 후 재시도."""
    last = None
    for _ in range(retries):
        try:
            st = os.stat(path)
            d = tempfile.mkdtemp(prefix="contracts_")
            dst = os.path.join(d, "snap.xlsx")
            shutil.copyfile(path, dst)
            if os.path.getsize(dst) != st.st_size and os.path.getsize(dst) == 0:
                raise OSError("빈 파일(동기화 중)")
            return dst, st
        except OSError as e:
            last = e
            time.sleep(wait)
    raise RuntimeError(f"파일을 읽을 수 없습니다(잠김/동기화 중): {last}")


def parse_file(path):
    snap, st = snapshot(path)
    try:
        rows = build_data.read_xlsx(snap)
        recs, warns = build_data.convert(rows)
    finally:
        shutil.rmtree(os.path.dirname(snap), ignore_errors=True)
    return recs, warns, st


def content_hash(recs):
    return hashlib.sha256(json.dumps(recs, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def sync_once(cfg, state, dry=False, force=False):
    """변경이 있으면 업로드. 반환: 상태 문자열."""
    path = cfg["xlsx_path"]
    try:
        st = os.stat(path)
    except OSError as e:
        state["error"] = f"원본 파일을 찾을 수 없습니다: {e}"
        return "error"
    sig = [st.st_mtime_ns, st.st_size]
    if not force and state.get("sig") == sig:
        return "same-file"
    if not force and state.get("err_sig") == sig and time.time() < state.get("retry_at", 0):
        return "backoff"             # 직전에 읽기 실패 -> 30초 뒤 재시도(로그/KV 쓰기 폭주 방지)
    # 저장 직후에는 OneDrive 가 아직 쓰는 중일 수 있어, 수정시각이 안정될 때까지 잠깐 기다림
    time.sleep(cfg["settle_seconds"])
    try:
        recs, warns, st2 = parse_file(path)
    except (build_data.InputError, RuntimeError, Exception) as e:   # noqa: BLE001
        state["error"] = f"{type(e).__name__}: {e}"
        log(f"변환 실패(마지막 정상 데이터 유지): {state['error']}")
        # 엑셀 구조 오류는 파일이 다시 저장될 때까지 재시도하지 않고, 잠김/동기화 지연은 다음 주기에 다시 시도
        state["sig"] = sig if isinstance(e, build_data.InputError) else None
        state["retry_at"] = time.time() + 30
        state["err_sig"] = sig       # 파일이 다시 저장되면(시그니처 변경) 대기 없이 바로 재시도
        return "error"
    state["sig"] = [st2.st_mtime_ns, st2.st_size]
    state["retry_at"] = 0
    h = content_hash(recs)
    if h == state.get("hash") and not force:
        state["error"] = ""
        return "same-data"          # 엑셀은 저장됐지만 대시보드에 보이는 내용은 그대로
    payload = {
        "hash": h, "rows": recs, "count": len(recs), "warnings": warns[:20],
        "sourceModified": datetime.datetime.fromtimestamp(st2.st_mtime, KST).isoformat(timespec="seconds"),
        "syncedAt": now_iso(),
    }
    if dry:
        log(f"[dry-run] {build_data.summarize(recs)} hash={h}")
        return "dry-run"
    kv_put(cfg, "latest", payload)
    state.update(hash=h, error="", syncedAt=payload["syncedAt"], sourceModified=payload["sourceModified"])
    log(f"업로드 완료: {build_data.summarize(recs)} hash={h}")
    return "uploaded"


def heartbeat(cfg, state):
    kv_put(cfg, "heartbeat", {"at": now_iso(), "ok": not state.get("error"), "error": state.get("error", ""),
                              "syncedAt": state.get("syncedAt", ""), "sourceModified": state.get("sourceModified", "")})
    state["hb_at"] = time.time()


def main(argv):
    once, dry = "--once" in argv, "--dry-run" in argv
    cfg = load_config()
    state = load_state()
    log(f"감시 시작: {cfg['xlsx_path']} (확인 주기 {cfg['poll_seconds']}초)")
    first = True
    while True:
        try:
            result = sync_once(cfg, state, dry=dry, force=first and not state.get("hash"))
            first = False
            if not dry:
                err_changed = state.get("error") != state.get("hb_err")
                if result == "uploaded" or err_changed or time.time() - state.get("hb_at", 0) >= cfg["heartbeat_seconds"]:
                    heartbeat(cfg, state)
                    state["hb_err"] = state.get("error")
            save_state({k: v for k, v in state.items() if k not in ("hb_at", "retry_at", "err_sig")})
        except Exception as e:  # 네트워크 오류 등: 프로그램은 계속 실행, 마지막 정상 데이터는 서버에 그대로 남음
            state["error"] = f"{type(e).__name__}: {e}"
            state["sig"] = None   # 다음 주기에 다시 시도
            log("오류(재시도 예정): " + state["error"])
            if os.environ.get("WATCHER_DEBUG"):
                traceback.print_exc()
        if once:
            return 0 if not state.get("error") else 1
        time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
