"""Write new SL Paper 2 practice questions with Gemini and add them to the bank as drafts.

For each question:
  1. work out what the bank is short of (coverage.py) and pick a target and a past-paper case study;
  2. ask Gemini (writer prompt) for the question as JSON (schema.py), and turn it into question.yaml (convert.py);
  3. check it with the nightly build's checker, the stricter extra_checks.py, and a trial drawing;
     problems go back to Gemini to fix (up to `repair_attempts` times);
  4. ask Gemini again, as a demanding reviewer; if it fails, one revision, then it must pass review again;
  5. upload questions/<id>/question.yaml to Drive (status: draft), or write it locally with --dry-run.

Public output (the Actions log is public) is limited to ids, targets and pass/fail. Full prompts, replies and
reviewer comments go to a private log file in Drive generation-log/ (or --out with --dry-run).

Usage:
  python scripts/generator/generate.py [--count 1] [--marks 6|10] [--difficulty 1|2|3]
                                       [--statements A1.1.3,B2.1.4] [--case-study 26M.2.SL.TZ1.6]
                                       [--request <encrypted request from the site>]
                                       [--source local-source] [--catalogue case_studies.json]
                                       [--dry-run --out drafts-out]
"""
import argparse
import datetime
import json
import os
import random
import sys
import tempfile
import traceback
from pathlib import Path
from string import Template

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import convert  # noqa: E402
import coverage  # noqa: E402
import extra_checks  # noqa: E402
from schema import Draft, Review  # noqa: E402

PROMPTS = HERE / "prompts"


def say(msg):
    """Public progress line (Actions log). Never pass question content to this."""
    print(msg, flush=True)


def summary(line):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ------------------------------------------------------------------ checking
def load_syllabus(source):
    import syllabus_import
    xlsx = Path(source) / "syllabus" / "DT_IB_Strands.xlsx"
    if xlsx.exists():
        syllabus_import.main(xlsx)
    sy = json.loads((ROOT / "site" / "data" / "dt" / "syllabus.json").read_text(encoding="utf-8"))
    return {s["id"]: s for s in sy["statements"]}, {c["term"]: c for c in sy["command_terms"]}


def validate(q, syl, cts, cov, cfg):
    """All the problems with question dict q (empty list = passes). Includes a trial drawing."""
    import build_bank
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp) / q["id"]
        qdir.mkdir()
        (qdir / "question.yaml").write_text(convert.to_yaml(q), encoding="utf-8")
        q2 = yaml.safe_load((qdir / "question.yaml").read_text(encoding="utf-8"))
        errors, _warnings = build_bank.check(q2, qdir, syl, cts)
        errors += extra_checks.check(q2, cov["refs"], cfg["max_questions_per_case_study"], cov["ids"])
        try:
            build_bank.render(build_bank.question_story(q2, qdir), build_bank.Q_W)
            build_bank.render(build_bank.markscheme_story(q2), build_bank.MS_W)
        except Exception as e:  # noqa: BLE001
            errors.append(f"the question could not be drawn (check markup): {' '.join(str(e).split())[:200]}")
    return errors


# ------------------------------------------------------------------ prompts
def statements_block(ids, syl):
    return "\n".join(f"- {s} ({syl[s]['topic']} {syl[s]['topic_title']}): {syl[s]['text']}" for s in ids)


def case_study_block(cs, bank):
    if not cs:
        return ("No unused past-paper case study is left. Invent a realistic, plausible product context (not a "
                "real brand) and start source_note with 'Fictional context written for this practice paper.'")
    same = [q for q in bank if (q.get("source") or {}).get("reference") == cs["reference"]]
    lines = [f"Base it on this case study from an old-syllabus IB past paper ({cs['reference']}, {cs['product']}). "
             "Keep the real product facts, rewrite the text in the specimen style (removing any banned words), and "
             "write completely new parts aimed at the 2027 syllabus.",
             "", "CASE STUDY TEXT", cs.get("text", ""), "", "DATA IN THE ORIGINAL", cs.get("data") or "none",
             "", "THE ORIGINAL QUESTIONS (do not reuse them)"] + [f"- {x}" for x in cs.get("original_questions", [])]
    if same:
        lines += ["", "QUESTIONS ALREADY IN THE BANK ON THIS CASE STUDY (take a different angle; do not repeat them)"]
        for q in same:
            lines += [f"- {q.get('title')}: " + " | ".join(p.get("question", "") for p in q.get("parts", []))]
    return "\n".join(lines)


