"""FastAPI route definitions for the Real-Time Feature Store API.

Exposes endpoints for single feature retrieval, batch feature retrieval,
and system health monitoring.
"""

import logging
from typing import List
from fastapi import APIRouter, HTTPException, Path
from redis.exceptions import RedisError
from app.models.schemas import BatchFeatureRequest, FeatureResponse, HealthResponse
from app.services.redis_client import redis_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service Health Check",
    description="Checks API readiness and verifies active connectivity to Redis.",
    responses={
        200: {"description": "Service is healthy and Redis is responsive"},
        503: {"description": "Redis service is unavailable"},
    },
)
async def health() -> HealthResponse:
    """Perform health check by pinging Redis."""
    try:
        await redis_client.redis.ping()
        return HealthResponse(status="ok")
    except Exception as exc:
        logger.error("Health check failed - Redis ping error: %s", exc)
        raise HTTPException(status_code=503, detail="Redis unavailable") from None


@router.get(
    "/features/{user_id}",
    response_model=FeatureResponse,
    summary="Retrieve Features for a Single User",
    description="Retrieves online feature vector stored in Redis Hash for the specified user.",
    responses={
        200: {"description": "User features retrieved successfully", "model": FeatureResponse},
        400: {"description": "Invalid user_id parameter"},
        404: {"description": "User not found in feature store"},
        503: {"description": "Redis backend is unavailable"},
    },
)
async def get_features(
    user_id: str = Path(..., description="Unique user identifier (1 to 128 characters)"),
) -> FeatureResponse:
    """Retrieve features for a single user by ID."""
    if not user_id or not user_id.strip() or len(user_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    user_id = user_id.strip()
    try:
        features = await redis_client.get_user_features(user_id)
    except (RedisError, ConnectionError, RuntimeError) as exc:
        logger.error("Redis error fetching features for user '%s': %s", user_id, exc)
        raise HTTPException(status_code=503, detail="Redis unavailable") from None

    if features is None:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")

    return FeatureResponse(user_id=user_id, features=features)


@router.post(
    "/features/batch",
    response_model=List[FeatureResponse],
    summary="Retrieve Features for Multiple Users",
    description="Batch fetches feature vectors for 1 to 100 users using pipelined Redis lookups.",
    responses={
        200: {"description": "Batch retrieval completed successfully", "model": List[FeatureResponse]},
        422: {"description": "Validation error in request payload"},
        503: {"description": "Redis backend is unavailable"},
    },
)
async def get_batch_features(request: BatchFeatureRequest) -> List[FeatureResponse]:
    """Retrieve features for a batch of users, returning empty feature dicts for missing users."""
    user_ids = request.user_ids
    try:
        results_map = await redis_client.get_batch_features(user_ids)
    except (RedisError, ConnectionError, RuntimeError) as exc:
        logger.error("Redis error in batch feature lookup: %s", exc)
        raise HTTPException(status_code=503, detail="Redis unavailable") from None

    response: List[FeatureResponse] = []
    for uid in user_ids:
        features = results_map.get(uid, {})
        response.append(FeatureResponse(user_id=uid, features=features))

    return response
