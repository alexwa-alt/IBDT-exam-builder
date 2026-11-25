"""Open the encrypted requests the staff site sends to GitHub Actions (Generate and Review buttons).

Workflow inputs are visible to anyone on this public repository's Actions tab, so the site encrypts each
request with the same key it uses to read the bank: PBKDF2(staff password, the site's public salt) -> AES-GCM.
The workflow knows the password (the SITE_PASSWORD secret), so it can rebuild the key and open the request.
Anyone without the password sees only scrambled text.

A request is base64(JSON {"v": 1, "salt": b64, "iterations": n, "data": b64(nonce + ciphertext)}).
The decrypted JSON must hold "kind" and "sent" (milliseconds since 1970); requests older than two days are refused.
"""
import base64
import json
import os
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parent))
from encrypt_site import derive_key  # noqa: E402

MAX_AGE_S = 2 * 24 * 3600


class BadRequest(ValueError):
    pass


def open_request(text, kind, password=None):
    password = password if password is not None else os.environ.get("SITE_PASSWORD", "")
    if not password:
        raise BadRequest("SITE_PASSWORD is not set")
    try:
        env = json.loads(base64.b64decode(text.strip()))
        salt = base64.b64decode(env["salt"])
        iterations = int(env["iterations"])
        blob = base64.b64decode(env["data"])
        if env.get("v") != 1 or not 100_000 <= iterations <= 5_000_000 or len(salt) != 16:
            raise ValueError("unexpected format")
        plain = AESGCM(derive_key(password, salt, iterations)).decrypt(blob[:12], blob[12:], None)
        req = json.loads(plain)
    except Exception as e:  # noqa: BLE001 - any failure means "not a request from the site"
        raise BadRequest("the request could not be opened (wrong password or damaged)") from e
    if req.get("kind") != kind:
        raise BadRequest(f"this is not a {kind} request")
    age = time.time() - float(req.get("sent", 0)) / 1000
    if not -600 < age < MAX_AGE_S:
        raise BadRequest("the request is too old; send it again from the site")
    return req


def seal_request(req, password, salt, iterations):
    """The Python twin of the site's code, used by the tests."""
    import secrets
    nonce = secrets.token_bytes(12)
    blob = nonce + AESGCM(derive_key(password, salt, iterations)).encrypt(nonce, json.dumps(req).encode(), None)
    env = {"v": 1, "salt": base64.b64encode(salt).decode(), "iterations": iterations,
           "data": base64.b64encode(blob).decode()}
    return base64.b64encode(json.dumps(env).encode()).decode()
