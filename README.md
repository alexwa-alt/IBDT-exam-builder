# IB Design technology question bank

A staff-only practice-paper builder for IB DT (first assessment 2027), adapted from the IGCSE
paper-2-builder. Questions are written as source files, not extracted from past-paper PDFs.

## Milestone 1 (this folder): the content pipeline

```
source/                       the private source (will live in the staff-only Drive folder)
  syllabus/DT_IB_Strands.xlsx the department's strands workbook (syllabus, teaching order, command terms)
  questions/<id>/             one folder per question: question.yaml + figures (see FORMAT.md)
scripts/syllabus_import.py    workbook -> site/data/dt/syllabus.json (+ syllabus_review.json of problems)
scripts/build_bank.py         checks every question, renders question and markscheme images,
                              writes build/data/{questions,tags,review}.json and build/review_pack.pdf
config.yaml                   which statuses are published; whether past-paper figures go on the site
fonts/                        Liberation Sans and DejaVu Sans (open licences), so builds look the same everywhere
```

Run:
```bash
pip install -r requirements.txt
python scripts/syllabus_import.py
python scripts/build_bank.py
```

## Still to come
- Milestone 2: adapt the site (DT filters, "taught so far", specimen-style SL Paper 2 builder) and encrypt the
  build output with the staff password.
- Milestone 3: GitHub Action that fetches `source/` from the Drive folder, builds, encrypts and publishes.
