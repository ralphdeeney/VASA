import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    """Only emit controlled event fields; exception messages and arguments may hold secrets."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "event": getattr(record, "event", "log_event"),
                "exception_type": type(record.exc_info[1]).__name__ if record.exc_info else None,
            }
        )


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("vasa")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
