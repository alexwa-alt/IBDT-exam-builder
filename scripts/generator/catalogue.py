"""One-off (re-runnable): list every case study in the past-paper PDF, for the generator to choose from.

Gemini reads the PDF twice: first to list the case studies and their pages, then once per case study to
extract its text, data, figures and the topics it suits. The result is saved privately in Drive as
reference/case_studies.json (never in this public repository). Alex can open and correct that file in Drive.

Usage:
  python scripts/generator/catalogue.py                  read the PDF named in generator.yaml, save to Drive
  python scripts/generator/catalogue.py --pdf file.pdf --out case_studies.json   (local test)
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from coverage import SL_TOPICS  # noqa: E402
from schema import CaseStudy, CaseStudyIndex  # noqa: E402

TOPIC_NAMES = ("A1.1 Ergonomics; A2.1 User-centred research methods; A2.2 Prototyping techniques; A3.1 Material "
               "classification and properties; B1.1 User-centred design; B2.1 The design process; B2.2 Modelling "
               "and prototyping; B3.1 Material selection; C1.1 Responsibility of the designer; C1.2 Inclusive "
               "design; C2.1 Design for sustainability; C2.2 Design for a circular economy; C3.1 Product analysis "
               "and evaluation")


def topic_ids(items):
    """SL topic ids from whatever Gemini wrote: 'A1.1', 'A1.1 Ergonomics', 'Ergonomics (A1.1)' or 'Ergonomics'."""
    names = {name.strip().lower(): tid for tid, name in
             (part.strip().split(" ", 1) for part in TOPIC_NAMES.split(";"))}
    found = []
    for item in items:
        ids = re.findall(r"[ABC]\d\.\d", item) or [names.get(item.strip().lower())]
        found += [t for t in ids if t in SL_TOPICS and t not in found]
    return found


EXTRACT = ("Extract the case study {ref} ({product}), pages {first}–{last} of this PDF.\n"
           "- text: copy the case-study (stimulus) text WORD FOR WORD, every sentence, in order, including any "
           "text in figure labels or bullet lists. Do not summarise, shorten or paraphrase. Do not include the "
           "question parts themselves.\n"
           "- data: every table or number in the stimulus, written out as text (or 'none').\n"
           "- figures: every figure's caption and the PDF page it is on.\n"
           "- original_questions: a one-line summary of each original question part.\n"
           "- suits_topics: which of these new-syllabus SL topics the case study could support well, as ids only "
           "(e.g. A1.1): {topics}.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf")
    ap.add_argument("--out")
    ap.add_argument("--fresh", action="store_true", help="redo every case study, not only missing ones")
    args = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "generator.yaml").read_text(encoding="utf-8"))
    from gemini import Gemini
    gem = Gemini(cfg["model"], 0.1, 32000, max_calls=80)

    drive = None
    if args.pdf:
        pdf = Path(args.pdf)
    else:
        from drive import Drive
        drive = Drive()
        pdf = drive.download(cfg["drive"]["past_papers_pdf"], Path(tempfile.mkdtemp()) / "past_papers.pdf")

    def load():
        if args.out:
            p = Path(args.out)
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        return drive.read_json(cfg["drive"]["reference_folder"], "case_studies.json") or []

    def save(items):
        """Saved after every case study, so an error part-way through keeps the work done so far."""
        if args.out:
            Path(args.out).write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
        else:
            drive.write_json(cfg["drive"]["reference_folder"], "case_studies.json", items)

    out = [] if args.fresh else load()
    done = {c["reference"] for c in out}
    if done:
        print(f"{len(done)} case studies already catalogued; only missing ones will be added (--fresh redoes all)")

    doc = gem.upload(pdf)
    index = gem.ask([doc, "This PDF is a collection of IB Design Technology exam questions, each built on a case "
                     "study (a product or context with text, figures and sometimes data). List every case study "
                     "with its IB reference exactly as printed (e.g. 26M.2.SL.TZ1.6), the product, and the PDF "
                     "page numbers (1 = first page of the file) where it starts and ends."], CaseStudyIndex)
    print(f"found {len(index.case_studies)} case studies")
    for item in index.case_studies:
        if item.reference in done:
            continue
        done.add(item.reference)
        cs = gem.ask([doc, EXTRACT.format(ref=item.reference, product=item.product, first=item.first_page,
                                          last=item.last_page, topics=TOPIC_NAMES)], CaseStudy)
        d = cs.model_dump()
        d["reference"] = item.reference
        d["suits_topics"] = topic_ids(d["suits_topics"])
        out.append(d)
        save(out)
        print(f"  {item.reference}: {len(d['text'].split())} words, {len(d['figures'])} figures, "
              f"topics {', '.join(d['suits_topics']) or 'none'}")
    where = args.out or f"Drive {cfg['drive']['reference_folder']}/case_studies.json"
    print(f"saved {len(out)} case studies to {where} ({gem.calls} Gemini calls)")


if __name__ == "__main__":
    main()
