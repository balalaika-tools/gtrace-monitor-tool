from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        populate_by_name=True,
        extra="ignore",
    )

    # ── General ──────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ── AWS ──────────────────────────────────────────────────────────────
    aws_access_key_id: str | None = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str | None = Field(
        default=None, alias="AWS_SECRET_ACCESS_KEY"
    )
    aws_session_token: str | None = Field(default=None, alias="AWS_SESSION_TOKEN")
    aws_default_region: str = Field(default="us-east-1", alias="AWS_DEFAULT_REGION")

    # ── CloudWatch ──────────────────────────────────────────────────────
    log_group_name: str | None = Field(
        default=None,
        alias="LOG_GROUP_NAME",
    )
    log_filter_pattern: str = Field(
        default='{ $.level = "TRACE" }',
        alias="LOG_FILTER_PATTERN",
    )
    max_log_events: int = Field(
        default=50_000,
        alias="MAX_LOG_EVENTS",
    )
    span_content_max_chars: int = Field(
        default=900,
        alias="SPAN_CONTENT_MAX_CHARS",
    )

    # ── LLM Pricing (USD per million tokens) ────────────────────────────
    price_input: float = Field(default=1.00, alias="PRICE_INPUT")
    price_output: float = Field(default=5.00, alias="PRICE_OUTPUT")
    price_cache_creation: float = Field(default=1.25, alias="PRICE_CACHE_CREATION")
    price_cache_read: float = Field(default=0.10, alias="PRICE_CACHE_READ")

    # ── S3 (single bucket, different prefixes) ───────────────────────────
    s3_bucket: str = Field(default="ai-exception-poc-data", alias="S3_BUCKET")
    s3_config_prefix: str = Field(default="config", alias="S3_CONFIG_PREFIX")
    s3_reports_prefix: str = Field(default="reports", alias="S3_REPORTS_PREFIX")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        return Settings()
    except Exception:
        raise
