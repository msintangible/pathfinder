from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    # App
    app_name: str = "Pathfinder API"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "development"


    # Database — ssl=disable required for local Docker postgres (no SSL configured)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pathfinder?ssl=disable"
    # Unused by the app itself — docker-compose reads these from the same
    # .env to configure the Postgres container. Declared here only so
    # Settings (extra="forbid" by default) doesn't reject them.
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "pathfinder"
    postgres_port: int = 5432
    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30
    # Anonymous identity tokens (no login flow exists yet, so no session to
    # refresh) get their own, much longer expiry than a future login session.
    jwt_anonymous_token_expire_days: int = 365

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

    # Local resume PDF storage — placeholder until S3 upload is wired up
    resume_storage_path: str = "./storage/resumes"

    # Rate limits (requests per minute)
    rate_limit_default: int = 60
    rate_limit_generation: int = 10

    # In-app backstop against unexpected Gemini API bills — the Google Cloud
    # Console quota/budget cap is the other, external half of this safety net.
    gemini_daily_call_limit: int = 500

    @model_validator(mode="after")
    def _require_real_jwt_secret_in_production(self) -> "Settings":
        if self.environment == "production" and self.jwt_secret_key == _DEFAULT_JWT_SECRET:
            raise ValueError(
                "JWT_SECRET_KEY is still the default value. Set a real random secret "
                "before running with ENVIRONMENT=production."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
