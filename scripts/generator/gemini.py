"""A small wrapper round the Gemini API (google-genai package): structured JSON replies, retries, a call cap.

The key is read from the GEMINI_API_KEY environment variable (a GitHub secret), never from a file.
"""
import json
import os
import time


class QuotaError(RuntimeError):
    """Gemini refused because the quota is used up, or this run reached its own call limit."""


class Gemini:
    def __init__(self, model, temperature=0.7, max_output_tokens=16000, max_calls=50):
        from google import genai  # imported here so tests can run without the package
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise SystemExit("GEMINI_API_KEY is not set. Add your Gemini API key as a repository secret.")
        self.client = genai.Client(api_key=key)
        self.model, self.temperature, self.max_output_tokens = model, temperature, max_output_tokens
        self.max_calls, self.calls, self.tokens = max_calls, 0, 0
        self._files = {}

    def upload(self, path, mime="application/pdf"):
        """Send a PDF to Gemini's file store once per run (files expire there after 48 hours)."""
        path = str(path)
        if path not in self._files:
            self._files[path] = self.client.files.upload(file=path, config={"mime_type": mime})
        return self._files[path]

    def ask(self, contents, schema, temperature=None):
        """contents: list of strings and uploaded files. Returns an instance of the Pydantic schema."""
        from google.genai import errors, types
        if self.calls >= self.max_calls:
            raise QuotaError(f"reached this run's limit of {self.max_calls} Gemini calls")
        config = types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=schema,
            temperature=self.temperature if temperature is None else temperature,
            max_output_tokens=self.max_output_tokens)
        delay = 20
        for attempt in range(4):
            self.calls += 1
            try:
                r = self.client.models.generate_content(model=self.model, contents=contents, config=config)
            except errors.APIError as e:
                code = getattr(e, "code", None)
                if code == 429 and "quota" in str(e).lower() and "per day" in str(e).lower():
                    raise QuotaError("Gemini daily quota used up") from e
                if code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
            usage = getattr(r, "usage_metadata", None)
            self.tokens += getattr(usage, "total_token_count", 0) or 0
            if getattr(r, "parsed", None) is not None:
                return r.parsed
            try:
                return schema.model_validate(json.loads(r.text))
            except Exception:  # noqa: BLE001 - a cut-off or malformed reply: try once more
                if attempt < 3:
                    continue
                raise
        raise RuntimeError("Gemini did not return a usable reply")
