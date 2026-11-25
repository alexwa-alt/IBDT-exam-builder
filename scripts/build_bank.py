"""Build the DT question bank from the source folder.

For every source/questions/<id>/question.yaml it:
  1. checks the question against the syllabus, the command terms and the specimen format;
  2. draws the question (stimulus, parts and answer lines) and its markscheme as PNG page images,
     in the shape the site's paper builder already uses (pages / ms lists with sizes in mm);
  3. writes build/data/questions.json, tags.json and review.json.

Questions with errors are left out and listed in review.json. Nothing here is encrypted; the
encrypt step (a later milestone) turns build/ into the public site.

Usage: python scripts/build_bank.py [--source source] [--out build] [--only <id>]
"""
import argparse
import io
import json
import re
import shutil
import sys
from pathlib import Path

import pymupdf as fitz  # PyMuPDF, renders PDF pages to images
import yaml
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.fonts import addMapping
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, Image, KeepTogether, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
for name, file in [("Arial", "LiberationSans-Regular"), ("Arial-Bold", "LiberationSans-Bold"),
                   ("Arial-Italic", "LiberationSans-Italic"), ("Arial-BoldItalic", "LiberationSans-BoldItalic"),
                   ("DejaVu", "DejaVuSans")]:
    pdfmetrics.registerFont(TTFont(name, str(FONTS / f"{file}.ttf")))
addMapping("Arial", 0, 0, "Arial"); addMapping("Arial", 1, 0, "Arial-Bold")
addMapping("Arial", 0, 1, "Arial-Italic"); addMapping("Arial", 1, 1, "Arial-BoldItalic")

# Page geometry must match site/paper.js: question images sit beside a 13 mm number column.
Q_W, MS_W, PAGE_H = 161 * mm, 174 * mm, 257 * mm
DPI = 150

BODY = ParagraphStyle("body", fontName="Arial", fontSize=10.5, leading=14, spaceAfter=6)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8.5, leading=11, textColor=colors.HexColor("#333333"))
CAP = ParagraphStyle("cap", parent=BODY, spaceBefore=4, spaceAfter=4)
SRC = ParagraphStyle("src", parent=SMALL, alignment=TA_CENTER, fontSize=7.5, spaceBefore=2)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=9.5, leading=12, spaceAfter=0)
RIGHT = ParagraphStyle("right", parent=BODY, alignment=TA_RIGHT)
TICK = ' <font name="DejaVu">\u2713</font>'

# Command terms and mark values seen in the specimen SL Paper 2, allowed alongside the department's list.
SPECIMEN_TERMS = {"State": {1, 2}, "Identify": {1, 2}, "List": {2}, "Outline": {2}, "Describe": {2},
                  "Explain": {3, 4}, "Justify": {3}, "Analyse": {3, 4}, "Evaluate": {3, 4}, "Present": {2}}
SPECIMEN_AO = {"Present": "AO2"}
SL_P2 = {"question_marks": {6, 10}, "max_part": 4}
HL_TERMS = ["gear", "lever", "pulley", "linkage", "cam follower", "young\u2019s modulus", "young's modulus",
            "safety factor", "factor of safety", "four-pleasure", "attract/converse", "act model", "life-cycle analysis",
            "life cycle analysis", "cradle-to-grave", "injection mould", "blow mould", "rotational mould", "extrusion",
            "casting", "production system", "mass production", "batch production", "design for assembly",
            "design for manufacture", "design for process", "op-amp", "microcontroller", "transistor", "cantilever",
            "stress-strain", "yield strength", "internet of things", "4d print", "welding", "welded"]
OLD_TERMS = ["rogers", "product champion", "entrepreneur", "inventor", "sustaining innovation", "disruptive",
             "process innovation", "end-of-pipe", "converging technolog", "conceptual model", "instrumented model",
             "eco-design", "maturity", "green legislation", "design for materials", "technology push", "market pull",
             "eco-label", "radical innovation", "incremental innovation", "dominant design", "ashby", "poka-yoke"]


# ---------------------------------------------------------------- drawing helpers
class Lines(Flowable):
    """Dotted answer lines: two per mark, as in the specimen."""
    def __init__(self, n, width, gap=8.5 * mm):
        super().__init__(); self.n, self.w, self.gap = n, width, gap
    def wrap(self, aw, ah): return self.w, self.n * self.gap + 2 * mm
    def draw(self):
        c = self.canv; c.setDash(1, 2.2); c.setLineWidth(0.6); c.setStrokeColor(colors.HexColor("#555555"))
        for i in range(self.n):
            y = self.n * self.gap - (i + 1) * self.gap + 2 * mm
            c.line(10 * mm, y, self.w, y)


