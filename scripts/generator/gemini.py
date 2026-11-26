"""A small wrapper round the Gemini API (google-genai package): structured JSON replies, retries, a call cap.

Keys are read from environment variables (GitHub secrets), never from a file:
  GEMINI_API_KEY    the main key
  GEMINI_API_KEY2   optional backup key, used when the main one is out of credit or has hit its daily quota.
                    It can use a different model (backup_model), e.g. Flash for a free-tier key.
"""
import json
import os
import time

KEY_VARS = ("GEMINI_API_KEY", "GEMINI_API_KEY2")


class QuotaError(RuntimeError):
    """Gemini refused because the quota is used up, or this run reached its own call limit."""


CREDIT_MSG = ("Gemini credit used up: the API key's prepaid credit or billing limit is spent. Top up or raise the "
              "limit at https://aistudio.google.com (your project -> Billing), then run again")


def out_of_credit(e):
    """True for 'payment required' (402) and prepaid-credit / billing errors from Gemini."""
    text = str(e).lower()
    return getattr(e, "code", None) == 402 or "prepayment" in text or "credits are depleted" in text \
        or "billing" in text and "resource_exhausted" in text


def daily_quota(e):
    text = str(e).lower()
    return getattr(e, "code", None) == 429 and "quota" in text and "per day" in text


class Upload:
    """A file to send with a request. It is uploaded lazily, once per key, because an uploaded file belongs to the
    key (project) that uploaded it and cannot be used after switching to the backup key."""

    def __init__(self, path, mime):
        self.path, self.mime = str(path), mime


