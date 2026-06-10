import logging
import time
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger("app.perf")


@contextmanager
def perf_span(name: str, **fields: object) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.exception("PERF %s failed elapsed_ms=%.1f %s", name, elapsed_ms, _format_fields(fields))
        raise
    else:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info("PERF %s elapsed_ms=%.1f %s", name, elapsed_ms, _format_fields(fields))


def _format_fields(fields: dict[str, object]) -> str:
    return " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
