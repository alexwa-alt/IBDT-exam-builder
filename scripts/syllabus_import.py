"""Read the DT strands workbook (Criteria A, B, C and Command Terms) into site/data/dt/syllabus.json.

Each syllabus statement gets an id such as A1.1.3, its topic (A1.1), level (SL or HL), the term and units it is
taught in, and its text. Problems in the workbook are reported in syllabus_review.json rather than guessed at,
except the corrections listed in FIXES, which follow the IB guide.

Usage: python scripts/syllabus_import.py [path/to/DT_IB_Strands.xlsx]
"""
import datetime
import json
import re
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
TOPICS = {  # topic titles from the guide (first assessment 2027)
    "A1.1": "Ergonomics", "A2.1": "User-centred research methods", "A2.2": "Prototyping techniques",
    "A3.1": "Material classification and properties", "A3.2": "Introduction to structural systems",
    "A3.3": "Introduction to mechanical systems", "A3.4": "Introduction to electronic systems",
    "A4.1": "Manufacturing techniques", "B1.1": "User-centred design", "B2.1": "The design process",
    "B2.2": "Modelling and prototyping", "B3.1": "Material selection",
    "B3.2": "Structural systems application and selection", "B3.3": "Mechanical systems application and selection",
    "B3.4": "Electronic systems application and selection", "B4.1": "Production systems",
    "C1.1": "Responsibility of the designer", "C1.2": "Inclusive design", "C1.3": "Beyond usability",
    "C2.1": "Design for sustainability", "C2.2": "Design for a circular economy",
    "C3.1": "Product analysis and evaluation", "C3.2": "Life-cycle analysis", "C4.1": "Design for manufacture strategies"}
ROWS = {"1": "People", "2": "Process", "3": "Product", "4": "Production"}
STRANDS = {"A": "Design in theory", "B": "Design in practice", "C": "Design in context"}
HL_ONLY = {"A3.2", "A3.3", "A3.4", "A4.1", "B3.2", "B3.3", "B3.4", "B4.1", "C1.3", "C3.2", "C4.1"}
FIXES = {"B2.2": "SL and HL in the guide; the workbook says HL only",
         "B3.1": "SL and HL in the guide; the workbook says HL only"}
TERM_ORDER = ["Yr 12 1.1", "Yr 12 1.2", "Yr 12 2.1", "Yr 12 2.2", "Yr 12 3.1", "Yr 12 3.2",
              "Yr 13 1.1", "Yr 13 1.2", "Yr 13 2.1", "Yr 13 2.2"]


def norm_term(v):
    t = re.sub(r"Yr\s*(\d+)", r"Yr \1", str(v or "").strip())
    return t or None


def parse_units(v, sid, issues):
    if v is None or str(v).strip() == "":
        issues.append({"id": sid, "problem": "No unit given"})
        return []
    if isinstance(v, (datetime.date, datetime.datetime)):
        issues.append({"id": sid, "problem": f"Unit shows as a date ({v:%d %b %Y}). Excel probably converted a list "
                                             f"such as \"{v.day},{v.month}\" or \"{v.month},{v.day}\". Please retype it "
                                             f"(format the cell as text first)."})
        return []
    out = []
    for p in re.split(r"[,;/ ]+", str(v)):
        if p.strip():
            try:
                out.append(int(float(p)))
            except ValueError:
                issues.append({"id": sid, "problem": f"Unit {v!r} is not a number"})
    return out


def main(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    statements, issues = [], []
    for strand in "ABC":
        ws = wb[f"Criteria {strand}"]
        for r in ws.iter_rows(min_row=2, values_only=True):
            # columns: code, level, (three numbering columns), description, term, unit
            code, level, desc, term = r[0], r[1], r[5], r[6]
            unit = r[7] if len(r) > 7 else None
            if not code or not re.fullmatch(r"\d+\.\d+\.\d+", str(code).strip()):
                continue   # blank rows and topic heading rows
            sid = f"{strand}{str(code).strip()}"
            topic = sid.rsplit(".", 1)[0]
            if topic not in TOPICS:
                issues.append({"id": sid, "problem": "Not a topic in the guide"})
                continue
            lv = "HL" if str(level).strip() == "HL" else "SL"
            if topic in FIXES and lv == "HL":
                lv = "SL"
            if (topic in HL_ONLY) != (lv == "HL"):
                issues.append({"id": sid, "problem": f"Level {level!r} disagrees with the guide"})
            t = norm_term(term)
            if t and t not in TERM_ORDER:
                issues.append({"id": sid, "problem": f"Unrecognized term {term!r}"})
            statements.append({"id": sid, "topic": topic, "topic_title": TOPICS[topic], "strand": strand,
                               "row": ROWS[topic[1]], "level": lv, "term": t,
                               "term_index": TERM_ORDER.index(t) if t in TERM_ORDER else None,
                               "units": parse_units(unit, sid, issues), "text": " ".join(str(desc or "").split())})
    command_terms = []
    for r in wb["Command Terms"].iter_rows(min_row=2, values_only=True):
        if r[0]:
            nums = [int(n) for n in re.findall(r"\d+", str(r[2]))]
            command_terms.append({"term": r[0].strip(), "ao": r[1].strip(),
                                  "marks": list(range(min(nums), max(nums) + 1)),
                                  "include": r[3], "pitfall": r[4]})
    out = {"source": Path(path).name, "terms": TERM_ORDER, "rows": ROWS, "strands": STRANDS, "topics": TOPICS,
           "corrections": FIXES, "statements": statements, "command_terms": command_terms}
    dest = ROOT / "site" / "data" / "dt"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "syllabus.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    (dest / "syllabus_review.json").write_text(json.dumps(issues, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(statements)} statements, {len(command_terms)} command terms, {len(issues)} issues")
    for i in issues:
        print(" ", i["id"], "-", i["problem"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / "source" / "syllabus" / "DT_IB_Strands.xlsx")
