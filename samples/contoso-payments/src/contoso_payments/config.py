"""Settings: CONTOSO_* env vars."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONTOSO_", env_file=".env")

    database_url: str = "postgresql+asyncpg://postgres:localdev@localhost:5432/payments"
    bank_base_url: str = "http://localhost:8200"
    bank_api_key: str = "local-dev-key"
    webhook_secret: str = "dev-secret"
    # Bumping this sentinel is what forces App Service to reload config after
    # a slot swap - see docs/deploy.md.
    app_config_sentinel: str = "0"


settings = Settings()
