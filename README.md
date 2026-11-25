# IB Design technology practice-paper builder

A staff-only website for building IB DT practice papers (first assessment 2027). Staff filter a bank of
questions by syllabus, teaching order, command term and difficulty, pick questions (or press one button for a
specimen-style SL Paper 2), and download an exam-style PDF with a markscheme.

Questions are written as source files (one `question.yaml` per question, see [FORMAT.md](FORMAT.md)) in a
**staff-only Google Drive folder**. This repository holds **code only**. Question content, figures, rendered
images and the review pack are never committed (see `.gitignore`).

## How it works

```
Google Drive (staff only)            GitHub Actions (nightly, or on demand)              GitHub Pages (public URL)
questions/<id>/question.yaml  ──►  fetch_drive.py → syllabus_import.py → build_bank.py  ──►  encrypted site
syllabus/DT_IB_Strands.xlsx          → encrypt_site.py (staff password)                       (login screen)
review/DT_bank_review_pack.pdf ◄──  review pack uploaded back to Drive
```

| File | What it does |
|---|---|
| `scripts/fetch_drive.py` | Downloads the Drive folder into `source/`; uploads the review pack back to `review/` |
| `scripts/syllabus_import.py` | Strands workbook → `site/data/dt/syllabus.json` (+ `syllabus_review.json` of workbook problems) |
| `scripts/build_bank.py` | Checks every question, renders question and markscheme images, writes `build/` and the review pack |
| `scripts/encrypt_site.py` | Copies `site/` to `public/` and adds every data file and image, encrypted with the staff password |
| `scripts/build_summary.py` | Writes the list of problems shown on each GitHub Actions run page |
| `site/` | The website: `vault.js` (unlocking), `app.js` (filters, cards, paper list), `paper.js` (PDF) |
| `.github/workflows/build.yml` | The automatic build and publish |
| `scripts/generator/` | The Gemini question generator (see "Gemini question generator" below) |
| `scripts/review_apply.py` | Saves review decisions made on the website into Drive |
| `scripts/request_crypto.py` | Opens the encrypted requests the website's Generate and Review buttons send |
| `site/staff.js` | The website's Generate questions dialog and Review buttons |
| `.github/workflows/generate.yml` | Nightly (00:47 Bangkok) and on-demand question generation |
| `.github/workflows/review.yml` | Applies website reviews to Drive, then rebuilds the site |
| `.github/workflows/catalogue.yml` | One-off: lists the case studies in the past-paper PDF |
| `generator.yaml` | Gemini model name, limits, target mix, Drive ids of the reference PDFs |
| `config.yaml` | Which question statuses are published; whether past-paper figures go on the site |

**Encryption.** The password is stretched into a key with PBKDF2 (600,000 rounds), and each file is encrypted
with AES-256-GCM under a random file name. The only readable data file on the site is `data/lock.json`, which
holds no question content. The browser decrypts files after login. "Remember me" stores the derived key, never
the password. Changing the password logs every device out.

## Setting up (browser only)

### 1. Turn on GitHub Pages
1. In this repository, open **Settings** → **Pages**.
2. Under **Build and deployment** → **Source**, choose **GitHub Actions**.

### 2. Add the secrets
For each secret: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**, type the
name exactly as shown, paste the value, then **Add secret**.

| Name | Value |
|---|---|
| `SITE_PASSWORD` | The staff password for the site (at least 8 characters; a short phrase is best) |
| `DRIVE_FOLDER_ID` | `1FEAN1bv9KM3Hn_4YkKbpe1Sf0HN9pRzt` |
| `GDRIVE_SERVICE_ACCOUNT_JSON` | The service account's JSON key: open the downloaded `.json` file in a text editor and paste all of it |

### 3. Create the service account (once school IT agrees)
A service account is a robot Google account that lets GitHub read the Drive folder.
1. Go to <https://console.cloud.google.com>, create a project (e.g. "DT paper builder").
2. **APIs & Services** → **Library** → search **Google Drive API** → **Enable**.
3. **IAM & Admin** → **Service accounts** → **Create service account**. Give it a name and press **Done**
   (no roles needed).
4. Open the new account → **Keys** → **Add key** → **Create new key** → **JSON**. A file downloads. That file is
   the `GDRIVE_SERVICE_ACCOUNT_JSON` secret. Keep it private and delete the download once it's pasted.
5. Copy the account's email address (it ends in `iam.gserviceaccount.com`). In Google Drive, share the DT folder
   with it as **Viewer**, and the `review` subfolder as **Contributor**, so the build can update the review pack.

### 4. Run it
1. Open the **Actions** tab → **Build and publish** → **Run workflow**.
2. When it finishes (about 2–3 minutes), the run page shows a summary: questions published, questions left out
   because of errors, and strands-workbook problems. The site address is shown on the **deploy** step.

