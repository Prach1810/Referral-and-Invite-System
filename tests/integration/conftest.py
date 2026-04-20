import pytest
import os
from app.core.redis import get_redis


def pytest_configure(config):
    os.environ["TESTING"] = "1"


@pytest.fixture(autouse=True)
def flush_redis_before_each_test():
    redis = get_redis()
    redis.flushdb()
    yield