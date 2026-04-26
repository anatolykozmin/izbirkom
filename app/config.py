from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    secret_key: str = Field(
        default="change-me-in-production-use-openssl-rand-hex-32",
        description="Signing key for JWT and OTP pepper",
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120

    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@localhost"
    smtp_use_tls: bool = True

    # When True, emails are printed to stdout instead of SMTP (good for local dev)
    email_debug: bool = True

    database_url: str = "sqlite+aiosqlite:///./data/votes.db"

    # Включите на продакшене за HTTPS
    cookie_secure: bool = False

    otp_expire_minutes: int = 15
    otp_length: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()
