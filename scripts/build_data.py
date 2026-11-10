#!/usr/bin/env python3
"""매입 계약 진행 현황 -> data.js 변환.

입력 형식 두 가지를 지원합니다.
  1) 엑셀 파일(.xlsx)
  2) 탭으로 구분된 텍스트(.tsv / .txt) : 엑셀 시트를 그대로 복사한 형태(Microsoft 365 커넥터가 읽어 온 결과)

사용법:
  python3 scripts/build_data.py "계약현황.xlsx"
  python3 scripts/build_data.py /tmp/contracts.tsv
  python3 scripts/build_data.py /tmp/contracts.tsv --dry-run      # 파일은 쓰지 않고 검증 결과만 출력

종료 코드: 0 정상 / 1 입력 구조 이상(헤더 불일치, 0건 등) -> 이때는 data.js 를 건드리지 않습니다.
엑셀 구조(헤더 2행, 데이터 3행부터)가 바뀌면 COLS 와 HEADER_CHECK 를 수정하세요.
"""
import sys, json, re, datetime, pathlib

COLS = ["project", "vendor", "name", "pm", "start", "end",
        "legal", "approval", "send", "receive", "bond",
        "adv_bond", "adv_tax", "adv_appr", "adv_date",
        "bal_tax", "bal_appr", "bal_date", "note"]
DATE_COLS = {"start", "end", "adv_date", "bal_date"}
MARK_COLS = {"legal", "approval", "send", "receive", "bond",
             "adv_bond", "adv_tax", "adv_appr", "bal_tax", "bal_appr"}
# 2행(열 이름 행)에서 반드시 맞아야 하는 열 위치와 이름 -> 구조가 바뀌면 중단
HEADER_CHECK = {0: "사업명", 1: "업체명", 2: "계약명", 3: "담당 PM", 4: "계약 시작일", 5: "계약 종료일",
                6: "법무검토 요청", 7: "계약 품의", 8: "계약서 송부", 9: "계약서 회수", 10: "계약보증증권",
                11: "선금보증증권", 14: "집행(예정)일", 18: "비고"}
ALLOWED_MARKS = {"", "O", "X", "대체"}
# 엑셀에서 회색으로 칠한 칸 = '해당 없음 / 이슈로 진행 안 함 / 홀딩' (진행 중이 아님).
# 색상은 값이 아니라 서식이므로 따로 읽어서 각 행의 "na" 목록(열 이름)으로 담습니다. 값이 들어 있는 칸은 값이 우선입니다.
NA_FIRST, NA_LAST = 4, 17            # start ~ bal_date 열만 확인 (사업명·업체명·비고 칸 색은 무시)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class InputError(Exception):
    pass


def norm_date(v):
    if v in (None, ""):
        return ""
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def norm_mark(v):
    """O=완료, X=문제/거부, 대체=각서 등으로 대체, ''=미완료"""
    if v in (None, ""):
        return ""
    s = str(v).strip()
    if s.upper() == "O":
        return "O"
    if s.upper() == "X":
        return "X"
    if "대체" in s:
        return "대체"
    return s


def is_gray_rgb(r, g, b):
    """연한~중간 회색(흰색·검정·색 있는 칸은 제외)."""
    return max(r, g, b) - min(r, g, b) <= 12 and 100 <= (r + g + b) / 3 <= 248


def _gray_openpyxl(fill):
    """openpyxl 채우기 객체가 회색 계열이면 True. 테마색은 Office 기본 테마(흰/검정/연회색) 기준으로 계산."""
    try:
        if fill is None or fill.fill_type != "solid":
            return False
        c = fill.fgColor
        if c.type == "rgb" and isinstance(c.rgb, str) and len(c.rgb) >= 6:
            h = c.rgb[-6:]
            return is_gray_rgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        if c.type == "theme":
            tint = c.tint or 0
            base = {0: 255, 1: 0, 2: 231}.get(c.theme)      # 흰색 / 검정 / 연한 회색(lt2)
            if base is None:
                return False
            v = base * (1 + tint) if tint < 0 else base + (255 - base) * tint
            return is_gray_rgb(v, v, v)
        if c.type == "indexed":
            return c.indexed in (22, 23, 55)                  # 회색 계열 인덱스 색
    except Exception:   # noqa: BLE001
        return False
    return False


