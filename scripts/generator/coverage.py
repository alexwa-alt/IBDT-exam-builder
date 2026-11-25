"""What the bank already covers (handoff section 8.2), and the next target to write (section 8 step 1)."""
import datetime
import random
from collections import Counter
from pathlib import Path

import yaml

SL_TOPICS = ["A1.1", "A2.1", "A2.2", "A3.1", "B1.1", "B2.1", "B2.2", "B3.1",
             "C1.1", "C1.2", "C2.1", "C2.2", "C3.1"]


def load_bank(source):
    """All readable question.yaml files under source/questions, as dicts."""
    bank = []
    for qdir in sorted(p for p in (Path(source) / "questions").iterdir() if p.is_dir()):
        try:
            q = yaml.safe_load((qdir / "question.yaml").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a broken file is the build's problem, not ours
            continue
        if isinstance(q, dict):
            q.setdefault("id", qdir.name)
            bank.append(q)
    return bank


def statements_of(q):
    return sorted({s for p in q.get("parts", []) for s in p.get("syllabus", [])})


def coverage(bank, syl):
    """syl: {id: statement} from syllabus.json."""
    live = [q for q in bank if q.get("status") != "rejected"]
    cov = {"total": len(live), "marks": Counter(), "difficulty": Counter(), "topics": Counter(),
           "statements": Counter(), "early": 0, "refs": Counter(), "ids": {q["id"] for q in bank},
           "today": 0, "feedback": []}
    today = datetime.date.today().isoformat()
    for q in bank:
        src = q.get("source") or {}
        if src.get("generated_on") == today:
            cov["today"] += 1
        if q.get("status") == "rejected":
            for r in (q.get("review_history") or [])[-1:]:
                if r.get("reason"):
                    cov["feedback"].append(f"{q.get('title', q['id'])}: {r['reason']}")
            continue
        cov["marks"][q.get("marks")] += 1
        cov["difficulty"][q.get("difficulty")] += 1
        sts = statements_of(q)
        cov["statements"].update(sts)
        cov["topics"].update({s.rsplit(".", 1)[0] for s in sts})
        if sts and all(syl.get(s, {}).get("term_index") == 0 for s in sts):
            cov["early"] += 1
        if src.get("reference"):
            cov["refs"][src["reference"]] += 1
    return cov


def summary(cov):
    """A short plain summary (no question content) for logs."""
    return (f"{cov['total']} questions; marks {dict(cov['marks'])}; difficulty {dict(cov['difficulty'])}; "
            f"early Yr 12 {cov['early']}; topics {dict(sorted(cov['topics'].items()))}")


def _most_needed(counts, shares, total):
    return max(shares, key=lambda k: shares[k] * (total + 1) - counts.get(k, 0))


def choose_target(cov, syl, cfg, rng=None, marks=None, difficulty=None, statements=None):
    """Pick marks, difficulty and 2–4 statement ids, aiming at the bank's gaps. Explicit values win."""
    rng = rng or random.Random()
    shares = cfg["target_share"]
    total = cov["total"]
    marks = int(marks or _most_needed(cov["marks"], {int(k): v for k, v in shares["marks"].items()}, total))
    difficulty = int(difficulty or _most_needed(cov["difficulty"],
                                                {int(k): v for k, v in shares["difficulty"].items()}, total))
    sl = {sid: s for sid, s in syl.items() if s["level"] == "SL" and s["topic"] in SL_TOPICS}
    if statements:
        bad = [s for s in statements if s not in sl]
        if bad:
            raise ValueError(f"not SL statements: {', '.join(bad)}")
        sts = list(statements)
    else:
        early = cov["early"] < shares["early_year_12"] * (total + 1)
        pool = {sid: s for sid, s in sl.items() if not early or s["term_index"] == 0}
        topics = sorted({s["topic"] for s in pool.values()},
                        key=lambda t: (cov["topics"].get(t, 0), rng.random()))
        n_topics = 2 if marks == 6 else 3
        n_statements = rng.choice([2, 3]) if marks == 6 else rng.choice([3, 4])
        chosen_topics = topics[:1] + rng.sample(topics[1:6], min(n_topics - 1, len(topics[1:6])))
        sts = []
        for i in range(n_statements):
            t = chosen_topics[i % len(chosen_topics)]
            options = [sid for sid, s in pool.items() if s["topic"] == t and sid not in sts]
            if options:
                options.sort(key=lambda sid: (cov["statements"].get(sid, 0), rng.random()))
                sts.append(options[0])
    return {"marks": marks, "difficulty": difficulty, "statements": sorted(sts),
            "topics": sorted({s.rsplit(".", 1)[0] for s in sts})}


def choose_case_study(catalogue, target, cov, max_per_case, rng=None, reference=None):
    """Best-fitting case study with room for another question; unused ones first."""
    rng = rng or random.Random()
    if reference:
        hit = [c for c in catalogue if c["reference"] == reference]
        if not hit:
            raise ValueError(f"case study {reference} is not in the catalogue")
        return hit[0]
    ok = [c for c in catalogue if cov["refs"].get(c["reference"], 0) < max_per_case]
    if not ok:
        return None
    return max(ok, key=lambda c: (len(set(c.get("suits_topics", [])) & set(target["topics"])),
                                  -cov["refs"].get(c["reference"], 0), rng.random()))
