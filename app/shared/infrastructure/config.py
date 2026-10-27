from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Menu SaaS API"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://menu:menu@localhost:5440/menu"
    redis_url: str = "redis://localhost:6380/0"

    # Signing key for access tokens (HS256). Required: there is no default on purpose.
    jwt_secret: SecretStr = Field(min_length=32)
    # The access and refresh cookies are always httpOnly + SameSite=Strict; Secure can only be
    # disabled for plain-HTTP setups other than localhost (browsers accept Secure cookies on localhost).
    auth_cookie_secure: bool = True

    # Login attempts allowed per account (user) inside the window before a temporary block.
    login_failure_window_seconds: int = Field(default=900, gt=0)
    login_max_failures_per_account: int = Field(default=5, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required values come from the environment
