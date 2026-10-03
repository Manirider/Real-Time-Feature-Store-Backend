"""Unit tests for the feature ingestion script and synthetic feature generator."""

from datetime import datetime
import fakeredis
from scripts.ingest_features import (
    ACCOUNT_TIERS,
    CATEGORIES,
    DEVICE_TYPES,
    generate_features,
    populate_initial_users,
)


def test_generate_features_schema():
    """Verify that generated features contain all required numeric, categorical, boolean, and timestamp fields."""
    user_id = "user_00000042"
    features = generate_features(user_id)

    expected_keys = {
        "age",
        "account_tier",
        "total_purchases",
        "avg_order_value",
        "is_active",
        "session_count_30d",
        "days_since_last_purchase",
        "preferred_category",
        "device_type",
        "lifetime_value",
        "last_login_timestamp",
    }
    assert set(features.keys()) == expected_keys

    # Type & range assertions
    assert 18 <= int(features["age"]) <= 75
    assert features["account_tier"] in ACCOUNT_TIERS
    assert int(features["total_purchases"]) >= 0
    assert float(features["avg_order_value"]) > 0
    assert features["is_active"] in ("true", "false")
    assert int(features["session_count_30d"]) >= 0
    assert int(features["days_since_last_purchase"]) >= 0
    assert features["preferred_category"] in CATEGORIES
    assert features["device_type"] in DEVICE_TYPES
    assert float(features["lifetime_value"]) >= 0

    # Timestamp parse check
    dt = datetime.fromisoformat(features["last_login_timestamp"])
    assert dt is not None


def test_generate_features_determinism():
    """Verify that static feature generation for a user_id produces reproducible features."""
    user_id = "user_00001000"
    f1 = generate_features(user_id, is_update=False)
    f2 = generate_features(user_id, is_update=False)

    assert f1["age"] == f2["age"]
    assert f1["account_tier"] == f2["account_tier"]
    assert f1["preferred_category"] == f2["preferred_category"]
    assert f1["device_type"] == f2["device_type"]


def test_populate_initial_users_mock():
    """Verify pipeline ingestion populates Redis hash and global user set."""
    fake_sync_redis = fakeredis.FakeRedis(decode_responses=True)
    import scripts.ingest_features as ingest_mod

    orig_target = ingest_mod.TARGET_USERS
    orig_batch = ingest_mod.BATCH_SIZE
    try:
        ingest_mod.TARGET_USERS = 25
        ingest_mod.BATCH_SIZE = 10
        populate_initial_users(fake_sync_redis)

        assert fake_sync_redis.scard("all_users") == 25
        assert bool(fake_sync_redis.sismember("all_users", "user_00000001")) is True
        assert bool(fake_sync_redis.sismember("all_users", "user_00000025")) is True

        user_1_features = fake_sync_redis.hgetall("user:user_00000001:features")
        assert "age" in user_1_features
        assert "account_tier" in user_1_features
    finally:
        ingest_mod.TARGET_USERS = orig_target
        ingest_mod.BATCH_SIZE = orig_batch