def img(path, width_mm):
    w, h = PILImage.open(path).size
    width = min(width_mm * mm, Q_W)
    return Image(str(path), width=width, height=width * h / w)


def grid_table(rows, widths_mm, header=True):
    data = [[Paragraph(str(c), CELL) for c in r] for r in rows]
    scale = min(1.0, Q_W / (sum(widths_mm) * mm))       # never wider than the answer area
    t = Table(data, colWidths=[w * mm * scale for w in widths_mm], hAlign="LEFT")
    st = [("GRID", (0, 0), (-1, -1), 0.6, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")))
    t.setStyle(TableStyle(st))
    return t


def indent(style, mm_):
    return ParagraphStyle(style.name + "i", parent=style, leftIndent=mm_ * mm)


def question_story(q, qdir):
    s = []
    for b in q["stimulus"]:
        if "text" in b:
            s.append(Paragraph(b["text"], BODY))
        elif "note" in b:
            s.append(Paragraph(b["note"], SMALL))
        elif "bullets" in b:
            for t in b["bullets"]:
                s.append(Paragraph(t, ParagraphStyle("bl", parent=BODY, leftIndent=6 * mm, bulletIndent=2 * mm,
                                                     spaceAfter=2), bulletText="\u2022"))
            s.append(Spacer(1, 3 * mm))
        elif "table" in b:
            t = b["table"]
            s.append(KeepTogether([Paragraph(t["caption"], CAP), grid_table(t["rows"], t["widths_mm"],
                                   t.get("header", True)), Spacer(1, 4 * mm)]))
        elif "figure" in b:
            block = [Paragraph(b["caption"], CAP), img(qdir / b["figure"], b.get("width_mm", 120))]
            if b.get("credit"):
                block.append(Paragraph(f"[Source: {b['credit']}]", SRC))
            s.append(KeepTogether(block + [Spacer(1, 4 * mm)]))
    for p in q["parts"]:
        t = Table([[Paragraph(f"({p['label']})", BODY), Paragraph(p["question"], BODY),
                    Paragraph(f"[{p['marks']}]", RIGHT)]], colWidths=[10 * mm, Q_W - 26 * mm, 16 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        s.append(KeepTogether([Spacer(1, 3 * mm), t, Lines(p["marks"] * 2, Q_W), Spacer(1, 2 * mm)]))
    return s


def markscheme_story(q):
    hdr = [Paragraph(f"<b>{h}</b>", CELL) for h in ("Part", "Answers", "Notes", "Total")]
    rows = [hdr]
    for p in q["parts"]:
        rows.append([Paragraph(f"({p['label']})", CELL),
                     [Paragraph(a + TICK, CELL, bulletText="\u2022") for a in p["answers"]],
                     Paragraph(p["notes"], CELL),
                     Paragraph(str(p["marks"]), ParagraphStyle("c", parent=CELL, alignment=TA_CENTER))])
    t = Table(rows, colWidths=[12 * mm, 88 * mm, MS_W - 116 * mm, 16 * mm], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return [t, Spacer(1, 2 * mm), Paragraph(f"<b>Total: [{q['marks']}]</b>", RIGHT)]


def render(story, width):
    """Lay the story out on pages of the given width, then return cropped PNG pages."""
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=(width, PAGE_H), leftMargin=0, rightMargin=0, topMargin=0, bottomMargin=0)
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(0, 0, width, PAGE_H, id="f", leftPadding=0,
                                                              rightPadding=0, topPadding=0, bottomPadding=0)])])
    doc.build(story)
    pages = []
    pdf = fitz.open(stream=buf.getvalue(), filetype="pdf")
    for page in pdf:
        pix = page.get_pixmap(dpi=DPI)
        im = PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)
        bbox = PILImage.eval(im.convert("L"), lambda v: 255 - v).getbbox()
        bottom = min(im.height, (bbox[3] if bbox else 1) + int(2 * DPI / 25.4))
        im = im.crop((0, 0, im.width, bottom))
        pages.append(im)
    return pages


# ---------------------------------------------------------------- checks
def plain(t):
    return re.sub(r"<[^>]+>", "", str(t))


