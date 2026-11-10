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
       python watcher\\watcher.py --diagnose (파일 읽기 방법별 성공/실패 진단)
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


def _copy_plain(path, dst):
    shutil.copyfile(path, dst)


def _copy_shared(path, dst):
    """Windows: 다른 프로그램(Excel/OneDrive)이 열어 둔 파일도 읽기 공유 플래그를 모두 주고 열어서 복사."""
    if os.name != "nt":
        raise OSError("windows only")
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    GENERIC_READ, SHARE_ALL, OPEN_EXISTING = 0x80000000, 0x1 | 0x2 | 0x4, 3
    h = k32.CreateFileW(path, GENERIC_READ, SHARE_ALL, None, OPEN_EXISTING, 0x80, None)
    if h in (None, wintypes.HANDLE(-1).value, 0xFFFFFFFFFFFFFFFF):
        raise OSError(f"CreateFile 실패(코드 {ctypes.get_last_error()})")
    try:
        buf, chunks = ctypes.create_string_buffer(1 << 20), []
        n = wintypes.DWORD(0)
        while True:
            if not k32.ReadFile(h, buf, len(buf), ctypes.byref(n), None):
                raise OSError(f"ReadFile 실패(코드 {ctypes.get_last_error()})")
            if n.value == 0:
                break
            chunks.append(buf.raw[:n.value])
    finally:
        k32.CloseHandle(h)
    data = b"".join(chunks)
    if not data:
        raise OSError("빈 파일(동기화 중)")
    with open(dst, "wb") as f:
        f.write(data)


def _rows_from_open_excel(path):
    """Excel 이 그 파일을 열어 둔 상태라면, 실행 중인 Excel 에서 직접 값을 읽음 (pywin32 필요: py -m pip install pywin32)."""
    if os.name != "nt":
        raise OSError("windows only")
    import win32com.client  # type: ignore
    xl = win32com.client.GetActiveObject("Excel.Application")
    want = os.path.basename(path).lower()
    for wb in xl.Workbooks:
        if wb.Name.lower() == want:
            v = wb.Worksheets(1).UsedRange.Value
            if not isinstance(v, tuple):
                v = ((v,),)
            return [list(r) for r in v]
    raise OSError("Excel 에서 해당 파일이 열려 있지 않습니다")


def read_rows(path, retries=4, wait=2.0):
    """읽기 방법을 차례로 시도: 일반 복사 -> 공유 읽기 -> 열려 있는 Excel 에서 직접. 모두 실패하면 이유를 모아 RuntimeError."""
    errs = []
    for attempt in range(retries):
        for name, fn in (("일반복사", _copy_plain), ("공유읽기", _copy_shared)):
            d = tempfile.mkdtemp(prefix="contracts_")
            dst = os.path.join(d, "snap.xlsx")
            try:
                fn(path, dst)
                rows = build_data.read_xlsx(dst)
                return rows, name
            except build_data.InputError:
                raise
            except Exception as e:   # noqa: BLE001
                errs.append(f"{name}: {type(e).__name__}: {e}")
            finally:
                shutil.rmtree(d, ignore_errors=True)
        try:
            return _rows_from_open_excel(path), "열린Excel"
        except Exception as e:       # noqa: BLE001
            errs.append(f"열린Excel: {type(e).__name__}: {e}")
        time.sleep(wait)
    uniq = list(dict.fromkeys(errs))[-4:]
    raise RuntimeError("파일을 읽을 수 없습니다(잠김/동기화 중) -> " + " | ".join(uniq))


def parse_file(path):
    st = os.stat(path)
    rows, how = read_rows(path)
    recs, warns = build_data.convert(rows)
    log(f"읽기 방법: {how}") if how != "일반복사" else None
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


def diagnose(cfg):
    path = cfg["xlsx_path"]
    print("파일:", path)
    try:
        st = os.stat(path)
        print(f"  존재함, 크기 {st.st_size} 바이트, 수정 {datetime.datetime.fromtimestamp(st.st_mtime, KST).isoformat(timespec='seconds')}")
    except OSError as e:
        print("  찾을 수 없음:", e)
        return 1
    for name, fn in (("일반복사", _copy_plain), ("공유읽기", _copy_shared)):
        d = tempfile.mkdtemp(prefix="contracts_")
        try:
            fn(path, os.path.join(d, "snap.xlsx"))
            print(f"  [{name}] 성공")
        except Exception as e:   # noqa: BLE001
            print(f"  [{name}] 실패: {type(e).__name__}: {e}")
        finally:
            shutil.rmtree(d, ignore_errors=True)
    try:
        rows = _rows_from_open_excel(path)
        print(f"  [열린Excel] 성공 ({len(rows)}행)")
    except Exception as e:       # noqa: BLE001
        print(f"  [열린Excel] 실패: {type(e).__name__}: {e}")
    return 0


def main(argv):
    once, dry = "--once" in argv, "--dry-run" in argv
    cfg = load_config()
    if "--diagnose" in argv:
        return diagnose(cfg)
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