def read_xlsx(path):
    """값 행 목록을 돌려줍니다. 각 행 끝(19번째 뒤)에 회색 칸의 열 번호 목록을 덧붙입니다."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)      # 서식(채우기)을 읽어야 하므로 read_only 를 쓰지 않음
    ws = wb.active
    rows = []
    for r in ws.iter_rows():
        vals = [c.value for c in r]
        vals += [None] * (len(COLS) - len(vals))
        gray = [i for i in range(NA_FIRST, NA_LAST + 1) if i < len(r) and _gray_openpyxl(r[i].fill)]
        rows.append(vals[:len(COLS)] + [gray])
    return rows


def read_tsv(path):
    """탭 구분 텍스트. 'Workbook:' / '## Sheet:' 같은 안내 줄과 빈 줄은 건너뜁니다."""
    rows = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("Workbook:") or line.startswith("## Sheet") or line.startswith("Formulas"):
            continue
        if not line.strip("\t "):
            continue           # 완전히 빈 줄은 무시
        rows.append(line.split("\t"))
    return rows


def check_header(rows):
    if len(rows) < 3:
        raise InputError("행이 너무 적습니다(헤더 2행 + 데이터 1행 이상 필요).")
    header = [("" if c is None else str(c).strip()) for c in rows[1]]
    header += [""] * (len(COLS) - len(header))
    bad = [f"{i + 1}열: 기대 '{want}' / 실제 '{header[i]}'" for i, want in HEADER_CHECK.items() if header[i] != want]
    if bad:
        raise InputError("엑셀 열 구조가 달라졌습니다 -> " + "; ".join(bad))


def convert(rows):
    check_header(rows)
    out, project, warns = [], "", []
    for n, r in enumerate(rows[2:], start=3):
        r = list(r) + [None] * (len(COLS) - len(r))
        gray = r[len(COLS)] if len(r) > len(COLS) and isinstance(r[len(COLS)], (list, tuple)) else []
        rec = dict(zip(COLS, r[:len(COLS)]))
        if not any(rec[c] for c in ("vendor", "name")):
            continue  # 빈 줄
        if rec["project"]:
            project = str(rec["project"]).strip()  # 병합셀: 위 행 사업명 이어받기
        rec["project"] = project
        for c in COLS:
            if c in DATE_COLS:
                rec[c] = norm_date(rec[c])
                if rec[c] and not DATE_RE.match(rec[c]):
                    warns.append(f"{n}행 {c}: 날짜 형식 이상 '{rec[c]}'")
            elif c in MARK_COLS:
                rec[c] = norm_mark(rec[c])
                if rec[c] not in ALLOWED_MARKS:
                    warns.append(f"{n}행 {c}: 알 수 없는 표시값 '{rec[c]}'")
            else:
                rec[c] = "" if rec[c] is None else str(rec[c]).strip()
        if not rec["project"]:
            warns.append(f"{n}행: 사업명이 비어 있음")
        # 회색 칸 중 값이 비어 있는 칸만 '해당 없음'으로 기록
        rec["na"] = [COLS[i] for i in gray if NA_FIRST <= i <= NA_LAST and COLS[i] != "" and rec[COLS[i]] in ("", None)]
        out.append(rec)
    if not out:
        raise InputError("계약 데이터가 0건입니다.")
    return out, warns


def summarize(recs):
    steps = ["legal", "approval", "send", "receive", "bond"]
    done = lambda v: v in ("O", "대체")
    stage, issues = {}, 0
    for r in recs:
        last = -1
        for i, s in enumerate(steps):
            if done(r[s]):
                last = i
        key = "홀딩" if "홀딩" in r["note"] else f"{1 if last <= 0 else last + 1}단계"
        stage[key] = stage.get(key, 0) + 1
        if any(r[c] == "X" for c in MARK_COLS):
            issues += 1
    return f"{len(recs)}건 | 단계별 {dict(sorted(stage.items()))} | 확인 필요(X) {issues}건"


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    dry = "--dry-run" in argv
    if len(args) != 1:
        sys.exit(__doc__)
    path = args[0]
    try:
        rows = read_xlsx(path) if path.lower().endswith((".xlsx", ".xlsm")) else read_tsv(path)
        recs, warns = convert(rows)
    except InputError as e:
        print("입력 오류:", e, file=sys.stderr)
        return 1
    for w in warns:
        print("경고:", w, file=sys.stderr)
    print(summarize(recs))
    if dry:
        return 0
    out = pathlib.Path(__file__).resolve().parent.parent / "data.js"
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d")  # 한국 시간 기준
    out.write_text(
        "// scripts/build_data.py 로 자동 생성된 파일입니다. 직접 수정하지 마세요.\n"
        f"window.DATA_UPDATED = {json.dumps(today)};\n"
        f"window.CONTRACTS = {json.dumps(recs, ensure_ascii=False, indent=1)};\n",
        encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
