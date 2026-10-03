"""Unit tests for Redis data access layer and data structures."""

import pytest
from app.services.redis_client import redis_client


@pytest.mark.asyncio
async def test_redis_key_format():
    """Verify Redis key formatting conforms to the user:{id}:features pattern."""
    assert redis_client.key_for_user("12345") == "user:12345:features"
    assert redis_client.key_for_user("user_00000001") == "user:user_00000001:features"


@pytest.mark.asyncio
async def test_user_exists(fake_redis):
    """Verify user_exists checks membership in the all_users set."""
    await fake_redis.sadd("all_users", "user_alpha")
    assert await redis_client.user_exists("user_alpha") is True
    assert await redis_client.user_exists("user_beta") is False


@pytest.mark.asyncio
async def test_get_user_features(fake_redis):
    """Verify get_user_features retrieves all hash fields for a member user."""
    features = {"age": "29", "tier": "premium"}
    await fake_redis.hset("user:user_active:features", mapping=features)
    await fake_redis.sadd("all_users", "user_active")

    result = await redis_client.get_user_features("user_active")
    assert result == features


@pytest.mark.asyncio
async def test_get_user_features_missing(fake_redis):
    """Verify get_user_features returns None for non-existent users."""
    result = await redis_client.get_user_features("nonexistent_user")
    assert result is None


@pytest.mark.asyncio
async def test_set_user_features(fake_redis):
    """Verify set_user_features writes to Hash and registers user in all_users Set."""
    features = {"lifetime_value": "1500.50", "category": "electronics"}
    await redis_client.set_user_features("user_new", features)

    # Verify global set registration
    assert bool(await fake_redis.sismember("all_users", "user_new")) is True
    # Verify hash contents
    stored = await fake_redis.hgetall("user:user_new:features")
    assert stored == features


@pytest.mark.asyncio
async def test_batch_features_order_and_missing(fake_redis):
    """Verify get_batch_features maintains exact order and populates empty dicts for missing users."""
    await fake_redis.hset("user:user_a:features", mapping={"score": "10"})
    await fake_redis.sadd("all_users", "user_a")
    await fake_redis.hset("user:user_b:features", mapping={"score": "20"})
    await fake_redis.sadd("all_users", "user_b")

    query_order = ["user_b", "missing_user", "user_a"]
    result = await redis_client.get_batch_features(query_order)

    assert result["user_b"] == {"score": "20"}
    assert result["missing_user"] == {}
    assert result["user_a"] == {"score": "10"}


@pytest.mark.asyncio
async def test_batch_features_deduplication(fake_redis):
    """Verify get_batch_features handles duplicate keys cleanly."""
    await fake_redis.hset("user:user_dup:features", mapping={"tier": "gold"})
    await fake_redis.sadd("all_users", "user_dup")

    result = await redis_client.get_batch_features(["user_dup", "user_dup"])
    assert result["user_dup"] == {"tier": "gold"}


@pytest.mark.asyncio
async def test_redis_data_types(fake_redis):
    """Verify strict Redis data types: features MUST be hash, all_users MUST be set."""
    await fake_redis.hset("user:type_check:features", mapping={"val": "1"})
    await fake_redis.sadd("all_users", "type_check")

    assert await fake_redis.type("user:type_check:features") == "hash"
    assert await fake_redis.type("all_users") == "set"