It then runs automatically every night at 02:17 Bangkok time, so edits made in Drive appear the next morning.
To change the password, edit the `SITE_PASSWORD` secret and run the workflow again.

## Gemini question generator

Gemini writes one new SL Paper 2 question every night (and more on demand from the website). Each question is
based on a case study from the old-syllabus past papers, checked by the same rules as the nightly build plus
stricter ones (`scripts/generator/extra_checks.py`), reviewed by a second Gemini "Head of DT" prompt, and added
to Drive `questions/` as a **draft** marked **AI-written**. Hand-written questions work exactly as before.

```
generate.yml ─► read the bank, find the gaps ─► choose target + case study ─► Gemini writes (JSON)
             ─► convert to question.yaml ─► checker (+ up to 2 repairs) ─► Gemini reviewer (+ 1 revision)
             ─► questions/<id>/question.yaml in Drive  +  private log in Drive generation-log/
```

**Privacy.** This repository and its Actions logs are public. Past-paper text, the specimen, the case-study list
and Gemini's replies are only ever read from or written to Drive; the logs show only question ids and targets.

### Reviewing on the website
Open a question (click its picture). Staff see **Approve**, **Publish**, **Reject** (with a reason) and **Back to
draft**. Decisions collect in **Reviews to send**; type your name and press **Send reviews**. About 5 minutes later
the site has rebuilt with the new statuses. Rejected questions are hidden (tick **Status → Rejected** to see or
restore them), and their reasons are given to Gemini so it learns what the department doesn't want. Nobody needs
to open the Drive folder, and the website can only change a question's status, never its text or files.

**Generate questions…** (top right) asks for 1–5 new questions now, optionally choosing marks, difficulty,
statements or a case study. They appear about 10 minutes later.

Both buttons start GitHub workflows. The request is encrypted with the staff password before it leaves the
browser, so the public Actions page shows only scrambled text.

### Setting up the generator (browser only)
1. **Gemini key.** At <https://aistudio.google.com/apikey> create an API key. Add it as repository secret
   `GEMINI_API_KEY`.
2. **Drive folders.** In the bank folder create two folders, `reference` and `generation-log`. Give the robot
   (service) account **Contributor** on `questions`, `reference` and `generation-log` (it already has Viewer on the
   bank). Share with it as **Viewer**: the past-paper PDF *Case Study style questions - from past syllabus* and the
   specimen paper parts 10–12 (ids in `generator.yaml`).
3. **Catalogue the case studies (once).** Actions → **Catalogue case studies** → **Run workflow**. It saves
   `reference/case_studies.json` in Drive: a list of every case study, its text and the topics it suits. Skim it
   and correct anything odd (it is plain text and can be edited in Drive).
4. **Website buttons.** On GitHub: your picture → **Settings** → **Developer settings** → **Personal access
   tokens** → **Fine-grained tokens** → **Generate new token**. Repository access: *Only select repositories* →
   this repository. Permissions → Repository permissions → **Actions: Read and write** (nothing else). Choose an
   expiry (up to a year; set a reminder to renew it). Copy the token and add it as repository secret
   `GEN_DISPATCH_TOKEN`, then run **Build and publish**. The token is stored encrypted in the site, so only staff
   with the password can use it, and it can do nothing except start and read workflows in this repository.
   Without it the site works as before, without the Generate and Review buttons.
5. **Try it.** Actions → **Generate questions** → **Run workflow** (count 1). The run page lists what was added;
   the full log is in Drive `generation-log/`.

To change the model, the number per night, the daily cap or the mix of marks and difficulty, edit
`generator.yaml`. To change the time, edit the `cron` line in `.github/workflows/generate.yml`.

## Testing on a computer (for developers)

Put a copy of the Drive folder in `local-source/` (ignored by git), then:
```bash
pip install -r requirements.txt
python scripts/syllabus_import.py local-source/syllabus/DT_IB_Strands.xlsx
python scripts/build_bank.py --source local-source
SITE_PASSWORD=test-password python scripts/encrypt_site.py
python -m http.server 8000 --directory public
```

Generator and review tests (no keys needed): `pip install pydantic pytest && python -m pytest tests`.
A trial generation without uploading (needs `GEMINI_API_KEY` and a local `case_studies.json`):
```bash
python scripts/generator/generate.py --source local-source --catalogue case_studies.json --dry-run --out drafts-out
```
Then open <http://localhost:8000>. (The login needs `localhost` or `https://`: browsers only allow the
built-in encryption on secure addresses.)

## Still to come
- HL Paper 2 and Paper 1 (multiple choice): add a format to `FORMATS` in `site/app.js` and a cover title in
  `site/paper.js`.
- Unit names: fill in `UNIT_NAMES` at the top of `site/app.js`.
