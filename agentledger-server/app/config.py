"""Server configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./agentledger.db"
    redis_url: str = "redis://localhost:6379/0"
    api_key: str | None = None  # if set, all requests must include this key
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    batch_max_size: int = 1000
    log_level: str = "INFO"

    model_config = {"env_prefix": "AGENTLEDGER_"}


settings = Settings()
