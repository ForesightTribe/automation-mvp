from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Foresight API"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/foresight"

    SECRET_KEY: str = "change-me-in-production"
    ENCRYPTION_KEY: str = ""  # Generate with: Fernet.generate_key().decode()

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
