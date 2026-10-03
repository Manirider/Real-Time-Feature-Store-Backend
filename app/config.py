"""Configuration settings for the Real-Time Feature Store Backend.

Uses Pydantic Settings to load and validate environment variables.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable overrides and validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    redis_host: str = Field(default="redis", description="Redis server hostname or IP")
    redis_port: int = Field(default=6379, gt=0, le=65535, description="Redis server port")
    api_host: str = Field(default="0.0.0.0", description="FastAPI host binding")
    api_port: int = Field(default=8000, gt=0, le=65535, description="FastAPI port binding")
    ingestion_batch_size: int = Field(default=500, gt=0, description="Number of users per ingestion batch")
    ingestion_interval_sec: float = Field(default=0.5, ge=0.0, description="Sleep interval between ingestion batches in seconds")
    ingestion_target_users: int = Field(default=100000, gt=0, description="Total unique users target for ingestion")


settings = Settings()
