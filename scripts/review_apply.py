"""Apply reviewers' decisions sent from the staff site: change a question's status in Drive.

The site sends an encrypted request (see request_crypto.py):
  {"kind": "review", "sent": <ms>, "by": "<reviewer name>",
   "items": [{"id": "<question id>", "status": "reviewed" | "published" | "rejected" | "draft", "reason": "..."}]}

For each item, questions/<id>/question.yaml in Drive gets:
  - its top-level  status:  line changed (nothing else in the question is touched), and
  - an entry added to a  review_history:  list at the end of the file (who, when, decision, reason).
Drive keeps the previous version of the file in its version history.

Usage: SITE_PASSWORD=... python scripts/review_apply.py --request <encrypted text>
       python scripts/review_apply.py --local-file question.yaml --status reviewed --by Alex   (testing)
"""
import argparse
import datetime
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

STATUSES = {"draft", "reviewed", "published", "rejected"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")


def apply(text, status, by, reason="", when=None):
    """Return question.yaml text with the new status and a review_history entry. Raises ValueError."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    before = yaml.safe_load(text)
    if not isinstance(before, dict) or "status" not in before:
        raise ValueError("question.yaml has no top-level status")
    new, n = re.subn(r"(?m)^status:[ \t]*\S.*$", f"status: {status}", text, count=1)
    if n != 1:
        raise ValueError("could not find the status: line")
    history = list(before.get("review_history") or [])
    entry = {"date": (when or datetime.date.today()).isoformat(), "by": by[:60] or "unknown",
             "status": status}
    if reason:
        entry["reason"] = " ".join(reason.split())[:1000]
    history.append(entry)
    # Remove any existing review_history block (from its key to the next top-level key), then re-add it at the end.
    new = re.sub(r"(?ms)^review_history:.*?(?=^[A-Za-z_][\w-]*:|\Z)", "", new).rstrip("\n") + "\n"
    new += yaml.safe_dump({"review_history": history}, sort_keys=False, allow_unicode=True, width=110)
    after = yaml.safe_load(new)
    expected = dict(before, status=status, review_history=history)
    if after != expected:
        raise ValueError("the edited file did not read back as expected; nothing was changed")
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--request")
    ap.add_argument("--local-file")
    ap.add_argument("--status")
    ap.add_argument("--by", default="")
    ap.add_argument("--reason", default="")
    args = ap.parse_args()

    if args.local_file:
        p = Path(args.local_file)
        p.write_text(apply(p.read_text(encoding="utf-8"), args.status, args.by, args.reason), encoding="utf-8")
        print(f"{p}: status {args.status}")
        return 0

    from request_crypto import BadRequest, open_request
    try:
        req = open_request(args.request or "", "review")
    except BadRequest as e:
        print(f"::error::{e}")
        return 1
    from generator.drive import Drive
    drive = Drive()
    by = str(req.get("by") or "unknown")
    done = failed = 0
    summary = ["## Reviews from the website\n"]
    for item in (req.get("items") or [])[:100]:
        qid, status = str(item.get("id", "")), str(item.get("status", ""))
        if not ID_RE.match(qid) or status not in STATUSES:
            print("::warning::skipped an item with a bad id or status")
            failed += 1
            continue
        fid = drive.question_file(qid)
        if not fid:
            print(f"::warning::{qid}: not in the bank")
            failed += 1
            continue
        try:
            new = apply(drive.read_text(fid), status, by, str(item.get("reason") or ""))
        except ValueError as e:
            print(f"::warning::{qid}: {e}")
            failed += 1
            continue
        drive.update(fid, new.encode("utf-8"), "text/yaml")
        print(f"{qid}: {status}")
        summary.append(f"- `{qid}` → {status}")
        done += 1
    summary.append(f"\n{done} change(s) saved to Drive; {failed} skipped.")
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        Path(path).open("a", encoding="utf-8").write("\n".join(summary) + "\n")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        Path(out).open("a").write(f"changed={done}\n")
    return 0 if done or not failed else 1


if __name__ == "__main__":
    sys.exit(main())
