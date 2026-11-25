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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf")
    ap.add_argument("--out")
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
    doc = gem.upload(pdf)

    index = gem.ask([doc, "This PDF is a collection of IB Design Technology exam questions, each built on a case "
                     "study (a product or context with text, figures and sometimes data). List every case study "
                     "with its IB reference exactly as printed (e.g. 26M.2.SL.TZ1.6), the product, and the PDF "
                     "page numbers (1 = first page of the file) where it starts and ends."], CaseStudyIndex)
    print(f"found {len(index.case_studies)} case studies")
    out, seen = [], set()
    for item in index.case_studies:
        if item.reference in seen:
            continue
        seen.add(item.reference)
        cs = gem.ask([doc, f"Extract the case study {item.reference} ({item.product}), pages {item.first_page}–"
                      f"{item.last_page} of this PDF. Give the complete stimulus text with every product fact, any "
                      "data written out as text, every figure's caption and page, and a one-line summary of each "
                      "original question part. Then list which of these new-syllabus SL topics the case study "
                      f"could support well (ids only): {TOPIC_NAMES}."], CaseStudy)
        d = cs.model_dump()
        d["reference"] = item.reference
        d["suits_topics"] = [t for t in d["suits_topics"] if t in SL_TOPICS]
        out.append(d)
        print(f"  {item.reference}: {len(d['text'].split())} words, {len(d['figures'])} figures, "
              f"topics {', '.join(d['suits_topics'])}")
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"saved {args.out}")
    else:
        drive.write_json(cfg["drive"]["reference_folder"], "case_studies.json", out)
        print(f"saved {cfg['drive']['reference_folder']}/case_studies.json in Drive "
              f"({len(out)} case studies; {gem.calls} Gemini calls)")


if __name__ == "__main__":
    main()
