"""Logging Configuration
========================
Dual-output logging system:
  1. Console: real-time colored output (StreamHandler)
  2. File:    timed rotating logs (TimedRotatingFileHandler)
     - Flush to disk every 60 seconds (via flush interval)
     - Rotate daily (midnight), keep 30 days of history
     - File location: backend/logs/gaokao-app.log

Usage:
  from logging_config import setup_logging, get_logger
  setup_logging()  # call once at startup
  logger = get_logger("module-name")
  logger.info("...")

Middleware:
  RequestLoggingMiddleware — auto-logs every HTTP request
  (method, path, status_code, duration_ms)
"""

import logging
import sys
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# ── Log directory ──
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "gaokao-app.log"

# ── Format ──
# Console: concise, human-readable
CONSOLE_FMT = "%(asctime)s │ %(levelname)-5s │ %(name)-12s │ %(message)s"
# File:    full detail, machine-parseable
FILE_FMT = "%(asctime)s │ %(levelname)-5s │ %(name)-12s │ %(filename)s:%(lineno)d │ %(message)s"

# ── Date format ──
DATE_FMT = "%Y-%m-%d %H:%M:%S"


# ============================================
# Custom formatter with ANSI colors for console
# ============================================

class ColorFormatter(logging.Formatter):
    """Add ANSI colors to log level for terminal output."""

    COLORS = {
        logging.DEBUG:    "\033[36m",   # cyan
        logging.INFO:     "\033[32m",   # green
        logging.WARNING:  "\033[33m",   # yellow
        logging.ERROR:    "\033[31m",   # red
        logging.CRITICAL: "\033[35m",   # magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


# ============================================
# Flush-aware file handler
# ============================================

class FlushingTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    TimedRotatingFileHandler that flushes to disk on every emit.

    Standard TimedRotatingFileHandler buffers writes and only flushes
    when the buffer is full or the file is closed. This subclass
    forces an immediate flush after each log record, ensuring logs
    are written to disk within milliseconds rather than seconds.

    Rotation: midnight, keep 30 backup days.
    """

    def __init__(self, filename, **kwargs):
        kwargs.setdefault("when", "midnight")
        kwargs.setdefault("interval", 1)
        kwargs.setdefault("backupCount", 30)
        kwargs.setdefault("encoding", "utf-8")
        super().__init__(filename, **kwargs)

    def emit(self, record):
        super().emit(record)
        self.flush()


# ============================================
# Setup function — call once at startup
# ============================================

_root_logger_setup = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root 'gaokao-app' logger with console + file handlers.

    Call this once at application startup (before any other module
    creates loggers). After setup, use get_logger() to create
    child loggers.

    Args:
        level: Minimum log level (default: INFO)
    """
    global _root_logger_setup
    if _root_logger_setup:
        return  # prevent double-setup

    root = logging.getLogger("gaokao-app")
    root.setLevel(level)

    # Prevent propagation to root logger (avoids duplicate console output)
    root.propagate = False

    # ── Console handler ──
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(ColorFormatter(CONSOLE_FMT, datefmt=DATE_FMT))
    root.addHandler(console)

    # ── File handler (flushing + daily rotation) ──
    file_handler = FlushingTimedRotatingFileHandler(
        str(LOG_FILE),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(FILE_FMT, datefmt=DATE_FMT))
    root.addHandler(file_handler)

    # ── Also configure uvicorn access log to use our format ──
    uvicorn_logger = logging.getLogger("uvicorn.access")
    uvicorn_logger.setLevel(logging.WARNING)  # suppress noisy access logs
    uvicorn_logger.propagate = False

    _root_logger_setup = True

    root.info("=" * 60)
    root.info("Logging system initialized")
    root.info("  Console: real-time colored output (stdout)")
    root.info("  File:    %s (daily rotation, 30-day retention)", LOG_FILE)
    root.info("  Flush:   immediate (every emit)")
    root.info("=" * 60)


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the 'gaokao-app' hierarchy.

    Args:
        name: Sub-module name (e.g., 'llm', 'auth', 'api')

    Returns:
        Logger instance named 'gaokao-app.<name>'
    """
    return logging.getLogger(f"gaokao-app.{name}")


# ============================================
# Request logging middleware (for FastAPI)
# ============================================

class RequestLoggingMiddleware:
    """ASGI middleware that logs every HTTP request with duration.

    Logs format:
      [HTTP] GET /api/health → 200 (12ms)
      [HTTP] POST /api/generate → 200 (3456ms)
      [HTTP] POST /api/auth/login → 401 (5ms) ⚠

    Usage:
      app = FastAPI()
      app.add_middleware(RequestLoggingMiddleware)
    """

    def __init__(self, app, logger_name: str = "gaokao-app.http"):
        self.app = app
        self.logger = logging.getLogger(logger_name)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract request info
        method = scope.get("method", "?")
        path = scope.get("path", "?")
        start_time = time.monotonic()

        # Intercept response to capture status code
        # Use a mutable list to avoid closure variable assignment issue
        status_holder = [None]

        async def send_with_status(message):
            if message["type"] == "http.response.start":
                status_holder[0] = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            self.logger.error(
                "[HTTP] %s %s → EXCEPTION (%dms) %s",
                method, path, duration_ms, exc,
            )
            raise

        duration_ms = int((time.monotonic() - start_time) * 1000)
        status_code = status_holder[0]

        # Choose log level based on status code
        if status_code is None:
            level = logging.WARNING
            status_str = "???"
        elif status_code < 400:
            level = logging.INFO
            status_str = str(status_code)
        elif status_code < 500:
            level = logging.WARNING
            status_str = f"{status_code} ⚠"
        else:
            level = logging.ERROR
            status_str = f"{status_code} ✗"

        self.logger.log(
            level,
            "[HTTP] %s %s → %s (%dms)",
            method, path, status_str, duration_ms,
        )
