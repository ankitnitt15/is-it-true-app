import sys
from pathlib import Path

# Same insertion main.py/pipeline_service.py do at import time -- needed here
# too because a test module can import shared/cache/etc. before either of
# those has run, and today that only works by accident of import order.
sys.path.insert(0, str(Path(__file__).parent / "pipeline"))

import pytest

from cache import report_cache
from limits import rate_limiter


@pytest.fixture(autouse=True)
def _reset_in_memory_state():
    """rate_limiter and report_cache fall back to module-level dicts when
    REDIS_URL is unset (true for the whole test run) -- without this,
    counters/cached reports from one test would leak into the next.
    """
    rate_limiter._memory_counts.clear()
    report_cache._memory_store.clear()
    yield
    rate_limiter._memory_counts.clear()
    report_cache._memory_store.clear()
