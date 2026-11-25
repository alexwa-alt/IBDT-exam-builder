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
| `DRIVE_FOLDER_ID` | `1HknYqxQaBoUCzkB962dTJOswFDxFrQze` |
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

## Testing on a computer (for developers)

Put a copy of the Drive folder in `local-source/` (ignored by git), then:
```bash
pip install -r requirements.txt
python scripts/syllabus_import.py local-source/syllabus/DT_IB_Strands.xlsx
python scripts/build_bank.py --source local-source
SITE_PASSWORD=test-password python scripts/encrypt_site.py
python -m http.server 8000 --directory public
```
Then open <http://localhost:8000>. (The login needs `localhost` or `https://`: browsers only allow the
built-in encryption on secure addresses.)

## Still to come
- HL Paper 2 and Paper 1 (multiple choice): add a format to `FORMATS` in `site/app.js` and a cover title in
  `site/paper.js`.
- Unit names: fill in `UNIT_NAMES` at the top of `site/app.js`.
