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


def read_xlsx(path):
    import openpyxl
    ws = openpyxl.load_workbook(path, data_only=True).active
    return [list(r) for r in ws.iter_rows(values_only=True)]


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
