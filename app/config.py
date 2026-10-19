"""Settings read from environment variables or the .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str
    groq_api_key: str
    agent_model: str
    guardian_model: str
    jwt_secret: str
    jwt_expire_minutes: int = 60
    timezone: str = "America/Montevideo"


settings = Settings()
