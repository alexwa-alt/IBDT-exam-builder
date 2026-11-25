"""Turn the build output into the public, password-protected site.

Copies the site code (site/) into the output folder and adds the question data and images, each encrypted
separately with the staff password. Nothing readable about the questions is written in the clear.

  password --PBKDF2-HMAC-SHA256 (600,000 rounds, random 16-byte salt)--> 256-bit key
  each file --AES-256-GCM (fresh random 12-byte nonce)--> data/enc/<random name>.bin  (nonce + ciphertext)

data/lock.json (public) holds only the salt, the number of rounds, the format version, an encrypted "check"
value the browser uses to test a password, and the random name of the encrypted index. The index maps the
real file names (questions.json, images/<id>_q1.png, ...) to their random names.

Usage: SITE_PASSWORD=... python scripts/encrypt_site.py [--build build] [--site site] [--out public]
"""
import argparse
import base64
import datetime
import json
import os
import secrets
import shutil
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent.parent
VERSION = 1
ITERATIONS = 600_000
CHECK_TEXT = b"dt-bank password check"   # the browser decrypts this to test a password
DATA_FILES = ["questions.json", "tags.json", "syllabus.json"]


def b64(b):
    return base64.b64encode(b).decode("ascii")


def derive_key(password, salt, iterations=ITERATIONS):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def seal(aes, data):
    nonce = secrets.token_bytes(12)
    return nonce + aes.encrypt(nonce, data, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default=str(ROOT / "build"))
    ap.add_argument("--site", default=str(ROOT / "site"))
    ap.add_argument("--out", default=str(ROOT / "public"))
    args = ap.parse_args()
    build, site, out = Path(args.build), Path(args.site), Path(args.out)

    password = os.environ.get("SITE_PASSWORD", "")
    if not password:
        sys.exit("SITE_PASSWORD is not set. Set it to the staff password, for example:\n"
                 "  SITE_PASSWORD='...' python scripts/encrypt_site.py")
    if len(password) < 8:
        print("warning: the site password is shorter than 8 characters, which makes it easy to guess",
              file=sys.stderr)
    for f in DATA_FILES:
        if not (build / "data" / f).exists():
            sys.exit(f"{build / 'data' / f} is missing. Run syllabus_import.py and build_bank.py first.")

    # 1. Fresh output folder holding the site code only (never site/data, which holds unencrypted files).
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(site, out, ignore=shutil.ignore_patterns("data", ".*"))
    (out / ".nojekyll").write_text("")          # tells GitHub Pages to serve the files as they are
    enc = out / "data" / "enc"
    enc.mkdir(parents=True)

    # 2. Key and cipher.
    salt = secrets.token_bytes(16)
    aes = AESGCM(derive_key(password, salt))

    # 3. Encrypt each file under a random name.
    files = {}

    def put(real_name, data):
        name = secrets.token_hex(16) + ".bin"
        (enc / name).write_bytes(seal(aes, data))
        files[real_name] = name

    for f in DATA_FILES:
        put(f, (build / "data" / f).read_bytes())
    # Optional: a fine-grained GitHub token (Actions: read and write on this repository only) that lets the
    # site's Generate and Review buttons start workflows. Encrypted like everything else.
    token = os.environ.get("GEN_DISPATCH_TOKEN", "").strip()
    if token:
        put("dispatch.json", json.dumps({"token": token, "repo": os.environ.get("GITHUB_REPOSITORY", ""),
                                         "ref": os.environ.get("GITHUB_REF_NAME", "main")}).encode("utf-8"))
    questions = json.loads((build / "data" / "questions.json").read_text(encoding="utf-8"))
    for q in questions:
        for page in q["pages"] + q["ms"]:
            put(page["image"], (build / page["image"]).read_bytes())

    index = {"version": VERSION, "files": files,
             "built": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    index_name = secrets.token_hex(16) + ".bin"
    (enc / index_name).write_bytes(seal(aes, json.dumps(index).encode("utf-8")))

    # 4. The only public, unencrypted data file.
    lock = {"version": VERSION, "kdf": "PBKDF2-HMAC-SHA256", "iterations": ITERATIONS, "salt": b64(salt),
            "cipher": "AES-256-GCM", "check": b64(seal(aes, CHECK_TEXT)), "index": index_name}
    (out / "data" / "lock.json").write_text(json.dumps(lock, indent=1), encoding="utf-8")
    print(f"encrypted {len(files)} files ({len(questions)} questions) into {enc}")


if __name__ == "__main__":
    main()
