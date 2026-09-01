from shared.models import Report
from redis_client import client as _redis

_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days -- long enough that a viral forward
# stays a cache hit for everyone who pastes it after the first person, short
# enough that stale verdicts eventually expire rather than living forever.

_memory_store: dict[str, str] = {}


def _key(article_id: str) -> str:
    return f"report:{article_id}"


def get_report(article_id: str) -> Report | None:
    key = _key(article_id)
    raw = _redis.get(key) if _redis else _memory_store.get(key)
    if raw is None:
        return None
    return Report.model_validate_json(raw)


def save_report(article_id: str, report: Report) -> None:
    key = _key(article_id)
    raw = report.model_dump_json()
    if _redis:
        _redis.set(key, raw, ex=_TTL_SECONDS)
    else:
        _memory_store[key] = raw
