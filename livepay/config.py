"""Application settings, loaded from the environment (12-factor style).

Values default to the docker-compose services for local dev. Override via a
`.env` file or real environment variables in other environments.
"""

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://livepay:livepay@localhost:5433/livepay"
    redis_url: str = "redis://localhost:6379/0"

    # Wallet: fraction of earned net pay held back as a safety buffer.
    # This is a PRODUCT policy choice (not a CRA/tax rule): withholding a
    # margin protects against later recalculation (e.g. a late clock-out
    # correction) reducing pay below what was already withdrawn.
    wallet_safety_buffer: Decimal = Decimal("0.25")


settings = Settings()
