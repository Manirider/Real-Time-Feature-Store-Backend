"""Pydantic schemas for the Real-Time Feature Store API.

Provides request and response validation for single feature retrieval,
batch feature queries, and service health checks.
"""

from typing import List, Dict
from pydantic import BaseModel, Field, field_validator


class BatchFeatureRequest(BaseModel):
    """Request payload for batch feature retrieval."""

    user_ids: List[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of 1 to 100 user IDs to fetch features for.",
        examples=[["123", "456", "unknown_99"]],
    )

    @field_validator("user_ids")
    @classmethod
    def validate_user_ids(cls, v: List[str]) -> List[str]:
        cleaned = []
        for idx, item in enumerate(v):
            if not isinstance(item, str):
                raise ValueError(f"user_id at index {idx} must be a string")
            stripped = item.strip()
            if not stripped:
                raise ValueError(f"user_id at index {idx} must be non-empty and not only whitespace")
            if len(stripped) > 128:
                raise ValueError(f"user_id at index {idx} exceeds maximum allowed length of 128 characters")
            cleaned.append(stripped)
        return cleaned


class FeatureResponse(BaseModel):
    """Response payload containing a single user's features."""

    user_id: str = Field(..., description="Unique user identifier", examples=["123"])
    features: Dict[str, str] = Field(
        default_factory=dict,
        description="Key-value mapping of feature names to string feature values",
        examples=[{"age": "25", "account_tier": "premium"}],
    )


class FeatureItem(FeatureResponse):
    """Alias for FeatureResponse for ML feature contract compatibility."""
    pass


class HealthResponse(BaseModel):
    """Response payload for service health check."""

    status: str = Field(..., description="Health status indicator", examples=["ok"])
