"""Structured JSON logging with request IDs and secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import get_request_context

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (
        re.compile(r"(?i)\b(token|ticket|sig|refresh_token|access_token|password|signed_xdr)=([^&\s\"']+)"),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(
            r'(?i)"(token|ticket|refresh_token|access_token|password|new_password|current_password|signed_xdr)"\s*:\s*"[^"]*"'
        ),
        r'"\1": "[REDACTED]"',
    ),
    (re.compile(r"(?i)((?:__Secure-)?unifix_rt=)[^;\s]+"), r"\1[REDACTED]"),
    # Stellar secret seeds (S + 55 base32 characters), e.g. a mis-logged operator key.
    (re.compile(r"\bS[A-Z2-7]{55}\b"), "[REDACTED]"),
    (re.compile(r'(?i)"([a-z_]*secret[a-z_]*)"\s*:\s*"[^"]*"'), r'"\1": "[REDACTED]"'),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "dev_unredacted", False):
            # Only the development console email sender sets this; it cannot exist in production.
            return True
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = get_request_context()
        if context is not None:
            payload["request_id"] = context.request_id
        for key in ("method", "path", "status", "duration_ms", "user_id"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str, *, json_output: bool) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(
        JsonFormatter() if json_output else logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Our own middleware logs requests without query strings; uvicorn's access log would include them.
    logging.getLogger("uvicorn.access").disabled = True
