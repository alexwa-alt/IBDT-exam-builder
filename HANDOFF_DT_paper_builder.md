# Handoff: IB Design technology practice-paper builder

You are continuing a project started in a Claude.ai chat with Alex (a Physics teacher at St Andrews International
School Bangkok, who looks after learning technology). Alex is new to web development: explain any new term or
abbreviation the first time you use it, and keep instructions to things he can do in a browser (his work laptop
has no admin rights, so he can't install software).

Read this whole file before starting. The decisions in section 2 are settled; don't reopen them without asking Alex.

---

## 1. What we're building

A **staff-only website for building IB Design technology (DT) practice papers**, modelled closely on Alex's
existing IGCSE question-bank site (`alexwa-alt/paper-2-builder`). Staff filter a bank of questions by syllabus,
teaching order, command term and difficulty, pick questions (or press one button for a specimen-style paper), and
download an exam-style PDF with a markscheme.

The big difference from the IGCSE site: **DT has no bank of past-paper PDFs.** Questions are written as structured
source files (one YAML file per question, plus figures). So the IGCSE site's `extract.py` (cuts PDFs into images)
and `tag.py` (Gemini tagging) are **not needed**. A build script renders each question straight into the same
image format the IGCSE site's paper builder already uses, with its tags known in advance.

**Milestone 1 is done** (see section 3). Your job is **milestone 2 (the website and encryption)** and
**milestone 3 (automatic build and publish)**.

---

## 2. Decisions already made

1. **Hosting:** a public GitHub Pages site, published from the DT repository. Alex has given you this repository.
   Do **not** modify `alexwa-alt/paper-2-builder`; use it only as a reference and source of code to copy.
2. **Password protection, "level 2":** the site is behind a shared staff password, enough to stop a curious
   student, not heavy-duty security. The question data, markschemes and images must be **encrypted** at build
   time, so nothing readable is ever publicly downloadable. A login screen alone is not enough.
3. **The source content lives in a staff-only Google Drive folder, never in the repository.**
   - Drive folder (in a Shared Drive): `https://drive.google.com/drive/folders/1HknYqxQaBoUCzkB962dTJOswFDxFrQze`
   - Layout:
     ```
     questions/<question-id>/question.yaml + figure files
     syllabus/DT_IB_Strands.xlsx      the department's syllabus, teaching order and command terms
     review/DT_bank_review_pack.pdf   PDF of every question + markscheme, for staff to comment on
     FORMAT.md                        the question format
     ```
   - The public repository holds **code only**. It must never contain question YAML, figures, rendered question
     images, unencrypted `questions.json` / `tags.json`, or the review pack.
4. **Review workflow (simplest version):** DT staff read the review pack PDF in Drive and add comments. Question
   edits are made in the YAML source (by Claude in the chat, for now). Staff do not edit YAML themselves.
5. **Past-paper case studies:** 7 of the 14 questions use IB past-paper case studies whose images are IB
   copyright. They are in the review pack but **not on the site** while `include_past_paper_figures: false` in
   `config.yaml`. Keep that switch working; don't change its value.
6. **Scope:** SL Paper 2 first (50 marks, 1 hour 30 minutes). HL Paper 2 and multiple-choice Paper 1 come later,
   so keep the code general enough to add them (`level` and `paper` fields already exist), but don't build them now.
7. **Command terms** come from the department's Command Terms sheet, plus the terms used in the specimen SL
   Paper 2. "Discuss" and "Determine" are deliberately not used.
8. **Figures and tables are numbered from 1 within each question**, because the site decides question numbers.

---

## 3. What already exists (milestone 1)

Alex has a zip, `dt-bank-milestone1.zip`. Ask him for it if it isn't in the repository yet. It contains:

```
scripts/syllabus_import.py   DT_IB_Strands.xlsx -> site/data/dt/syllabus.json (+ syllabus_review.json)
scripts/build_bank.py        checks each question, renders question + markscheme PNGs, writes build/data/*.json,
                             build/images/, build/review_pack.pdf (all of every question, incl. past-paper ones)
config.yaml                  publish_statuses, include_past_paper_figures
fonts/                       Liberation Sans + DejaVu Sans (open licences), bundled so CI renders identically
FORMAT.md, README.md, requirements.txt
source/                      a local copy of the Drive folder's questions/ and syllabus/ (14 questions)
```

**Important:** the zip's `source/` folder contains the question content and past-paper images. **Do not commit
it.** Move it to a git-ignored folder (for example `local-source/`) and use it only for local testing
(`python scripts/build_bank.py --source local-source`). Add `source/`, `local-source/` and `build/` to
`.gitignore` before your first commit.

Run it locally:
```bash
pip install -r requirements.txt
python scripts/syllabus_import.py local-source/syllabus/DT_IB_Strands.xlsx
python scripts/build_bank.py --source local-source
```
Expected result: 7 questions built, 7 past-paper questions "rendered for the review pack only", 0 errors.

### Data the build produces (inputs to the website)

`build/data/questions.json`, a list:
```json
{"id": "bagasse-food-box", "title": "Bagasse food box", "level": "SL", "paper": 2,
 "pages": [{"image": "images/bagasse-food-box_q1.png", "w_mm": 161.0, "h_mm": 245.2}, ...],
 "ms":    [{"image": "images/bagasse-food-box_ms1.png", "w_mm": 174.1, "h_mm": 172.4}],
 "ms_status": "ok", "source": {"type": "original", ...}, "figure_rights": "original"}
```
Question page images are 161 mm wide (they sit beside paper.js's 13 mm question-number column) and markscheme
images 174 mm. **The images contain no question number;** paper.js draws it, exactly as it does for IGCSE Paper 4/6.

`build/data/tags.json`, an object keyed by question id:
```json
{"bagasse-food-box": {"status": "draft", "marks": 6, "difficulty": 1,
  "statements": ["A3.1.3", "A3.1.4", ...], "topics": ["A3.1", "B3.1", "C2.2"], "rows": ["Process", "Product"],
  "command_terms": ["Describe", "Outline", "State"], "ao_marks": {"AO1": 2, "AO2": 4},
  "taught_by": 6, "units": [3, 4], "text": "searchable plain text of the question"}}
```
`taught_by` is an index into `syllabus.terms`: the **latest** term in which any of the question's statements is
taught.

`build/data/syllabus.json` has keys `terms` (ordered list: "Yr 12 1.1" … "Yr 13 2.2"), `rows`, `strands`, `topics`
(e.g. `"A1.1": "Ergonomics"`), `corrections`, `statements` (each with `id`, `topic`, `topic_title`, `strand`,
`row`, `level`, `term`, `term_index`, `units`, `text`) and `command_terms` (`term`, `ao`, `marks`, `include`,
`pitfall`).

---

## 4. Milestone 2: the website

Start from a copy of the IGCSE site's `site/` folder (`index.html`, `app.js`, `paper.js`, `styles.css`) and adapt
it. Remove what DT doesn't need (the subject picker, multiple-choice and Paper 6 paths, answer grids, past-paper
reference lines); keep the overall look, behaviour and code style.

### 4.1 Filters

All filters combine (AND), as on the IGCSE site:
- **Row:** People / Process / Product / Production (from `syllabus.rows`).
- **Topic and syllabus statement:** a tree, topic (e.g. "A1.1 Ergonomics") → statements, using `topics` and
  `statements` with their text as tooltips. A question matches if any of its statements is ticked.
- **Taught so far:** a single dropdown of `syllabus.terms`. Show only questions whose `taught_by` is at or before
  the chosen term. Questions with `taught_by: null` always show. This is the most important new feature: teachers
  set practice papers before the course is finished.
- **Unit:** checkboxes of the unit numbers present in the bank (names aren't available yet, so show "Unit 4" etc.;
  make it easy to add a name map later).
- **Command term**, **marks (6 or 10)**, **difficulty (1 foundation, 2 standard, 3 challenging)**, **source type**
  (original / past-paper case study).
- **Status:** drafts are shown, with a visible "Draft" badge on the question card.
- **Text search** over `tags.text`.

### 4.2 Question cards and the paper list

Show each question's title, marks, difficulty, row(s), topic codes and status, with a preview of its first page
image. Adding and removing questions, reordering and remembering the paper in the browser all work as on the IGCSE
site.

### 4.3 "Build a specimen-style paper" button

This picks a valid SL Paper 2 from the current filter results:
- 5 questions worth 6 marks, then 2 worth 10 marks (the 6-mark questions come first), 50 marks in total.
- No two questions share the same id (obviously), and the topic overlap is kept low: prefer questions whose
  `topics` don't repeat ones already chosen.
- If the filtered bank can't make a valid paper, say exactly what is missing (e.g. "only 1 ten-mark question
  matches these filters") rather than building a short paper.

### 4.4 PDF (paper.js)

Use the existing structured-paper path, where every question starts on a new page and keeps its page images.
Changes:
- **Cover page:** "Design technology – Standard level – Paper 2 – Practice paper", "1 hour 30 minutes", candidate
  name box, and these instructions:
  - Do not open this examination paper until instructed to do so.
  - Answer all questions.
  - Answers must be written within the answer boxes provided.
  - A calculator is permitted for this paper.
  - The maximum mark for the examination paper is [N marks].

  Below them, a small note: "Practice paper written for teaching purposes in the format of the specimen papers
  for first assessment 2027. Not an official IB publication." **No IB logo or IB codes.**
- **Suggested time:** 1.8 minutes per mark (90 minutes for 50 marks); show the actual total for custom papers.
- **Footer:** page number centred; "Turn over" on every page except the last.
- Replace the past-paper reference lines (`refOf`) with nothing on the paper. In the markscheme, use the question
  title.
- **Markscheme:** an optional section at the end, using the `ms` images, headed "Question n: <title>".

### 4.5 Encryption (new: `scripts/encrypt_site.py` + browser code)

Goal: a curious student who finds the site or the repository can read nothing without the password.

**Build side (Python, `cryptography` library):**
1. Read the password from the environment variable `SITE_PASSWORD`. Fail clearly if it's missing.
2. Make a random 16-byte salt. Derive a 256-bit key with PBKDF2-HMAC-SHA256 (about 600,000 iterations).
   PBKDF2 is a slow "password stretching" function that makes guessing passwords expensive.
3. Encrypt each output file separately with AES-256-GCM, a standard encryption method that also detects
   tampering. Use a fresh random 12-byte nonce (a one-off number) per file. Store `nonce + ciphertext` as `.bin`.
   Files to encrypt:
   - `questions.json`, `tags.json`, `syllabus.json`
   - every question and markscheme image
4. **Give the encrypted files opaque names** (random or HMAC-based), so names like `hippo-roller_q1.png` don't
   reveal content. Store the real-name → opaque-name map inside the encrypted index, not in the clear.
5. Write a public `site/data/lock.json` containing only the salt, the iteration count, the format version and
   a small encrypted "check" value used to test whether the password is right.

**Browser side (Web Crypto API, built into every modern browser, so it works on iPads and phones):**
1. On load, show a simple login screen in the site's style. Derive the key from the typed password and the salt,
   then try to decrypt the check value. If that fails, show "Incorrect password" and nothing else.
2. A "Remember me on this device" option stores the **derived key**, never the password, in `localStorage`.
   Wrap every storage call in try/catch. Add a "Log out" link that clears it.
3. Decrypt the JSON files once. Decrypt each image when it's first needed and turn it into a `blob:` URL (a
   temporary in-memory address the page can show as an image). Cache it.
