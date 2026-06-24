from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Foresight API"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/foresight"

    SECRET_KEY: str = "change-me-in-production"
    ENCRYPTION_KEY: str = ""  # Generate with: Fernet.generate_key().decode()

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Marketplaces with real, trusted data today. Everything else is shown but
    # gated as "not connected" in the UI (no real scrapers yet). Stopgap until
    # connectivity is derived from successful scrape_jobs per platform.
    CONNECTED_MARKETPLACES: list[str] = ["blinkit"]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
