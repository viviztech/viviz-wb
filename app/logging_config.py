import logging
import json
import uuid
import time
from contextvars import ContextVar
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get("-"),
        }
        if record.exc_info:
            log["exc"] = self.formatException(record.exc_info)
        return json.dumps(log, ensure_ascii=False)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        token = request_id_var.set(rid)
        start = time.monotonic()
        response = await call_next(request)
        elapsed = round((time.monotonic() - start) * 1000)
        response.headers["X-Request-ID"] = rid
        logging.getLogger("access").info(
            f"{request.method} {request.url.path} {response.status_code} {elapsed}ms"
        )
        request_id_var.reset(token)
        return response


def configure_logging():
    fmt = JSONFormatter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    try:
        file_handler = logging.FileHandler("logs/app.log")
        file_handler.setFormatter(fmt)
        handlers = [stream_handler, file_handler]
    except OSError:
        handlers = [stream_handler]

    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    # Suppress noisy third-party loggers
    for name in ("uvicorn.access", "httpx", "apscheduler.executors"):
        logging.getLogger(name).setLevel(logging.WARNING)
