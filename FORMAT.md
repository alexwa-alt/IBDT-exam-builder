# Question format

Each question is a folder in `source/questions/`, named by its id, holding `question.yaml` and its figure files.

```yaml
id: hippo-roller                 # must match the folder name
title: Hippo Roller              # shown on the site
level: SL                        # SL or HL
paper: 2
marks: 6                         # SL Paper 2: 6 or 10
difficulty: 2                    # 1 = foundation, 2 = standard, 3 = challenging
status: draft                    # draft -> reviewed -> published (or rejected; set from the website)
source:
  type: past-paper case study    # or: original
  reference: 26M.2.SL.TZ2.6
figure_rights: past-paper        # original or past-paper (past-paper figures stay off the public site)
stimulus:                        # blocks, in order
- text: Paragraph text. <b>bold</b>, <i>italic</i> and <super>3</super> are allowed.
- figure: hippo.png              # file in this folder
  caption: 'Figure 1: The 75-litre Hippo Roller drum'
  width_mm: 95
  credit: Copyright © 2026 Hippo Roller.
- table:
    caption: 'Table 1: Standing elbow height in mm'
    widths_mm: [50, 38, 38, 38]
    rows:
    - [User group, 5th percentile, 50th percentile, 95th percentile]
    - [Children aged 10, '780', '845', '910']
- bullets: [first point, second point]
- note: Small print, for example "Data written for this practice paper."
parts:
- label: a
  marks: 1
  command_term: State             # from the Command Terms sheet (or the specimen)
  syllabus: [A1.1.3, A1.1.6]      # statement ids from the strands workbook
  question: State the percentile …   # must begin with the command term (or "Using …, <term> …")
  answers:                        # each answer is one ✓ marking point
  - 5th percentile
  notes: Award [1] for … Do not accept …
```

**Numbering.** Figures and tables are numbered from 1 within each question (Figure 1, Table 1), because the
paper builder decides question numbers.

**Checks.** `python scripts/build_bank.py` refuses any question whose marks don't add up, whose command term is
not on the department list or doesn't match the wording, that cites a missing or HL-only statement, or that uses
HL-only or old-syllabus terms. Problems are listed in `build/data/review.json`.

**Fields added automatically** (leave them as they are):
- `source.generated_by`, `source.generated_on`, `source.model`, `source.target`: on questions written by Gemini
  (`scripts/generator/`). The site marks these questions "AI-written".
- `review_history`: a list of decisions made with the website's Review buttons (date, who, status, reason).
  `status: rejected` questions are hidden on the site unless the Rejected filter is ticked; their reasons are
  shown to Gemini so it avoids the same problems.