def writer_prompt(target, cs, bank, cov, syl, exemplars):
    figs = (cs or {}).get("figures") or []
    images = ("Past-paper images for this case study (you cannot include them; if one would help, name it and its "
              "page in past_paper_images): " + "; ".join(f"{f['caption']} (page {f['page']})" for f in figs)
              ) if figs else ""
    avoid = ("DO NOT REUSE these ids: " + ", ".join(sorted(cov["ids"])))
    feedback = ""
    if cov["feedback"]:
        feedback = ("REVIEWERS REJECTED THESE EARLIER DRAFTS; AVOID THE SAME PROBLEMS\n" +
                    "\n".join(f"- {f}" for f in cov["feedback"][-15:]))
    return Template((PROMPTS / "writer.md").read_text(encoding="utf-8")).substitute(
        marks=target["marks"], difficulty=target["difficulty"],
        statements=statements_block(target["statements"], syl), case_study_block=case_study_block(cs, bank),
        images_line=images, rules=(PROMPTS / "rules.md").read_text(encoding="utf-8"),
        quality=(PROMPTS / "quality.md").read_text(encoding="utf-8"), avoid_block=avoid,
        feedback_block=feedback, exemplars=exemplars or "(none available)")


def reviewer_prompt(q, target, syl):
    return Template((PROMPTS / "reviewer.md").read_text(encoding="utf-8")).substitute(
        marks=target["marks"], difficulty=target["difficulty"], statement_ids=", ".join(target["statements"]),
        statements=statements_block(target["statements"], syl),
        rules=(PROMPTS / "rules.md").read_text(encoding="utf-8"),
        quality=(PROMPTS / "quality.md").read_text(encoding="utf-8"), draft=convert.to_yaml(q))


def fix_prompt(base, q, problems, fixes=None):
    text = [base, "", "YOUR PREVIOUS DRAFT (as YAML)", convert.to_yaml(q), "", "PROBLEMS TO FIX"]
    text += [f"- {p}" for p in problems]
    if fixes:
        text += ["", "SUGGESTED FIXES"] + [f"- {f}" for f in fixes]
    text += ["", "Return the complete corrected question as JSON matching the schema."]
    return "\n".join(text)


# ------------------------------------------------------------------ one question
def write_one(gem, target, cs, bank, cov, syl, cts, cfg, exemplars, attachments, log):
    base = writer_prompt(target, cs, bank, cov, syl, exemplars)
    qid_holder = {}

    def as_question(draft):
        if "id" not in qid_holder:
            qid_holder["id"] = convert.unique_id(draft.title, cov["ids"])
        return convert.to_question(draft, qid_holder["id"], target=target, case_study=cs, model=gem.model)

    # The specimen PDFs go with the first writer call only: repairs and revisions already have the draft (in the
    # specimen style) to work from, and leaving the PDFs out makes those calls much cheaper.
    def draft_until_valid(prompt, first=False):
        draft = gem.ask((attachments if first else []) + [prompt], Draft)
        q = as_question(draft)
        for attempt in range(cfg["repair_attempts"] + 1):
            errors = validate(q, syl, cts, cov, cfg)
            log["steps"].append({"step": "check", "errors": errors})
            if not errors:
                return q
            if attempt == cfg["repair_attempts"]:
                break
            q = as_question(gem.ask([fix_prompt(base, q, errors)], Draft))
        log["last_draft"] = convert.to_yaml(q)
        return None

    q = draft_until_valid(base, first=True)
    if not q:
        return None, "failed the checks"
    for round_ in range(2):
        review = gem.ask([reviewer_prompt(q, target, syl)], Review, temperature=0.2)
        log["steps"].append({"step": "review", "passed": review.passed, "problems": review.problems,
                             "fixes": review.fixes})
        if review.passed:
            return q, "passed"
        if round_ == 1:
            break
        revised = draft_until_valid(fix_prompt(base, q, review.problems, review.fixes))
        if not revised:
            return None, "revision failed the checks"
        q = revised
    log["last_draft"] = convert.to_yaml(q)
    return None, "failed review"


