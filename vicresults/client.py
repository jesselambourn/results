"""HTTP client for the Analysis API.

Rules this client enforces (from the API brief):
- One host only: https://2026.victoriansocialists.org.au. Anything else is refused.
- The bearer token comes from the ANALYSIS_TOKEN environment variable and is
  never printed, logged or included in exception messages.
- Long timeout (60 s default, never under 30 s) and the whole body is read
  before parsing, since a full count is ~11 MB streamed over ~3 s.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://2026.victoriansocialists.org.au"
ALLOWED_HOST = urllib.parse.urlparse(BASE_URL).netloc
SAMPLES = ("6pm", "7pm", "10pm", "final")
MIN_TIMEOUT = 30.0


class AnalysisError(Exception):
    """Any non-200 answer from the API. `status` is the HTTP code, `body` the parsed JSON error."""

    def __init__(self, status: int, message: str, body: dict[str, Any] | None = None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message
        self.body = body or {}


class BadSampleError(AnalysisError):
    """400: unknown sample value."""


class AuthError(AnalysisError):
    """401: missing or wrong token. Polling should stop; retrying won't help."""


class NotReadyError(AnalysisError):
    """404: no feed files archived yet (normal before 6 pm Saturday). Retry later."""


class SchemaMismatchError(AnalysisError):
    """500: converted files didn't match the schema. Retry next poll and tell Angus."""

    @property
    def issues(self) -> list[dict[str, Any]]:
        return list(self.body.get("issues") or [])


_ERRORS = {400: BadSampleError, 401: AuthError, 404: NotReadyError, 500: SchemaMismatchError}


class AnalysisClient:
    def __init__(self, token: str | None = None, timeout: float = 60.0, base_url: str = BASE_URL):
        if urllib.parse.urlparse(base_url).netloc != ALLOWED_HOST or not base_url.startswith("https://"):
            raise ValueError(f"Only {BASE_URL} may be used")
        self._token = token if token is not None else os.environ.get("ANALYSIS_TOKEN")
        if not self._token:
            raise RuntimeError("ANALYSIS_TOKEN is not set")
        self.base_url = base_url.rstrip("/")
        self.timeout = max(float(timeout), MIN_TIMEOUT)

    def __repr__(self) -> str:  # never show the token
        return f"AnalysisClient(base_url={self.base_url!r}, timeout={self.timeout})"

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "User-Agent": "vicresults-client/1",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()  # read the whole body before parsing
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                body = json.loads(raw)
            except ValueError:
                body = {"error": raw[:500].decode("utf-8", "replace")}
            if not isinstance(body, dict):
                body = {"error": str(body)}
            cls = _ERRORS.get(e.code, AnalysisError)
            raise cls(e.code, str(body.get("error", e.reason)), body) from None

    def openapi(self) -> dict[str, Any]:
        """The OpenAPI 3.1 contract. components.schemas.Analysis is the response schema."""
        return self._get("/api/analysis/openapi.json")

    def analysis(self, sample: str | None = None) -> dict[str, Any]:
        """Latest converted VEC feed. Pass sample (6pm, 7pm, 10pm, final) for 2022 test data."""
        if sample is not None and sample not in SAMPLES:
            raise ValueError(f"sample must be one of {SAMPLES}")
        return self._get("/api/analysis", {"sample": sample} if sample else None)


def validate(data: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    """Check a response against components.schemas.Analysis. Returns a list of problems (empty = OK).

    Needs the optional `jsonschema` package; returns [] with a note if it's missing.
    """
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        return ["jsonschema not installed; skipped validation"]
    schema = dict(contract["components"]["schemas"]["Analysis"])
    schema["components"] = contract["components"]  # let internal $refs resolve
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in validator.iter_errors(data)]


def is_sample(data: dict[str, Any]) -> bool:
    """True when the response is 2022 sample data (file names start State2022)."""
    return any(str(v).startswith("State2022") for v in (data.get("files") or {}).values())