4. **paper.js currently `fetch`es image URLs** (`toDataURL`). Route all image loading through one helper that
   decrypts, so the PDF builder keeps working unchanged otherwise.

Changing the password = editing the GitHub secret and re-running the build. The old remembered keys then stop
working; detect that and show the login screen again.

### 4.6 Acceptance checks for milestone 2

- Local build + encrypt + `python -m http.server`: the site works end to end with the 7 publishable questions.
  - Filters, including "taught so far", give sensible results. Check a couple by hand against `taught_by`.
  - With no filters, the specimen-style button builds a 50-mark paper. The 7 publishable questions are exactly
    five 6-mark and two 10-mark questions, so it must use all of them. With a narrower filter, for example
    "taught so far" set to "Yr 12 1.1", it explains what is missing instead of building a short paper.
  - The PDF opens on desktop and on an iPad-sized screen, with correct numbering, cover, footer and markscheme.
- Wrong password → nothing readable. Opening any `.bin` URL directly gives unreadable bytes.
- `grep -ri "hippo\|bagasse\|markscheme text samples"` over the built `site/` finds nothing readable, apart from
  code and UI labels.
- No question content in git history: run `git log --stat` and confirm.

---

## 5. Milestone 3: automatic build and publish (GitHub Actions)

A GitHub Action is an automatic task GitHub runs on its own servers. Create one workflow,
`.github/workflows/build.yml`, that:

