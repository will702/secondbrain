import json
import logging
import sys
import time
import uuid

_CONFIGURED = False

# Never log these keys/values — sensitive payloads stay server-side only.
_REDACTED_KEYS = {
    "password",
    "token",
    "access_token",
    "refresh_token",
    "credential",
    "credentials",
    "authorization",
    "cookie",
    "body_text",
    "content",
}


def _scrub(value: object) -> object:
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if k.lower() in _REDACTED_KEYS else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("request_id", "user_id", "job_id", "agent", "purpose", "document_id"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        extra = getattr(record, "data", None)
        if extra:
            payload["data"] = _scrub(extra)
        if record.exc_info and record.exc_info[0]:
            payload["exc"] = self.formatException(record.exc_info)[-2000:]
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").handlers = []  # route access logs through our format
    _CONFIGURED = True


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]
