from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    # App
    app_name: str = "Pathfinder API"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "development"


    # Database — ssl=disable required for local Docker postgres (no SSL configured)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pathfinder?ssl=disable"
    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # AI providers
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    google_project_id: str = ""
    google_location: str = "us-central1"


    # Object storage
    s3_bucket: str = "pathfinder-documents"
    s3_region: str = "us-east-1"

    # Rate limits (requests per minute)
    rate_limit_default: int = 60
    rate_limit_generation: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
