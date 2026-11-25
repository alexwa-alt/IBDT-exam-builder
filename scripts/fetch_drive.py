"""Download the staff-only Google Drive folder (question source + strands workbook), or upload the review pack.

Uses a Google service account (a robot Google account). The Drive folder must be shared with the service
account's email address. The folder is in a Shared Drive, so every call passes supportsAllDrives.

Environment:
  GDRIVE_SERVICE_ACCOUNT_JSON   the service account's JSON key (the whole file's contents)
  DRIVE_FOLDER_ID               the id of the top Drive folder (the part of its link after /folders/)

Usage:
  python scripts/fetch_drive.py [--out source]                        download the folder into source/
  python scripts/fetch_drive.py --upload-review build/review_pack.pdf  replace review/DT_bank_review_pack.pdf
"""
import argparse
import io
import json
import os
import sys
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
# Google-format files are exported; everything else is downloaded as it is.
EXPORTS = {"application/vnd.google-apps.spreadsheet":
           ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx")}
SKIP_FOLDERS = {"review"}          # the review pack is an output, not an input
REVIEW_FOLDER, REVIEW_NAME = "review", "DT_bank_review_pack.pdf"
ALL = {"supportsAllDrives": True}
LIST = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}


def fail(msg):
    print(f"::error::{msg}" if os.environ.get("GITHUB_ACTIONS") else f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def service():
    raw = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    folder = os.environ.get("DRIVE_FOLDER_ID", "").strip()
    if not raw:
        fail("GDRIVE_SERVICE_ACCOUNT_JSON is not set. Add the service account's JSON key as a repository secret.")
    if not folder:
        fail("DRIVE_FOLDER_ID is not set. Add the Drive folder id as a repository secret.")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        fail("GDRIVE_SERVICE_ACCOUNT_JSON is not valid JSON. Paste the whole key file, including the { }.")
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False), folder, info.get("client_email", "?")


def children(drive, folder_id):
    items, token = [], None
    while True:
        r = drive.files().list(q=f"'{folder_id}' in parents and trashed = false", pageToken=token,
                               fields="nextPageToken, files(id, name, mimeType, shortcutDetails)",
                               pageSize=1000, **LIST).execute()
        items += r.get("files", [])
        token = r.get("nextPageToken")
        if not token:
            return items


def open_folder(drive, folder_id, email):
    """Check the folder can be seen, with a clear message if it isn't shared with the robot account."""
    try:
        f = drive.files().get(fileId=folder_id, fields="id, name, mimeType", **ALL).execute()
    except HttpError as e:
        if e.resp.status in (403, 404):
            fail(f"The service account cannot see Drive folder {folder_id}. Share the folder (or its Shared Drive) "
                 f"with {email}, then run the workflow again.")
        raise
    if f["mimeType"] != FOLDER:
        fail(f"DRIVE_FOLDER_ID points to {f['name']!r}, which is not a folder.")
    return f


def download(drive, file_id, dest, export=None):
    req = (drive.files().export_media(fileId=file_id, mimeType=export) if export
           else drive.files().get_media(fileId=file_id, **ALL))
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(buf.getvalue())


def fetch(drive, folder_id, out, top=True):
    count = 0
    for f in children(drive, folder_id):
        name, mime = f["name"], f["mimeType"]
        if mime == SHORTCUT:     # follow shortcuts to their target
            target = f.get("shortcutDetails", {})
            f = {"id": target.get("targetId"), "name": name, "mimeType": target.get("targetMimeType")}
            mime = f["mimeType"]
        if "/" in name or name in (".", ".."):
            print(f"skipping {name!r}: not a safe file name")
            continue
        if mime == FOLDER:
            if top and name in SKIP_FOLDERS:
                continue
            count += fetch(drive, f["id"], out / name, top=False)
        elif mime in EXPORTS:
            export, ext = EXPORTS[mime]
            download(drive, f["id"], out / (Path(name).stem + ext), export)
            count += 1
        elif mime.startswith("application/vnd.google-apps."):
            print(f"skipping {out / name}: Google-format file ({mime})")
        else:
            download(drive, f["id"], out / name)
            count += 1
    return count


def upload_review(drive, folder_id, path):
    if not path.exists():
        fail(f"{path} does not exist; run build_bank.py first.")
    sub = [f for f in children(drive, folder_id) if f["mimeType"] == FOLDER and f["name"] == REVIEW_FOLDER]
    if not sub:
        fail(f"There is no {REVIEW_FOLDER!r} folder in the Drive folder.")
    existing = [f for f in children(drive, sub[0]["id"]) if f["name"] == REVIEW_NAME]
    media = MediaFileUpload(str(path), mimetype="application/pdf", resumable=True)
    try:
        if existing:   # replace the contents, keeping the same file (and its comments and link)
            drive.files().update(fileId=existing[0]["id"], media_body=media, **ALL).execute()
        else:
            drive.files().create(body={"name": REVIEW_NAME, "parents": [sub[0]["id"]]}, media_body=media,
                                 fields="id", **ALL).execute()
    except HttpError as e:
        if e.resp.status == 403:
            fail(f"The service account may read the Drive folder but not edit {REVIEW_FOLDER}/. Give it "
                 f"Contributor (or Content manager) access to that folder to update the review pack.")
        raise
    print(f"uploaded {path} to {REVIEW_FOLDER}/{REVIEW_NAME}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="source")
    ap.add_argument("--upload-review", metavar="PDF")
    args = ap.parse_args()
    drive, folder_id, email = service()
    top = open_folder(drive, folder_id, email)
    if args.upload_review:
        upload_review(drive, folder_id, Path(args.upload_review))
        return
    out = Path(args.out)
    n = fetch(drive, folder_id, out)
    if not (out / "questions").is_dir() or not (out / "syllabus").is_dir():
        fail(f"Drive folder {top['name']!r} should contain 'questions' and 'syllabus' folders.")
    print(f"downloaded {n} files from {top['name']!r} into {out}/")


if __name__ == "__main__":
    main()