# ------------------------------------------------------------------ main
def options_from_request(args):
    from request_crypto import open_request
    req = open_request(args.request, "generate")
    args.count = int(req.get("count") or 1)
    args.marks = req.get("marks") or None
    args.difficulty = req.get("difficulty") or None
    args.statements = req.get("statements") or None
    args.case_study = req.get("case_study") or None
    return req.get("by") or "the website"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--marks", type=int, choices=[6, 10])
    ap.add_argument("--difficulty", type=int, choices=[1, 2, 3])
    ap.add_argument("--statements", help="comma-separated statement ids")
    ap.add_argument("--case-study", help="past-paper reference, e.g. 26M.2.SL.TZ1.6")
    ap.add_argument("--request", help="encrypted request from the staff site")
    ap.add_argument("--source", help="local copy of the bank folder (default: download from Drive)")
    ap.add_argument("--catalogue", help="local case_studies.json (default: reference/ in Drive)")
    ap.add_argument("--dry-run", action="store_true", help="write drafts to --out instead of uploading to Drive")
    ap.add_argument("--out", default="drafts-out")
    ap.add_argument("--seed", type=int)
    args = ap.parse_args()
    # Empty strings come from blank workflow inputs.
    for k in ("statements", "case_study", "request"):
        if getattr(args, k) is not None and not str(getattr(args, k)).strip():
            setattr(args, k, None)

    cfg = yaml.safe_load((ROOT / "generator.yaml").read_text(encoding="utf-8"))
    requested_by = "schedule or command line"
    if args.request:
        try:
            requested_by = options_from_request(args)
        except Exception as e:  # noqa: BLE001
            say(f"::error::{e}")
            return 1
    if isinstance(args.statements, str):
        args.statements = [s.strip() for s in args.statements.replace(" ", ",").split(",") if s.strip()]
    count = max(1, min(int(args.count), cfg["max_per_run"]))

    drive = None
    if not (args.dry_run and args.source and args.catalogue):
        from drive import Drive
        drive = Drive()
    work = Path(tempfile.mkdtemp(prefix="dtgen-"))
    source = Path(args.source) if args.source else work / "source"
    if not args.source:
        drive.download_bank(source)
    syl, cts = load_syllabus(source)
    bank = coverage.load_bank(source)

    catalogue = (json.loads(Path(args.catalogue).read_text(encoding="utf-8")) if args.catalogue
                 else drive.read_json(cfg["drive"]["reference_folder"], "case_studies.json"))
    if not catalogue:
        say("::error::No case-study catalogue. Run the 'Catalogue case studies' workflow (catalogue.py) first.")
        return 1

    from gemini import Gemini, QuotaError
    gem = Gemini(cfg["model"], cfg["temperature"], cfg["max_output_tokens"],
                 max_calls=cfg["max_calls_per_question"] * count + 2, backup_model=cfg.get("backup_model"))

    attachments = []
    if drive:
        for i, fid in enumerate(cfg["drive"].get("specimen_sl_paper2") or []):
            try:
                attachments.append(gem.upload(drive.download(fid, work / f"specimen_{i}.pdf")))
            except QuotaError as e:   # no point writing questions without credit
                say(f"::error::{e}.")
                summary(f"- **Stopped: {e}.**")
                return 1
            except Exception as e:  # noqa: BLE001 - the prompt still works without the specimen
                say(f"::warning::Specimen part {i + 1} could not be attached ({type(e).__name__}); "
                    "share it with the robot account.")
    if attachments:
        attachments = ["The attached PDFs are the IB specimen SL Paper 2 and its markscheme: copy their style."] \
            + attachments
    exemplars = []
    for eid in cfg["drive"].get("exemplars", []):
        p = source / "questions" / eid / "question.yaml"
        if p.exists():
            exemplars.append(p.read_text(encoding="utf-8"))
    exemplars = "\n---\n".join(exemplars)

    rng = random.Random(args.seed)
    run = {"started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "requested_by": requested_by, "model": cfg["model"], "questions": []}
    say(f"Bank: {coverage.summary(coverage.coverage(bank, syl))}")
    summary("## Question generator\n")
    added, stopped = [], False
    for n in range(count):
        cov = coverage.coverage(bank, syl)
        if cov["today"] >= cfg["max_per_day"]:
            say(f"Daily limit of {cfg['max_per_day']} AI questions reached; stopping.")
            summary(f"- Stopped: the daily limit of {cfg['max_per_day']} AI questions was reached.")
            break
        try:
            target = coverage.choose_target(cov, syl, cfg, rng, args.marks, args.difficulty, args.statements)
            cs = coverage.choose_case_study(catalogue, target, cov, cfg["max_questions_per_case_study"], rng,
                                            args.case_study)
        except ValueError as e:
            say(f"::error::{e}")
            summary(f"- Could not start: {e}")
            break
        label = f"{target['marks']}-mark, difficulty {target['difficulty']}, {', '.join(target['statements'])}"
        say(f"Question {n + 1}/{count}: {label}; case study {cs['reference'] if cs else 'none left (fictional)'}")
        log = {"target": target, "case_study": cs and cs["reference"], "steps": []}
        try:
            q, result = write_one(gem, target, cs, bank, cov, syl, cts, cfg, exemplars, attachments, log)
        except QuotaError as e:
            say(f"::error::{e}; stopping.")
            summary(f"- **Stopped early: {e}.**")
            stopped = True
            log["result"] = str(e)
            run["questions"].append(log)
            break
        except Exception as e:  # noqa: BLE001 - log privately, carry on with the next question
            say(f"::warning::Question {n + 1} failed: {type(e).__name__}")
            log["result"] = "error"
            log["error"] = traceback.format_exc()[-3000:]
            run["questions"].append(log)
            continue
        log["result"] = result
        if q:
            text = convert.to_yaml(q)
            log["id"] = q["id"]
            log["question"] = text
            if args.dry_run:
                d = Path(args.out) / q["id"]
                d.mkdir(parents=True, exist_ok=True)
                (d / "question.yaml").write_text(text, encoding="utf-8")
            else:
                drive.add_question(q["id"], {"question.yaml": text.encode("utf-8")})
            bank.append(q)
            added.append(q["id"])
            say(f"  added {q['id']} ({result})")
            summary(f"- Added `{q['id']}`: {label}")
        else:
            say(f"  not added: {result}")
            summary(f"- Not added ({result}): {label}")
        run["questions"].append(log)

    cost = gem.cost([cfg.get("price_per_million"), cfg.get("backup_price_per_million")])
    run["gemini_calls"], run["tokens"] = gem.calls, gem.tokens
    run["input_tokens"], run["output_tokens"], run["estimated_cost_usd"] = gem.input_tokens, gem.output_tokens, \
        round(cost, 3)
    run["key_used"], run["model_used"] = gem.key_name, gem.model
    run["added"] = added
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    if args.dry_run:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        (Path(args.out) / f"log_{stamp}.json").write_text(json.dumps(run, indent=1, ensure_ascii=False))
    else:
        try:
            drive.write_json(cfg["drive"]["log_folder"], f"{stamp}.json", run)
        except Exception as e:  # noqa: BLE001
            say(f"::warning::Could not write the private log to Drive ({type(e).__name__}).")
    say(f"Done: {len(added)} added; {gem.calls} Gemini calls, {gem.input_tokens} input + {gem.output_tokens} "
        f"output tokens, about ${cost:.2f}.")
    where = f"{args.out}/log_{stamp}.json" if args.dry_run else f"Drive {cfg['drive']['log_folder']}/{stamp}.json"
    summary(f"\n{len(added)} question(s) added; {gem.calls} Gemini calls, about ${cost:.2f} "
            f"({gem.input_tokens} input and {gem.output_tokens} output tokens). Details (private) are in `{where}`.")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"added={len(added)}\n")
    return 1 if stopped and not added else 0


if __name__ == "__main__":
    sys.exit(main())
