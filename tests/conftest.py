import pytest
from app.services.redis_client import redis_client
import fakeredis.aioredis

@pytest.fixture(autouse=True)
def fake_redis_autouse():
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client._redis = fake
    yield fake
    redis_client._redis = None

@pytest.fixture
def fake_redis(fake_redis_autouse):
    return fake_redis_autouse
