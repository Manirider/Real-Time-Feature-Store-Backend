"""Redis data access and connection service for the Real-Time Feature Store.

Manages connection pooling, pipelined reads/writes, and schema isolation
between the API layer and the underlying Redis storage.
"""

import logging
from typing import Dict, List, Optional
import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Async Redis client wrapper with connection pooling and optimized pipelining."""

    def __init__(self) -> None:
        self._redis: Optional[aioredis.Redis] = None
        self._pool: Optional[aioredis.ConnectionPool] = None

    async def connect(self) -> None:
        """Initialize Redis connection pool and verify connectivity."""
        if self._redis is None:
            self._pool = aioredis.ConnectionPool(
                host=settings.redis_host,
                port=settings.redis_port,
                decode_responses=True,
                max_connections=200,
                socket_keepalive=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
            )
            self._redis = aioredis.Redis(connection_pool=self._pool)
            try:
                await self._redis.ping()
                logger.info(
                    "Successfully connected to Redis at %s:%s",
                    settings.redis_host,
                    settings.redis_port,
                )
            except Exception as exc:
                logger.warning(
                    "Initial Redis ping failed at %s:%s: %s (will retry on incoming requests)",
                    settings.redis_host,
                    settings.redis_port,
                    exc,
                )

    async def close(self) -> None:
        """Close connection pool gracefully during application shutdown."""
        if self._redis:
            await self._redis.close()
            logger.info("Closed Redis async client")
        if self._pool:
            await self._pool.disconnect()
            logger.info("Disconnected Redis connection pool")
        self._redis = None
        self._pool = None

    @property
    def redis(self) -> aioredis.Redis:
        """Return the active Redis client or raise RuntimeError if disconnected."""
        if self._redis is None:
            raise RuntimeError("Redis client is not connected")
        return self._redis

    @staticmethod
    def key_for_user(user_id: str) -> str:
        """Generate canonical Redis Hash key for user features."""
        return f"user:{user_id}:features"

    async def user_exists(self, user_id: str) -> bool:
        """Check whether a user exists in the global user index set."""
        exists = await self.redis.sismember("all_users", user_id)
        return bool(exists)

    async def get_user_features(self, user_id: str) -> Optional[Dict[str, str]]:
        """Retrieve features for a single user using a Redis pipeline.

        Returns None if user is not in the 'all_users' set (triggers 404).
        Returns a dict of feature string key-values if the user exists.
        """
        key = self.key_for_user(user_id)
        pipe = self.redis.pipeline()
        pipe.sismember("all_users", user_id)
        pipe.hgetall(key)
        exists, data = await pipe.execute()
        if not exists:
            return None
        return data or {}

    async def get_batch_features(self, user_ids: List[str]) -> Dict[str, Dict[str, str]]:
        """Retrieve features for a batch of users using a 2-stage optimized pipeline.

        Optimization:
        1. Deduplicates requested IDs while preserving lookup semantics.
        2. Stage 1: Pipelines SISMEMBER for all unique IDs in a single round-trip.
        3. Identifies users verified to exist in the global index.
        4. Stage 2: Pipelines HGETALL only for existing users, avoiding unnecessary
           hash lookups for missing records.
        5. Populates result map with empty dict {} for missing users.
        """
        if not user_ids:
            return {}

        unique_ids = list(dict.fromkeys(user_ids))

        # Stage 1: Pipeline SISMEMBER existence checks
        pipe = self.redis.pipeline()
        for uid in unique_ids:
            pipe.sismember("all_users", uid)
        existence_results = await pipe.execute()

        existing_users = [
            uid for uid, exists in zip(unique_ids, existence_results) if exists
        ]
        result_map: Dict[str, Dict[str, str]] = {uid: {} for uid in unique_ids}

        # Stage 2: Pipeline HGETALL only for confirmed existing users
        if existing_users:
            pipe = self.redis.pipeline()
            for uid in existing_users:
                pipe.hgetall(self.key_for_user(uid))
            hash_results = await pipe.execute()
            for uid, features in zip(existing_users, hash_results):
                result_map[uid] = features or {}

        return result_map

    async def set_user_features(self, user_id: str, features: Dict[str, str]) -> None:
        """Write user features and update the global user index atomically via pipeline."""
        key = self.key_for_user(user_id)
        pipe = self.redis.pipeline()
        pipe.hset(key, mapping=features)
        pipe.sadd("all_users", user_id)
        await pipe.execute()


redis_client = RedisClient()
