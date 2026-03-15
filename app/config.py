from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    supervisord_port: int
    # Application
    APP_NAME: str = "Pharmaco"
    APP_COMPANY: str = "Qinora"
    APP_VERSION: str = "1.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = False

    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "pharmaco"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    SECRET_KEY: str = "change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 h

    # Scraper
    UBPHAR_URL: str = "https://www.ubphar.com/content/ubphar/liste-des-pharmacies"
    SCRAPER_INTERVAL_HOURS: int = 24

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
