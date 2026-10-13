"""Application settings loaded from environment variables / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Infrastructure
    POSTGRES_URL: str = "postgresql+asyncpg://webhookforge:webhookforge@localhost:5432/webhookforge"
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""

    # Auth
    API_KEY: str = "dev-api-key"

    # Delivery settings
    # Four retries plus the initial delivery gives the documented five total attempts.
    MAX_DELIVERY_RETRIES: int = 4
    DELIVERY_TIMEOUT_SECONDS: float = 5.0
    MAX_PAYLOAD_SIZE_BYTES: int = 65536

    # Rate limiting
    RATE_LIMIT_EVENTS_PER_MINUTE: int = 100

    # Observability
    PROMETHEUS_MULTIPROC_DIR: str | None = None

    @property
    def broker_url(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @property
    def result_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

    @property
    def postgres_url_sync(self) -> str:
        """Sync SQLAlchemy URL derived from the async one (used by Celery worker)."""
        return self.POSTGRES_URL.replace("+asyncpg", "+psycopg2")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
