from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "alleen-voor-ontwikkeling"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOYMEM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://loymem_app:loymem_app@localhost:5433/loymem"
    secret_key: str = DEV_SECRET
    environment: str = "development"
    public_base_url: str = "http://localhost:3000"
    session_hours: int = 12
    reward_code_seconds: int = 90
    reissue_link_minutes: int = 30
    unusual_stamps_per_hour: int = 20
    email_delivery: str = "log_only"

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.environment == "production" and (s.secret_key == DEV_SECRET or len(s.secret_key) < 32):
        raise RuntimeError("LOYMEM_SECRET_KEY ontbreekt of is te kort")
    return s
