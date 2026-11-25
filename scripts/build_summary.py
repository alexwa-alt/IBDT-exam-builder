"""Print a Markdown summary of a build, for the GitHub Actions run page ($GITHUB_STEP_SUMMARY).

Reads build/data/{questions,review}.json and site/data/dt/syllabus_review.json. Also prints ::error:: and
::warning:: lines so problems show as annotations on the run.

Usage: python scripts/build_summary.py [--build build] >> "$GITHUB_STEP_SUMMARY"
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default=str(ROOT / "build"))
    args = ap.parse_args()
    build = Path(args.build)
    questions = load(build / "data" / "questions.json", [])
    review = load(build / "data" / "review.json", [])
    syllabus = load(ROOT / "site" / "data" / "dt" / "syllabus_review.json", [])

    errors = [r for r in review if r["errors"]]
    print("## Question bank build\n")
    plural = lambda n, word: f"**{n}** {word}{'' if n == 1 else 's'}"
    print(f"- {plural(len(questions), 'question')} published to the site")
    print(f"- {plural(len(errors), 'question')} left out because of errors")
    print(f"- {plural(len(syllabus), 'problem')} in the strands workbook\n")
    if errors:
        print("### Questions with errors (not on the site)\n")
        print("Fix these in the question's `question.yaml` in Drive; the next build will include them.\n")
        for r in errors:
            for e in r["errors"]:
                print(f"- `{r['id']}`: {e}")
                print(f"::error title=Question {r['id']}::{e}", file=sys.stderr)
        print()
    notes = [(r["id"], w) for r in review for w in r["warnings"]]
    if notes:
        print("<details><summary>Notes</summary>\n")
        for i, w in notes:
            print(f"- `{i}`: {w}")
        print("\n</details>\n")
    if syllabus:
        print("<details><summary>Strands workbook problems</summary>\n")
        for s in syllabus:
            print(f"- {s['id']}: {s['problem']}")
        print("\n</details>\n")
    if errors:
        print(f"::warning::{len(errors)} question(s) left out because of errors; see the run summary.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
