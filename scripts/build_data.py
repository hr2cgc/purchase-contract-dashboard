#!/usr/bin/env python3
"""엑셀(매입 계약 진행 현황) -> data.js 변환.

사용법:  python3 scripts/build_data.py "계약현황.xlsx"
필요 패키지: pip install openpyxl
엑셀 구조(헤더 2행, 데이터 3행부터)가 바뀌면 COLS 를 수정하세요.
"""
import sys, json, datetime, pathlib
import openpyxl

COLS = ["project", "vendor", "name", "pm", "start", "end",
        "legal", "approval", "send", "receive", "bond",
        "adv_bond", "adv_tax", "adv_appr", "adv_date",
        "bal_tax", "bal_appr", "bal_date", "note"]
DATE_COLS = {"start", "end", "adv_date", "bal_date"}
MARK_COLS = {"legal", "approval", "send", "receive", "bond",
             "adv_bond", "adv_tax", "adv_appr", "bal_tax", "bal_appr"}


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


def main(path):
    ws = openpyxl.load_workbook(path, data_only=True).active
    rows, project = [], ""
    for r in ws.iter_rows(min_row=3, values_only=True):
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
            elif c in MARK_COLS:
                rec[c] = norm_mark(rec[c])
            else:
                rec[c] = "" if rec[c] is None else str(rec[c]).strip()
        rows.append(rec)

    out = pathlib.Path(__file__).resolve().parent.parent / "data.js"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    out.write_text(
        "// scripts/build_data.py 로 자동 생성된 파일입니다. 직접 수정하지 마세요.\n"
        f"window.DATA_UPDATED = {json.dumps(today)};\n"
        f"window.CONTRACTS = {json.dumps(rows, ensure_ascii=False, indent=1)};\n",
        encoding="utf-8")
    print(f"{len(rows)}건 -> {out}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
