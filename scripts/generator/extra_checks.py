"""Checks for AI-written questions, on top of build_bank.check() (handoff section 9.3).

These are stricter than the nightly build: a hand-written question may break them for a good reason, but a
generated draft that breaks them goes back to Gemini to be fixed.
"""
import re

PATTERNS = {6: [[1, 2, 3], [1, 1, 2, 2]], 10: [[2, 2, 2, 4], [1, 2, 3, 4]]}
WORDS = {6: (120, 250), 10: (200, 350)}
JUDGEMENT = {"Evaluate", "Analyse", "Justify"}
BANNED_TERMS = {"Discuss", "Determine"}
DATA_NOTE = "data written for this practice paper"


def plain(t):
    return re.sub(r"<[^>]+>", "", str(t)).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def stimulus_words(q):
    n = 0
    for b in q["stimulus"]:
        if "text" in b:
            n += len(plain(b["text"]).split())
        elif "bullets" in b:
            n += sum(len(plain(x).split()) for x in b["bullets"])
    return n


def check(q, used_refs=None, max_per_case=2, used_ids=()):
    """Returns a list of error strings (empty = passes)."""
    errors = []
    marks = q.get("marks")
    parts = q.get("parts", [])
    pattern = [p["marks"] for p in parts]
    if marks in PATTERNS and pattern not in PATTERNS[marks]:
        allowed = " or ".join("+".join(map(str, x)) for x in PATTERNS[marks])
        errors.append(f"mark pattern {'+'.join(map(str, pattern))} is not {allowed}")
    if marks == 10 and parts and (parts[-1]["marks"] != 4 or parts[-1]["command_term"] not in JUDGEMENT):
        errors.append("the last part of a 10-mark question must be a 4-mark Evaluate, Analyse or Justify")
    labels = [p["label"] for p in parts]
    if labels != [chr(ord("a") + i) for i in range(len(parts))]:
        errors.append(f"part labels {labels} should be a, b, c… in order")
    for p in parts:
        if p["command_term"] in BANNED_TERMS:
            errors.append(f"part ({p['label']}): '{p['command_term']}' is not allowed")
        if len(p.get("answers", [])) <= p["marks"]:
            errors.append(f"part ({p['label']}): give more marking points than marks "
                          f"({len(p.get('answers', []))} points for [{p['marks']}])")
        if p["marks"] >= 3 and p["command_term"] in JUDGEMENT | {"Explain"} and "[" not in p.get("notes", ""):
            errors.append(f"part ({p['label']}): notes must say how marks are awarded, e.g. 'Award [1] for…'")
        if p["command_term"] == "Evaluate":
            joined = " ".join(p["answers"])
            if not all(k in joined for k in ("Strength", "Limitation", "Conclusion")):
                errors.append(f"part ({p['label']}): Evaluate answers need Strength:, Limitation: and Conclusion: points")

    # Tables and figures: numbered 1, 2, … in order, and each one referred to in some part.
    questions_text = " ".join(plain(p["question"]) for p in parts)
    for kind, key in (("Table", "table"), ("Figure", "figure")):
        caps = []
        for b in q["stimulus"]:
            if key == "table" and "table" in b:
                caps.append(b["table"].get("caption", ""))
            elif key == "figure" and "figure" in b:
                caps.append(b.get("caption", ""))
        nums = []
        for c in caps:
            m = re.match(rf"\s*{kind}\s+(\d+)\s*:", plain(c))
            if not m:
                errors.append(f"{kind.lower()} caption {plain(c)!r} should start '{kind} n: '")
            else:
                nums.append(int(m.group(1)))
        if nums and nums != list(range(1, len(nums) + 1)):
            errors.append(f"{kind}s are numbered {nums}; number them 1, 2, … in order")
        for n in nums:
            if not re.search(rf"\b{kind}\s+{n}\b", questions_text):
                errors.append(f"{kind} {n} is not referred to in any part")
        for n in {int(x) for x in re.findall(rf"\b{kind}\s+(\d+)", questions_text)} - set(nums):
            errors.append(f"a part refers to {kind} {n}, which does not exist")

    tables = [b for b in q["stimulus"] if "table" in b]
    if not tables:
        errors.append("add at least one data table (generated questions have no pictures)")
    else:
        notes = " ".join(plain(b["note"]).lower() for b in q["stimulus"] if "note" in b)
        if DATA_NOTE not in notes:
            errors.append("end the stimulus with the note 'Data written for this practice paper.'")
    if q.get("difficulty") == 3 and not any(re.search(r"\bTable\s+\d", plain(p["question"])) and p["marks"] >= 2
                                            for p in parts):
        errors.append("difficulty 3 needs a part worth [2] or more that uses data from a table")

    if marks in WORDS:
        lo, hi = WORDS[marks]
        n = stimulus_words(q)
        if not lo <= n <= hi:
            errors.append(f"stimulus text is {n} words; aim for {lo}–{hi} for a {marks}-mark question")

    if q.get("id") in used_ids:
        errors.append(f"id {q.get('id')!r} is already in the bank")
    ref = (q.get("source") or {}).get("reference")
    if ref and used_refs is not None and used_refs.get(ref, 0) >= max_per_case:
        errors.append(f"case study {ref} already has {used_refs[ref]} question(s)")
    return errors
