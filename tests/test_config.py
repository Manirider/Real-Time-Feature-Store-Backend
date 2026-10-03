"""Unit tests for configuration validation and settings loading."""

import pytest
from pydantic import ValidationError
from app.config import Settings


def test_default_settings():
    """Verify default configuration values."""
    s = Settings()
    assert s.redis_host == "redis"
    assert s.redis_port == 6379
    assert s.api_host == "0.0.0.0"
    assert s.api_port == 8000
    assert s.ingestion_batch_size == 500
    assert s.ingestion_interval_sec == 0.5
    assert s.ingestion_target_users == 100000


def test_custom_settings():
    """Verify custom configuration overrides."""
    s = Settings(
        redis_host="localhost",
        redis_port=6380,
        api_port=9000,
        ingestion_batch_size=1000,
        ingestion_interval_sec=1.0,
        ingestion_target_users=50000,
    )
    assert s.redis_host == "localhost"
    assert s.redis_port == 6380
    assert s.api_port == 9000
    assert s.ingestion_batch_size == 1000
    assert s.ingestion_interval_sec == 1.0
    assert s.ingestion_target_users == 50000


def test_invalid_settings():
    """Verify validation triggers error for invalid port or batch size."""
    with pytest.raises(ValidationError):
        Settings(redis_port=-1)

    with pytest.raises(ValidationError):
        Settings(ingestion_batch_size=0)