class Gemini:
    def __init__(self, model, temperature=0.7, max_output_tokens=16000, max_calls=50, backup_model=None,
                 busy_fallback=None, backup_busy_fallback=None):
        self.keys = [(v, os.environ.get(v, "").strip()) for v in KEY_VARS]
        self.keys = [(v, k) for v, k in self.keys if k]
        if not self.keys:
            raise SystemExit("GEMINI_API_KEY is not set. Add your Gemini API key as a repository secret.")
        self.model, self.temperature, self.max_output_tokens = model, temperature, max_output_tokens
        self.backup_model = backup_model
        # Model to switch to when Google says the current one is busy (503), for the main and the backup key.
        self.busy_fallbacks = [busy_fallback, backup_busy_fallback]
        self.max_calls, self.calls = max_calls, 0
        self.tokens = self.input_tokens = self.output_tokens = 0
        self.usage = []                        # [input, output] tokens for each key, for the cost estimate
        self.key_index = -1
        self._next_key()

    def _make_client(self, key):
        from google import genai  # imported here so tests can run without the package
        # Preview models (e.g. gemini-3.1-pro-preview) are only served on the v1beta API, and newer versions of
        # the google-genai package default to v1, so ask for v1beta explicitly.
        return genai.Client(api_key=key, http_options={"api_version": "v1beta"})

    def _next_key(self):
        """Move to the next key. Returns False when there is none left."""
        if self.key_index + 1 >= len(self.keys):
            return False
        self.key_index += 1
        name, key = self.keys[self.key_index]
        self.client = self._make_client(key)
        self._files = {}                       # uploads made with the previous key can't be used
        self.usage.append([0, 0])
        if self.key_index:
            if self.backup_model:
                self.model = self.backup_model
            print(f"::warning::Switched to the backup Gemini key ({name}), model {self.model}.", flush=True)
        return True

    def cost(self, prices):
        """Estimated US dollars: prices is a list of {input, output} per million tokens, one per key."""
        total = 0.0
        for i, (used_in, used_out) in enumerate(self.usage):
            p = prices[min(i, len(prices) - 1)] or {"input": 0, "output": 0}
            total += (used_in * p["input"] + used_out * p["output"]) / 1e6
        return total

    def _busy_fallback(self):
        """Switch to this key's 'busy' fallback model once. Returns True if switched."""
        fallback = self.busy_fallbacks[min(self.key_index, len(self.busy_fallbacks) - 1)]
        if not fallback or fallback == self.model:
            return False
        print(f"::warning::{self.model} is busy (Google 503); switching to {fallback}.", flush=True)
        self.model = fallback
        return True

    @property
    def key_name(self):
        return self.keys[self.key_index][0]

    def _refused(self, e):
        """Called when Gemini refuses for credit or daily quota: switch key if possible, else raise QuotaError."""
        reason = CREDIT_MSG if out_of_credit(e) else "Gemini daily quota used up"
        print(f"::warning::{self.key_name}: {reason.split(':')[0]}.", flush=True)
        if not self._next_key():
            raise QuotaError(reason + (" (on every key)" if len(self.keys) > 1 else "")) from e

    def upload(self, path, mime="application/pdf"):
        """A PDF to attach to requests. Checks now that it can be sent, so problems show up early."""
        item = Upload(path, mime)
        self._resolve(item)
        return item

    def _resolve(self, item):
        """The uploaded-file object for item with the current key (uploading it if needed)."""
        if not isinstance(item, Upload):
            return item
        while item.path not in self._files:
            try:
                self._files[item.path] = self.client.files.upload(file=item.path, config={"mime_type": item.mime})
            except Exception as e:  # noqa: BLE001
                if out_of_credit(e) or daily_quota(e):
                    self._refused(e)          # switches key and loops, or raises QuotaError
                    continue
                raise
        return self._files[item.path]

    def available_models(self):
        """Names of the models that can write text with this key (model names are not secret)."""
        try:
            return sorted(m.name.removeprefix("models/") for m in self.client.models.list()
                          if "generateContent" in (getattr(m, "supported_actions", None) or []))
        except Exception:  # noqa: BLE001
            return []

    def ask(self, contents, schema, temperature=None):
        """contents: list of strings and uploads. Returns an instance of the Pydantic schema."""
        from google.genai import errors, types
        if self.calls >= self.max_calls:
            raise QuotaError(f"reached this run's limit of {self.max_calls} Gemini calls")
        config = types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=schema,
            temperature=self.temperature if temperature is None else temperature,
            max_output_tokens=self.max_output_tokens)
        delay, attempt, busy = 20, 0, 0
        while attempt < 4:
            parts = [self._resolve(c) for c in contents]
            self.calls += 1
            try:
                r = self.client.models.generate_content(model=self.model, contents=parts, config=config)
            except errors.APIError as e:
                code = getattr(e, "code", None)
                if out_of_credit(e) or daily_quota(e):
                    self._refused(e)          # switched key: try the same request again
                    continue
                if code == 404:
                    raise SystemExit(f"Gemini model {self.model!r} was not found. Models this key can use: "
                                     f"{', '.join(self.available_models()) or '(could not list them)'}. "
                                     "Change 'model:' in generator.yaml.") from e
                attempt += 1
                busy = busy + 1 if code == 503 else 0
                if busy >= 2 and self._busy_fallback():
                    delay, attempt, busy = 20, 0, 0   # fresh retries on the other model
                    continue
                if code in (429, 500, 502, 503, 504) and attempt < 4:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
            attempt += 1
            usage = getattr(r, "usage_metadata", None)
            self.tokens += getattr(usage, "total_token_count", 0) or 0
            used_in = getattr(usage, "prompt_token_count", 0) or 0
            used_out = (getattr(usage, "candidates_token_count", 0) or 0) + \
                (getattr(usage, "thoughts_token_count", 0) or 0)
            self.input_tokens += used_in
            self.output_tokens += used_out
            self.usage[self.key_index][0] += used_in
            self.usage[self.key_index][1] += used_out
            if getattr(r, "parsed", None) is not None:
                return r.parsed
            try:
                return schema.model_validate(json.loads(r.text))
            except Exception:  # noqa: BLE001 - a cut-off or malformed reply: try once more
                if attempt < 4:
                    continue
                raise
        raise RuntimeError("Gemini did not return a usable reply")
