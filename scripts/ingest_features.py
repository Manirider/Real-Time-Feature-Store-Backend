"""Synthetic feature ingestion pipeline for the Real-Time Feature Store.

Populates Redis with 100,000+ deterministic user feature vectors and
runs a continuous update loop simulating production feature stream ingestion.
"""

import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import redis
from redis.exceptions import ConnectionError as RedisConnectionError, RedisError, TimeoutError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [ingestion_worker] %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
BATCH_SIZE = int(os.getenv("INGESTION_BATCH_SIZE", "500"))
INTERVAL_SEC = float(os.getenv("INGESTION_INTERVAL_SEC", "0.5"))
TARGET_USERS = int(os.getenv("INGESTION_TARGET_USERS", "100000"))

ACCOUNT_TIERS = ["free", "basic", "premium", "enterprise"]
CATEGORIES = ["electronics", "clothing", "home", "sports", "books"]
DEVICE_TYPES = ["mobile", "desktop", "tablet"]

# Graceful termination flag
_running = True


def handle_shutdown(signum, frame):
    """Handle termination signals gracefully."""
    global _running
    logger.info("Received termination signal (%s). Initiating graceful shutdown...", signum)
    _running = False


def generate_features(user_id: str, is_update: bool = False) -> Dict[str, str]:
    """Generate realistic ML features for a given user.

    Uses a deterministic seed based on user_id for base features, while allowing
    timestamps and dynamic usage counts to update cleanly during periodic refresh.
    """
    seed = abs(hash(user_id)) % (2**32)
    rng = random.Random(seed)

    age = rng.randint(18, 75)
    account_tier = rng.choice(ACCOUNT_TIERS)
    total_purchases = rng.randint(0, 250)
    avg_order_value = round(rng.uniform(10.0, 500.0), 2)
    is_active = rng.random() > 0.15
    preferred_category = rng.choice(CATEGORIES)
    device_type = rng.choice(DEVICE_TYPES)
    lifetime_value = round(total_purchases * avg_order_value * rng.uniform(0.85, 1.15), 2)

    # Dynamic features for updates
    if is_update:
        # Use current time for active refresh
        now = datetime.now(timezone.utc)
        days_ago = random.randint(0, 15)
        last_login = now - timedelta(days=days_ago, minutes=random.randint(0, 1440))
        session_count_30d = random.randint(1, 120)
        days_since_last_purchase = random.randint(0, 180)
    else:
        now = datetime.now(timezone.utc)
        days_ago = rng.randint(0, 30)
        last_login = now - timedelta(days=days_ago, hours=rng.randint(0, 23))
        session_count_30d = rng.randint(0, 100)
        days_since_last_purchase = rng.randint(0, 365)

    return {
        "age": str(age),
        "account_tier": account_tier,
        "total_purchases": str(total_purchases),
        "avg_order_value": f"{avg_order_value:.2f}",
        "is_active": str(is_active).lower(),
        "session_count_30d": str(session_count_30d),
        "days_since_last_purchase": str(days_since_last_purchase),
        "preferred_category": preferred_category,
        "device_type": device_type,
        "lifetime_value": f"{lifetime_value:.2f}",
        "last_login_timestamp": last_login.isoformat(),
    }


def connect_redis(max_retries: int = 15, base_backoff: float = 1.0) -> redis.Redis:
    """Connect to Redis with bounded exponential backoff retries."""
    for attempt in range(1, max_retries + 1):
        if not _running:
            sys.exit(0)
        try:
            logger.info("Attempting to connect to Redis at %s:%s (attempt %d/%d)...", REDIS_HOST, REDIS_PORT, attempt, max_retries)
            client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
            )
            client.ping()
            logger.info("Connected to Redis successfully.")
            return client
        except (RedisConnectionError, TimeoutError, RedisError) as exc:
            backoff = min(base_backoff * (1.5 ** (attempt - 1)), 15.0)
            logger.warning("Redis connection attempt %d failed: %s. Retrying in %.2fs...", attempt, exc, backoff)
            time.sleep(backoff)

    raise RuntimeError(f"Failed to connect to Redis at {REDIS_HOST}:{REDIS_PORT} after {max_retries} attempts.")


