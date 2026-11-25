"""Google Drive helpers for the generator and the review workflow. Builds on scripts/fetch_drive.py.

The robot (service) account needs Contributor access to questions/, reference/ and generation-log/ in the
bank folder, and Viewer access to the reference PDFs named in generator.yaml.
"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fetch_drive  # noqa: E402  (service, children, download, fetch)
from googleapiclient.http import MediaIoBaseUpload  # noqa: E402

FOLDER = fetch_drive.FOLDER
ALL = fetch_drive.ALL


class Drive:
    def __init__(self):
        self.svc, self.root, self.email = fetch_drive.service()
        fetch_drive.open_folder(self.svc, self.root, self.email)

    def child(self, parent, name, folder=None):
        for f in fetch_drive.children(self.svc, parent):
            if f["name"] == name and (folder is None or (f["mimeType"] == FOLDER) == folder):
                return f
        return None

    def folder(self, name, parent=None, create=False):
        parent = parent or self.root
        f = self.child(parent, name, folder=True)
        if f:
            return f["id"]
        if not create:
            return None
        return self.svc.files().create(body={"name": name, "mimeType": FOLDER, "parents": [parent]},
                                       fields="id", **ALL).execute()["id"]

    def download_bank(self, out):
        """questions/ and syllabus/ (the same download as the nightly build)."""
        return fetch_drive.fetch(self.svc, self.root, Path(out))

    def download(self, file_id, dest):
        fetch_drive.download(self.svc, file_id, Path(dest))
        return Path(dest)

    def read_text(self, file_id):
        buf = io.BytesIO()
        from googleapiclient.http import MediaIoBaseDownload
        dl = MediaIoBaseDownload(buf, self.svc.files().get_media(fileId=file_id, **ALL))
        done = False
        while not done:
            _, done = dl.next_chunk()
        return buf.getvalue().decode("utf-8")

    def _media(self, data, mime):
        return MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=False)

    def write(self, parent, name, data, mime="application/octet-stream"):
        """Create the file, or replace its contents if it exists (Drive keeps the old version)."""
        existing = self.child(parent, name, folder=False)
        if existing:
            self.svc.files().update(fileId=existing["id"], media_body=self._media(data, mime), **ALL).execute()
            return existing["id"]
        return self.svc.files().create(body={"name": name, "parents": [parent]},
                                       media_body=self._media(data, mime), fields="id", **ALL).execute()["id"]

    def update(self, file_id, data, mime):
        self.svc.files().update(fileId=file_id, media_body=self._media(data, mime), **ALL).execute()

    def add_question(self, qid, files):
        """Create questions/<qid>/ holding files ({name: bytes}). Refuses to overwrite an existing question."""
        qfolder = self.folder("questions")
        if not qfolder:
            raise RuntimeError("the bank folder has no questions/ folder")
        if self.child(qfolder, qid):
            raise RuntimeError(f"questions/{qid} already exists in Drive")
        new = self.folder(qid, parent=qfolder, create=True)
        for name, data in files.items():
            mime = "text/yaml" if name.endswith(".yaml") else "image/png"
            self.write(new, name, data, mime)
        return new

    def question_file(self, qid):
        """The Drive file id of questions/<qid>/question.yaml, or None."""
        qfolder = self.folder("questions")
        sub = self.child(qfolder, qid, folder=True) if qfolder else None
        f = self.child(sub["id"], "question.yaml", folder=False) if sub else None
        return f["id"] if f else None

    def write_json(self, folder_name, name, obj):
        parent = self.folder(folder_name, create=True)
        return self.write(parent, name, json.dumps(obj, indent=1, ensure_ascii=False).encode("utf-8"),
                          "application/json")

    def read_json(self, folder_name, name):
        parent = self.folder(folder_name)
        f = self.child(parent, name, folder=False) if parent else None
        return json.loads(self.read_text(f["id"])) if f else None