def check(q, qdir, syl, cts):
    errors, warnings = [], []
    for f in ("id", "title", "level", "paper", "marks", "difficulty", "status", "stimulus", "parts"):
        if f not in q:
            errors.append(f"missing field {f!r}")
    if errors:
        return errors, warnings
    if q["id"] != qdir.name:
        errors.append(f"id {q['id']!r} does not match folder name {qdir.name!r}")
    total = sum(p["marks"] for p in q["parts"])
    if total != q["marks"]:
        errors.append(f"parts add up to {total}, not {q['marks']}")
    if q["level"] == "SL" and q["paper"] == 2:
        if q["marks"] not in SL_P2["question_marks"]:
            errors.append(f"SL Paper 2 questions are worth 6 or 10 marks, not {q['marks']}")
        for p in q["parts"]:
            if p["marks"] > SL_P2["max_part"]:
                errors.append(f"part ({p['label']}) is worth {p['marks']}; SL Paper 2 parts are at most [4]")
    for p in q["parts"]:
        ct, m = p.get("command_term"), p.get("marks")
        allowed = set(cts.get(ct, {}).get("marks", [])) | SPECIMEN_TERMS.get(ct, set())
        if ct not in cts and ct not in SPECIMEN_TERMS:
            errors.append(f"part ({p['label']}): command term {ct!r} is not in the department list or the specimen")
        elif m not in allowed:
            warnings.append(f"part ({p['label']}): {ct} [{m}] is outside the usual marks {sorted(allowed)}")
        words = plain(p["question"]).split()
        first = words[0] if words else ""
        if first == "Using":
            first = plain(p["question"]).split(",", 1)[-1].split()[0].capitalize()
        if first != ct:
            errors.append(f"part ({p['label']}): wording starts with {first!r} but the command term is {ct!r}")
        for sid in p.get("syllabus", []):
            st = syl.get(sid)
            if not st:
                errors.append(f"part ({p['label']}): syllabus statement {sid} does not exist")
            elif q["level"] == "SL" and st["level"] == "HL":
                errors.append(f"part ({p['label']}): {sid} is HL only")
        if not p.get("syllabus"):
            errors.append(f"part ({p['label']}): no syllabus statements")
        if not p.get("answers"):
            errors.append(f"part ({p['label']}): no markscheme answers")
    for b in q["stimulus"]:
        if "figure" in b and not (qdir / b["figure"]).exists():
            errors.append(f"figure file {b['figure']} is missing")
    text = plain(json.dumps(q, ensure_ascii=False)).lower()
    if q["level"] == "SL":
        found = [t for t in HL_TERMS if re.search(r"\b" + re.escape(t), text)]
        if found:
            errors.append(f"HL-only terms in an SL question: {', '.join(found)}")
    found = [t for t in OLD_TERMS if re.search(r"\b" + re.escape(t), text)]
    if found:
        errors.append(f"old-syllabus terms: {', '.join(found)}")
    return errors, warnings


