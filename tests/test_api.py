"""Unit and contract tests for the Real-Time Feature Store API endpoints."""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.redis_client import redis_client


@pytest.mark.asyncio
async def test_health_ok():
    """Verify GET /health returns 200 and status ok when Redis is available."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_redis_down():
    """Verify GET /health returns 503 when Redis ping fails."""
    # Temporarily disconnect Redis client
    original_redis = redis_client._redis
    redis_client._redis = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/health")
            assert resp.status_code == 503
            assert resp.json()["detail"] == "Redis unavailable"
    finally:
        redis_client._redis = original_redis


@pytest.mark.asyncio
async def test_get_user_success(fake_redis):
    """Verify GET /features/{user_id} returns 200 and complete feature hash."""
    features = {
        "age": "28",
        "account_tier": "premium",
        "total_purchases": "42",
        "avg_order_value": "89.50",
        "is_active": "true",
    }
    await fake_redis.hset("user:user_123:features", mapping=features)
    await fake_redis.sadd("all_users", "user_123")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/features/user_123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user_123"
        assert data["features"] == features


@pytest.mark.asyncio
async def test_get_user_not_found():
    """Verify GET /features/{user_id} returns 404 for unknown users."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/features/nonexistent_user")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_user_invalid_ids():
    """Verify GET /features/{user_id} returns 400 for empty or excessively long IDs."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Whitespace-only ID
        resp = await ac.get("/features/%20%20")
        assert resp.status_code == 400
        assert "Invalid user_id" in resp.json()["detail"]

        # Oversized ID (> 128 characters)
        long_id = "u" * 129
        resp = await ac.get(f"/features/{long_id}")
        assert resp.status_code == 400
        assert "Invalid user_id" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_batch_success(fake_redis):
    """Verify POST /features/batch returns ordered features for existing users."""
    await fake_redis.hset("user:u1:features", mapping={"age": "21"})
    await fake_redis.sadd("all_users", "u1")
    await fake_redis.hset("user:u2:features", mapping={"age": "34"})
    await fake_redis.sadd("all_users", "u2")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/features/batch", json={"user_ids": ["u1", "u2"]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["user_id"] == "u1"
        assert data[0]["features"] == {"age": "21"}
        assert data[1]["user_id"] == "u2"
        assert data[1]["features"] == {"age": "34"}


@pytest.mark.asyncio
async def test_batch_mixed_valid_and_missing(fake_redis):
    """Verify missing users in batch return empty features without failing the request."""
    await fake_redis.hset("user:u1:features", mapping={"age": "25"})
    await fake_redis.sadd("all_users", "u1")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/features/batch", json={"user_ids": ["u1", "missing_user"]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["user_id"] == "u1"
        assert data[0]["features"]["age"] == "25"
        assert data[1]["user_id"] == "missing_user"
        assert data[1]["features"] == {}


@pytest.mark.asyncio
async def test_batch_duplicates(fake_redis):
    """Verify batch request containing duplicate IDs preserves request order."""
    await fake_redis.hset("user:u1:features", mapping={"age": "40"})
    await fake_redis.sadd("all_users", "u1")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/features/batch", json={"user_ids": ["u1", "u1", "missing"]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        assert data[0]["user_id"] == "u1"
        assert data[0]["features"] == {"age": "40"}
        assert data[1]["user_id"] == "u1"
        assert data[1]["features"] == {"age": "40"}
        assert data[2]["user_id"] == "missing"
        assert data[2]["features"] == {}


@pytest.mark.asyncio
async def test_batch_empty_payload_rejected():
    """Verify empty user_ids array is rejected with 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/features/batch", json={"user_ids": []})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_batch_missing_payload_rejected():
    """Verify empty JSON object is rejected with 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/features/batch", json={})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_batch_too_many_ids_rejected():
    """Verify requests exceeding 100 user IDs are rejected with 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/features/batch", json={"user_ids": [f"u_{i}" for i in range(101)]})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_batch_invalid_types_rejected():
    """Verify non-string elements in user_ids are rejected with 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/features/batch", json={"user_ids": [123]})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_batch_whitespace_id_rejected():
    """Verify whitespace-only IDs inside batch are rejected with 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/features/batch", json={"user_ids": ["valid_user", "   "]})
        assert resp.status_code == 422
