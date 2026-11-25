"""Turn Gemini's Draft (schema.py) into a question.yaml dictionary and YAML text, following FORMAT.md.

Code, not Gemini, writes the YAML, so quoting, markup escaping and table widths are always right.
"""
import datetime
import re

import yaml

ALLOWED_TAGS = ("b", "i", "super", "sub")
TEXT_WIDTH_MM = 161
TAG_RE = re.compile(r"</?(?:%s)>" % "|".join(ALLOWED_TAGS))


def clean(text):
    """Escape & and < > that are not part of the allowed markup; tidy spaces; map sup -> super."""
    t = " ".join(str(text or "").split())
    t = re.sub(r"<(/?)sup>", r"<\1super>", t)
    t = re.sub(r"&(?!(?:amp|lt|gt|quot|#\d+);)", "&amp;", t)
    out, pos = [], 0
    for m in TAG_RE.finditer(t):
        out.append(t[pos:m.start()].replace("<", "&lt;").replace(">", "&gt;"))
        out.append(m.group(0))
        pos = m.end()
    out.append(t[pos:].replace("<", "&lt;").replace(">", "&gt;"))
    return "".join(out)


def plain_len(text):
    return len(re.sub(r"<[^>]+>|&\w+;", "x", text))


def table_widths(rows, total=TEXT_WIDTH_MM):
    """Column widths in mm from the longest cell in each column (header counts less), summing to <= total."""
    cols = max(len(r) for r in rows)
    weights = []
    for c in range(cols):
        cells = [plain_len(r[c]) if c < len(r) else 0 for r in rows]
        longest = max(cells[1:] or [0])
        weights.append(min(60, max(6, longest, cells[0] * 0.6)))
    natural = sum(w * 2.2 + 6 for w in weights)        # about 2.2 mm per character plus padding
    width = min(total, max(natural, 30 * cols))
    widths = [round(width * w / sum(weights)) for w in weights]
    widths = [max(12, w) for w in widths]
    while sum(widths) > total:                          # minimums may push past the page width
        i = widths.index(max(widths))
        widths[i] -= sum(widths) - total
    return widths


def unique_id(title, used):
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "question"
    qid, n = base, 2
    while qid in used:
        qid, n = f"{base}-{n}", n + 1
    return qid


def to_question(draft, qid, *, target, case_study, model):
    """draft: schema.Draft (or a dict of the same shape). Returns a dict in FORMAT.md order."""
    d = draft if isinstance(draft, dict) else draft.model_dump()
    stimulus = []
    for b in d["stimulus"]:
        kind = b.get("kind")
        if kind == "text" and b.get("text"):
            stimulus.append({"text": clean(b["text"])})
        elif kind == "note" and b.get("text"):
            stimulus.append({"note": clean(b["text"])})
        elif kind == "bullets" and b.get("bullets"):
            stimulus.append({"bullets": [clean(x) for x in b["bullets"]]})
        elif kind == "table" and b.get("table_rows"):
            rows = [[clean(c) for c in r] for r in b["table_rows"] if r]
            n = max(len(r) for r in rows)
            rows = [r + [""] * (n - len(r)) for r in rows]
            stimulus.append({"table": {"caption": clean(b.get("table_caption") or ""),
                                       "widths_mm": table_widths(rows), "rows": rows}})
    parts = []
    for p in d["parts"]:
        parts.append({"label": str(p["label"]).strip("() ").lower(), "marks": int(p["marks"]),
                      "command_term": p["command_term"].strip().capitalize(),
                      "syllabus": [s.strip() for s in p["syllabus"]],
                      "question": clean(p["question"]), "answers": [clean(a) for a in p["answers"]],
                      "notes": clean(p["notes"])})
    if case_study:
        source = {"type": "past-paper case study", "reference": case_study["reference"]}
    else:
        source = {"type": "original"}
    note = clean(d.get("source_note") or "")
    if d.get("past_paper_images"):
        note += " Past-paper images that could be added: " + clean(d["past_paper_images"])
    source["note"] = note.strip()
    source["generated_by"] = "gemini"
    source["generated_on"] = datetime.date.today().isoformat()
    source["model"] = model
    source["target"] = {"statements": target["statements"], "marks": target["marks"],
                        "difficulty": target["difficulty"]}
    return {"id": qid, "title": clean(d["title"]), "level": "SL", "paper": 2, "marks": int(d["marks"]),
            "difficulty": int(d["difficulty"]), "status": "draft", "source": source,
            "figure_rights": "original", "stimulus": stimulus, "parts": parts}


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper, s):
    style = ">" if len(s) > 90 and "\n" not in s and s == s.strip() else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style=style)


def _list(dumper, items):
    """Short lists of plain values on one line ([A1.1.3, B1.1.2]); everything else as a block list."""
    flow = all(isinstance(x, (str, int)) and len(str(x)) < 40 for x in items) and len(str(items)) < 100
    return dumper.represent_sequence("tag:yaml.org,2002:seq", items, flow_style=flow)


_Dumper.add_representer(str, _str)
_Dumper.add_representer(list, _list)


def to_yaml(q):
    """YAML text that reads back to exactly q (checked); folded >- blocks for long text where safe."""
    text = yaml.dump(q, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=110, default_flow_style=False)
    if yaml.safe_load(text) != q:   # never trust the pretty form blindly
        text = yaml.safe_dump(q, sort_keys=False, allow_unicode=True, width=110)
    assert yaml.safe_load(text) == q
    return text