1. Runs **on demand** (`workflow_dispatch`, a "Run workflow" button in the Actions tab) and **nightly**.
2. Installs `requirements.txt` plus the Google API client.
3. **Downloads the Drive folder** into a temporary `source/` folder using a Google **service account** (a robot
   Google account), recursing through subfolders.
   - It's a Shared Drive, so pass `supportsAllDrives=True` and `includeItemsFromAllDrives=True`.
   - Secrets: `GDRIVE_SERVICE_ACCOUNT_JSON` (the robot account's key) and `DRIVE_FOLDER_ID`
     (`1HknYqxQaBoUCzkB962dTJOswFDxFrQze`).
   - Write this as `scripts/fetch_drive.py` with a clear error if the folder isn't shared with the service account.
4. Runs `syllabus_import.py`, then `build_bank.py`. If the build reports errors, the run **still publishes the
   questions that passed** but shows the errors in the run summary (`$GITHUB_STEP_SUMMARY`).
5. Runs `encrypt_site.py` with the `SITE_PASSWORD` secret.
6. **Deploys with `actions/upload-pages-artifact` + `actions/deploy-pages`**, so the built site is published
   straight from the run and **never committed** to the repository. (Pages source must be set to "GitHub Actions"
   in Settings > Pages; tell Alex.)
7. Uploads the new `review_pack.pdf` back to the Drive `review/` folder, replacing the old file. This needs the
   service account to have edit rights on that one subfolder; if that isn't possible, skip this step and say so.

**Open item, not yours to resolve:** Alex is checking with school IT whether a Drive folder can be shared with an
outside service account. Build and test the workflow so it's ready, but test locally with `local-source/` until
the secret exists. If IT says no, the agreed fallback is a small Google Apps Script web app, running under Alex's
account, that returns the folder's contents only when given a secret token. Don't build the fallback unless Alex
asks.

### Secrets Alex will need to add (Settings > Secrets and variables > Actions)

| Secret | What it is |
|---|---|
| `SITE_PASSWORD` | The staff password for the site |
| `GDRIVE_SERVICE_ACCOUNT_JSON` | The service account's JSON key (once IT agrees) |
| `DRIVE_FOLDER_ID` | `1HknYqxQaBoUCzkB962dTJOswFDxFrQze` |

Write Alex short, numbered, browser-only setup steps for each secret and for the Pages setting in the README.

---

## 6. Things not to do

- Don't commit question content, figures, rendered images, unencrypted data or the review pack, ever, including
  in early "test" commits. If it happens, tell Alex immediately; the history then needs rewriting.
- Don't edit question YAML or the strands workbook. Content changes go through the Drive folder.
- Don't add Gemini or any other AI tagging; the tags come from the source files.
- Don't change `alexwa-alt/paper-2-builder`.
- Don't loosen the checks in `build_bank.py` to make a question pass. Report it instead.

---

## 7. Known issues to leave alone (but mention if relevant)

- **The strands workbook** (`syllabus/DT_IB_Strands.xlsx`) has unit values Excel turned into dates (A4.1.1, A4.1.2,
  C3.1.1, C3.1.2) and a missing unit (B2.1.7). `syllabus_import.py` reports these in `syllabus_review.json`; the
  department will fix the workbook.
- **The workbook marks B2.2 and B3.1 as HL only;** the guide says SL and HL. `syllabus_import.py` corrects this
  deliberately (`FIXES`).
- **Unit names** for unit numbers 0–11 aren't available yet.
- **The bank is small** (7 publishable questions). More are being written in batches. The site must cope
  gracefully with a small bank.

---

## 8. When you finish each milestone

Give Alex:
- a plain-English summary of what changed;
- what he needs to do in the browser (settings, secrets), as numbered steps;
- anything that didn't work or needs a decision.

Keep explanations jargon-light.