def write_review_pack(pack, path):
    """One A4 PDF of every rendered question and markscheme, for staff to review and comment on in Drive."""
    doc = fitz.open()
    pw, ph = 595.3, 841.9          # A4 in points
    margin, y, page, current = 36.0, None, None, None
    for q, kind, im in pack:
        w_pt = im.width * 72 / DPI
        h_pt = im.height * 72 / DPI
        scale = min(1.0, (pw - 2 * margin) / w_pt)
        w_pt, h_pt = w_pt * scale, h_pt * scale
        new_q = current != (q["id"], kind)
        if page is None or new_q or y + h_pt > ph - margin:
            page = doc.new_page(width=pw, height=ph)
            y = margin
            if new_q:
                label = (f"{q['title']}  \u2013  {q['marks']} marks  \u2013  {q['status']}  \u2013  id: {q['id']}"
                         if kind == "q" else f"Markscheme: {q['title']}")
                page.insert_text((margin, y + 10), label, fontsize=10, fontname="helv")
                y += 22
            current = (q["id"], kind)
        b = io.BytesIO(); im.convert("RGB").save(b, format="JPEG", quality=72, optimize=True)  # keeps the pack small
        page.insert_image(fitz.Rect(margin, y, margin + w_pt, y + h_pt), stream=b.getvalue())
        y += h_pt + 8
    if len(doc):
        doc.save(str(path), deflate=True)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(ROOT / "source"))
    ap.add_argument("--out", default=str(ROOT / "build"))
    ap.add_argument("--only")
    args = ap.parse_args()
    src, out = Path(args.source), Path(args.out)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    sylfile = ROOT / "site" / "data" / "dt" / "syllabus.json"
    sy = json.loads(sylfile.read_text(encoding="utf-8"))
    syl = {s["id"]: s for s in sy["statements"]}
    cts = {c["term"]: c for c in sy["command_terms"]}

    if out.exists() and not args.only:
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy(sylfile, out / "data" / "syllabus.json")

    (out / "review_only").mkdir(parents=True, exist_ok=True)
    questions, tags, review, pack = [], {}, [], []
    for qdir in sorted(p for p in (src / "questions").iterdir() if p.is_dir()):
        if args.only and qdir.name != args.only:
            continue
        try:
            q = yaml.safe_load((qdir / "question.yaml").read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 - report any YAML problem
            review.append({"id": qdir.name, "errors": [f"could not read question.yaml: {e}"], "warnings": []})
            continue
        errors, warnings = check(q, qdir, syl, cts)
        if q.get("status") not in cfg["publish_statuses"]:
            warnings.append(f"status {q.get('status')!r} is not published (publish_statuses in config.yaml)")
        if q.get("figure_rights") == "past-paper" and not cfg["include_past_paper_figures"]:
            warnings.append("left out: uses past-paper figures and include_past_paper_figures is false")
        if errors or warnings:
            review.append({"id": qdir.name, "errors": errors, "warnings": warnings})
        if errors:
            continue
        on_site = q.get("status") in cfg["publish_statuses"] and \
            (q.get("figure_rights") != "past-paper" or cfg["include_past_paper_figures"])

        def save(pages, kind):
            items = []
            for k, im in enumerate(pages, 1):
                name = f"{q['id']}_{kind}{k}.png"
                im.save((out / "images" if on_site else out / "review_only") / name, optimize=True)
                pack.append((q, kind, im))
                items.append({"image": f"images/{name}", "w_mm": round(im.width * 25.4 / DPI, 1),
                              "h_mm": round(im.height * 25.4 / DPI, 1)})
            return items

        try:   # a drawing error (usually bad <b>/<i> markup or a bare &) leaves out this question only
            q_pages, ms_pages = render(question_story(q, qdir), Q_W), render(markscheme_story(q), MS_W)
        except Exception as e:  # noqa: BLE001 - report any rendering problem against the question
            reason = " ".join(str(e).split())[:300]
            entry = next((r for r in review if r["id"] == qdir.name), None)
            if entry is None:
                entry = {"id": qdir.name, "errors": [], "warnings": []}
                review.append(entry)
            entry["errors"].append("could not be drawn; check that every <b>, <i>, <super> and <sub> tag is "
                                   f"closed and that & is written &amp; ({reason})")
            continue
        pages = save(q_pages, "q")
        ms = save(ms_pages, "ms")
        if not on_site:
            print(f"rendered {q['id']} for the review pack only")
            continue
        statements = sorted({s for p in q["parts"] for s in p["syllabus"]})
        topics = sorted({syl[s]["topic"] for s in statements})
        ao = {}
        for p in q["parts"]:
            a = cts.get(p["command_term"], {}).get("ao") or SPECIMEN_AO.get(p["command_term"], "AO2")
            ao[a] = ao.get(a, 0) + p["marks"]
        taught = [syl[s]["term_index"] for s in statements if syl[s]["term_index"] is not None]
        questions.append({"id": q["id"], "title": q["title"], "level": q["level"], "paper": q["paper"],
                          "pages": pages, "ms": ms, "ms_status": "ok",
                          "source": q.get("source", {}), "figure_rights": q.get("figure_rights", "original")})
        tags[q["id"]] = {
            "status": q["status"], "marks": q["marks"], "difficulty": q["difficulty"],
            "statements": statements, "topics": topics,
            "rows": sorted({syl[s]["row"] for s in statements}),
            "command_terms": sorted({p["command_term"] for p in q["parts"]}),
            "ao_marks": ao,
            "taught_by": max(taught) if taught else None,   # index into syllabus.terms
            "generated": (q.get("source") or {}).get("generated_by"),   # e.g. "gemini" for AI-written drafts
            "review": (q.get("review_history") or [None])[-1],         # latest website review decision
            "units": sorted({u for s in statements for u in syl[s]["units"]}),
            "text": " ".join([q["title"]] + [plain(b.get("text", "")) for b in q["stimulus"]] +
                             [plain(p["question"]) for p in q["parts"]]),
        }
        print(f"built {q['id']}: {len(pages)} question page(s), {len(ms)} markscheme page(s)")

    write_review_pack(pack, out / "review_pack.pdf")
    (out / "data" / "questions.json").write_text(json.dumps(questions, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "data" / "tags.json").write_text(json.dumps(tags, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "data" / "review.json").write_text(json.dumps(review, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(questions)} questions built; {sum(1 for r in review if r['errors'])} with errors "
          f"(see {out / 'data' / 'review.json'})")
    for r in review:
        for e in r["errors"]:
            print(f"  ERROR {r['id']}: {e}")
        for w in r["warnings"]:
            print(f"  note  {r['id']}: {w}")
    return 1 if any(r["errors"] for r in review) else 0


if __name__ == "__main__":
    sys.exit(main())