def populate_initial_users(redis_client: redis.Redis) -> None:
    """Populate Redis up to TARGET_USERS using pipelined writes."""
    try:
        existing_count = redis_client.scard("all_users")
    except RedisError as exc:
        logger.error("Failed to check existing user count: %s", exc)
        existing_count = 0

    logger.info("Current user count in 'all_users': %d (target: %d)", existing_count, TARGET_USERS)

    if existing_count >= TARGET_USERS:
        logger.info("Target user volume already satisfied (%d users).", existing_count)
        return

    logger.info("Starting initial population of %d users with batch size %d...", TARGET_USERS - existing_count, BATCH_SIZE)
    start_time = time.perf_counter()

    current_id = existing_count + 1
    total_written = existing_count

    while current_id <= TARGET_USERS and _running:
        batch_end = min(current_id + BATCH_SIZE - 1, TARGET_USERS)
        batch_ids = [f"user_{i:08d}" for i in range(current_id, batch_end + 1)]

        pipeline = redis_client.pipeline(transaction=False)
        for uid in batch_ids:
            features = generate_features(uid, is_update=False)
            pipeline.hset(f"user:{uid}:features", mapping=features)
        pipeline.sadd("all_users", *batch_ids)

        try:
            pipeline.execute()
        except RedisError as exc:
            logger.error("Redis error executing initial population batch for %s-%s: %s", batch_ids[0], batch_ids[-1], exc)
            time.sleep(1.0)
            continue

        total_written += len(batch_ids)
        current_id = batch_end + 1

        if total_written % 10000 == 0 or current_id > TARGET_USERS:
            elapsed = time.perf_counter() - start_time
            rate = total_written / elapsed if elapsed > 0 else 0
            pct = (total_written / TARGET_USERS) * 100.0
            logger.info(
                "Progress: %d / %d users populated (%.1f%%) - Rate: %.0f users/sec",
                total_written,
                TARGET_USERS,
                pct,
                rate,
            )

    elapsed = time.perf_counter() - start_time
    final_count = redis_client.scard("all_users")
    logger.info("Initial population completed in %.2fs. Total users indexed: %d", elapsed, final_count)


def run_continuous_updates(redis_client: redis.Redis) -> None:
    """Continuously update random batches of users to simulate real-time feature streaming."""
    logger.info("Starting continuous feature update loop (interval: %.2fs, batch size: %d)...", INTERVAL_SEC, BATCH_SIZE)
    update_batch_count = 0

    while _running:
        try:
            # Sample random user IDs from the populated range
            sample_indices = [random.randint(1, TARGET_USERS) for _ in range(BATCH_SIZE)]
            batch_ids = [f"user_{idx:08d}" for idx in sample_indices]

            pipeline = redis_client.pipeline(transaction=False)
            for uid in batch_ids:
                features = generate_features(uid, is_update=True)
                pipeline.hset(f"user:{uid}:features", mapping=features)
            pipeline.sadd("all_users", *batch_ids)

            pipeline.execute()
            update_batch_count += 1

            if update_batch_count % 20 == 0:
                logger.info("Continuous updates: %d batches (%d feature updates) completed.", update_batch_count, update_batch_count * BATCH_SIZE)

            time.sleep(INTERVAL_SEC)
        except (RedisConnectionError, TimeoutError) as exc:
            logger.warning("Redis connection lost during continuous update: %s. Attempting to reconnect...", exc)
            time.sleep(2.0)
            try:
                redis_client = connect_redis(max_retries=5)
            except Exception as reconnect_exc:
                logger.error("Reconnection failed: %s", reconnect_exc)
        except RedisError as exc:
            logger.error("Redis error during feature update cycle: %s", exc)
            time.sleep(1.0)
        except Exception as exc:
            logger.exception("Unexpected error in update loop: %s", exc)
            time.sleep(1.0)


def main() -> None:
    """Main execution orchestrator for feature ingestion."""
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    logger.info("Starting Real-Time Feature Store Ingestion Worker")
    logger.info("Target: %d users, Batch Size: %d, Redis: %s:%d", TARGET_USERS, BATCH_SIZE, REDIS_HOST, REDIS_PORT)

    redis_client = connect_redis()
    populate_initial_users(redis_client)

    if _running:
        run_continuous_updates(redis_client)

    logger.info("Ingestion worker shut down gracefully.")


if __name__ == "__main__":
    main()
