#!/usr/bin/env python3
"""Small, resumable MiniMax H3 V2 client using only the Python standard library.

The caller owns task persistence, polling, budgets and retries. In particular,
this module never retries a task submission. API contract checked 2026-09-12:
https://platform.minimax.cn/docs/api-reference/video-generation-v2-create
https://platform.minimax.cn/docs/api-reference/video-generation-v2-query
"""

from __future__ import annotations

import base64
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import shlex
import tempfile
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_BASE_URL = "https://api.minimax.cn"
MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
TASK_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "cancelled"})
MODEL_OPTIONS = {
    "MiniMax-H3": ({"768P", "2K"}, 4, 15),
    "MiniMax-H3-Max": ({"480P", "768P"}, 5, 15),
}


class MiniMaxError(RuntimeError):
    """A sanitized error; uncertain means a POST may have created a paid task."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
        uncertain: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.uncertain = uncertain


def load_env(path: str | Path, *, override: bool = False) -> dict[str, str]:
    """Read literal KEY=value settings, without shell execution or expansion.

    Blank lines, comments, optional ``export`` prefixes and quoted values work.
    Existing process variables win unless override=True. Parse all lines before
    changing the environment, and never include values in parse errors.
    """
    parsed: dict[str, str] = {}
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", stripped)
        if not match:
            raise MiniMaxError(f"Invalid environment setting on line {line_no}; expected KEY=value")
        key, value = match.groups()
        if value.startswith(("'", '"')):
            try:
                tokens = shlex.split(value, comments=True, posix=True)
            except ValueError:
                raise MiniMaxError(f"Invalid quoted environment setting on line {line_no}") from None
            if len(tokens) != 1:
                raise MiniMaxError(f"Invalid quoted environment setting on line {line_no}")
            value = tokens[0]
        else:
            # Inline comments require whitespace, preserving e.g. URL fragments.
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        parsed[key] = value
    for key, value in parsed.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return parsed


def build_i2v_payload(
    image_path: str | Path,
    prompt: str,
    *,
    model: str = "MiniMax-H3",
    duration: int = 5,
    resolution: str = "768P",
) -> dict[str, Any]:
    """Build one first-frame I2V request. The image determines the aspect ratio.

    Inputs are kept local until submit() is called. The caller should check
    image dimensions (256..5760 px and width/height 0.4..2.5) before submission.
    """
    _validate_generation_options(model, duration, resolution)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 7000:
        raise MiniMaxError("Prompt must contain 1 to 7000 characters")
    path = Path(image_path)
    size = path.stat().st_size
    if size == 0 or size > MAX_IMAGE_BYTES:
        raise MiniMaxError("Input image must be non-empty and at most 30 MB")
    mime = mimetypes.guess_type(path.name)[0]
    # MIME mappings for these formats vary between platforms.
    mime = {".heic": "image/heic", ".heif": "image/heif"}.get(path.suffix.lower(), mime)
    if mime not in {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}:
        raise MiniMaxError("Input image must be JPG, JPEG, PNG, WEBP, HEIC or HEIF")
    image_bytes = path.read_bytes()
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise MiniMaxError("Input image must be non-empty and at most 30 MB")
    return {
        "model": model,
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"},
                "role": "first_frame",
            },
        ],
        "duration": duration,
        "resolution": resolution,
        "ratio": "adaptive",
    }


def _validate_generation_options(model: str, duration: int, resolution: str) -> None:
    if not isinstance(model, str) or model not in MODEL_OPTIONS:
        raise MiniMaxError("Unsupported model; use MiniMax-H3 or MiniMax-H3-Max")
    resolutions, minimum, maximum = MODEL_OPTIONS[model]
    if not isinstance(duration, int) or isinstance(duration, bool) or not minimum <= duration <= maximum:
        raise MiniMaxError(f"Duration must be an integer from {minimum} to {maximum} seconds")
    if not isinstance(resolution, str) or resolution not in resolutions:
        raise MiniMaxError(f"Unsupported resolution for {model}")


def _check_http_url(url: str, *, base: bool = False) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        _ = parsed.port
    except (ValueError, TypeError):
        raise MiniMaxError("Invalid service or download URL") from None
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise MiniMaxError("Invalid service or download URL")
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise MiniMaxError("HTTPS is required except for localhost contract tests")
    if base and (parsed.query or parsed.path not in {"", "/"}):
        raise MiniMaxError("The API base URL must contain only scheme, host and optional port")
    return url.rstrip("/") if base else url


class _RejectAPIRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward an API key to a redirected origin or repeat a POST.
        return None


class _DownloadRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class MiniMaxClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        opener: Any = None,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("MINIMAX_API_KEY", "")
        if not isinstance(key, str) or not key.strip():
            raise MiniMaxError("Set MINIMAX_API_KEY to a pay-as-you-go API key before using MiniMax")
        if "\r" in key or "\n" in key:
            raise MiniMaxError("API key must be a single line")
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise MiniMaxError("Timeout must be a positive finite number of seconds")
        self._api_key = key.strip()
        self.base_url = _check_http_url(base_url, base=True)
        self.timeout = float(timeout)
        self._api_opener = opener or urllib.request.build_opener(_RejectAPIRedirects())
        self._download_opener = opener or urllib.request.build_opener(_DownloadRedirects())

    def _sanitize(self, message: Any) -> str:
        value = str(message).replace(self._api_key, "[REDACTED]")
        value = re.sub(r"(?i)Bearer\s+[^\s,;\"'}]+", "Bearer [REDACTED]", value)
        value = re.sub(r"data:[^\s,]+;base64,[A-Za-z0-9+/=]+", "[IMAGE REDACTED]", value)
        value = re.sub(r"(?i)(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[^\s,;\"'}]+", r"\1[REDACTED]", value)
        return value[:1200]

    def _json_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None
        if payload is not None:
            try:
                body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (TypeError, ValueError):
                raise MiniMaxError("Request payload must be valid JSON") from None
            if len(body) > MAX_REQUEST_BYTES:
                raise MiniMaxError("Request body exceeds the 64 MB API limit")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers={"Authorization": "Bearer " + self._api_key, "Content-Type": "application/json"},
            method=method,
        )
        uncertain = method == "POST"
        try:
            with self._api_opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            try:
                error_body = json.loads(exc.read(MAX_RESPONSE_BYTES).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, OSError):
                error_body = {}
            finally:
                exc.close()
            if not isinstance(error_body, dict):
                error_body = {}
            detail = error_body.get("error", {})
            message = detail.get("message", "Request rejected") if isinstance(detail, dict) else "Request rejected"
            request_id = error_body.get("request_id")
            raise MiniMaxError(
                f"MiniMax HTTP {exc.code}: {self._sanitize(message)}",
                status_code=exc.code,
                request_id=self._sanitize(request_id) if request_id is not None else None,
                uncertain=uncertain and (exc.code >= 500 or exc.code == 408),
            ) from None
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            # Never include the transport exception string: it can contain a URL,
            # authorization header or the serialized body from a custom opener.
            raise MiniMaxError(
                f"MiniMax transport failed ({type(exc).__name__}); submission was not retried",
                uncertain=uncertain,
            ) from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MiniMaxError("MiniMax returned an oversized response", uncertain=uncertain)
        try:
            result = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise MiniMaxError("MiniMax returned invalid JSON", uncertain=uncertain) from None
        if not isinstance(result, dict):
            raise MiniMaxError("MiniMax returned an invalid response object", uncertain=uncertain)
        if result.get("type") == "error" or "error" in result:
            detail = result.get("error", {})
            message = detail.get("message", "API error") if isinstance(detail, dict) else "API error"
            raise MiniMaxError(self._sanitize(message), uncertain=uncertain)
        return result

    def submit(self, payload: dict[str, Any]) -> str:
        """Submit exactly once. Persist the returned task ID before polling."""
        if not isinstance(payload, dict):
            raise MiniMaxError("Request payload must be an object")
        _validate_generation_options(payload.get("model"), payload.get("duration"), payload.get("resolution"))
        content = payload.get("content")
        if not isinstance(content, list) or not any(
            isinstance(item, dict) and item.get("type") == "text"
            and isinstance(item.get("text"), str) and 0 < len(item["text"].strip()) <= 7000
            for item in content
        ):
            raise MiniMaxError("Request content must contain a non-empty text prompt of at most 7000 characters")
        result = self._json_request("POST", "/v2/video_generation", payload)
        task_id = result.get("task_id")
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
            raise MiniMaxError("MiniMax response did not include a valid task_id", uncertain=True)
        return task_id

    def query(self, task_id: str) -> dict[str, Any]:
        """Query once and return the task object, including terminal failures."""
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
            raise MiniMaxError("Invalid task ID")
        result = self._json_request("GET", "/v2/query/video_generation/" + task_id)
        task = result.get("task")
        if not isinstance(task, dict) or task.get("status") not in TASK_STATUSES:
            raise MiniMaxError("MiniMax returned an invalid task status")
        if task.get("id") != task_id:
            raise MiniMaxError("MiniMax returned a different task ID")
        if task["status"] == "succeeded":
            content = task.get("content")
            if not isinstance(content, dict) or not isinstance(content.get("url"), str):
                raise MiniMaxError("Completed MiniMax task did not contain a video download URL")
            _check_http_url(content["url"])
        if isinstance(task.get("error"), dict):
            task["error"] = {
                "code": self._sanitize(task["error"].get("code", "")),
                "message": self._sanitize(task["error"].get("message", "")),
            }
        return task

    def list_tasks(self, *, page_num: int = 1, page_size: int = 20) -> dict[str, Any]:
        """Read-only authentication check/recovery aid; this creates no video."""
        if any(not isinstance(n, int) or isinstance(n, bool) or n < 1 for n in (page_num, page_size)):
            raise MiniMaxError("Task list page and size must be positive integers")
        query = urllib.parse.urlencode({"page_num": page_num, "page_size": page_size})
        return self._json_request("GET", "/v2/query/video_generation?" + query)

    def download(self, url: str, destination: str | Path, *, max_bytes: int = 512 * 1024 * 1024) -> Path:
        """Download a completed MP4 atomically, without sending the API key.

        Existing destination files are preserved. A failed download leaves no
        partial destination. The caller should additionally verify with ffprobe.
        """
        _check_http_url(url)
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 16:
            raise MiniMaxError("Download size limit must be at least 16 bytes")
        destination = Path(destination)
        if destination.exists():
            raise MiniMaxError("Download destination already exists; existing file was preserved")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with self._download_opener.open(urllib.request.Request(url, method="GET"), timeout=self.timeout) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/" in content_type or "json" in content_type:
                    raise MiniMaxError("Video download returned text instead of a video")
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".minimax-", suffix=".part", delete=False) as output:
                    temporary = output.name
                    size = 0
                    first_bytes = b""
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_bytes:
                            raise MiniMaxError("Video download exceeded the configured size limit")
                        if len(first_bytes) < 1024:
                            first_bytes += chunk[:1024 - len(first_bytes)]
                        output.write(chunk)
                    if size < 16 or b"ftyp" not in first_bytes:
                        raise MiniMaxError("Video download did not contain an MP4 file header")
                    output.flush()
                    os.fsync(output.fileno())
            # Do not overwrite a destination created while the request was open.
            if destination.exists():
                raise MiniMaxError("Download destination already exists; existing file was preserved")
            os.replace(temporary, destination)
            temporary = None
        except MiniMaxError:
            raise
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            exc.close()
            raise MiniMaxError(f"Video download failed (HTTP {status_code}); query the task to refresh its URL", status_code=status_code) from None
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise MiniMaxError(f"Video download failed ({type(exc).__name__})") from None
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        return destination
