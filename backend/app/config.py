from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every secret comes from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(
        default="postgresql+asyncpg://lcsp:lcsp@localhost:5432/lcsp",
        validation_alias="DATABASE_URL",
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:8080"],
        validation_alias="CORS_ORIGINS",
    )

    nan_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="NAN_API_KEY")
    nan_base_url: str = Field(
        default="https://api.nan.builders/v1", validation_alias="NAN_BASE_URL"
    )
    chat_model: str = Field(default="deepseek-v4-flash", validation_alias="NAN_CHAT_MODEL")
    embedding_model: str = Field(default="qwen3-embedding", validation_alias="NAN_EMBEDDING_MODEL")
    rerank_model: str = Field(default="rerank", validation_alias="NAN_RERANK_MODEL")

    embedding_dimensions: int = Field(default=4096, validation_alias="EMBEDDING_DIMENSIONS")
    retrieval_top_k: int = Field(default=6, validation_alias="RETRIEVAL_TOP_K")
    rerank_threshold: float = Field(default=0.35, validation_alias="RERANK_THRESHOLD")
    embedding_batch_size: int = Field(default=16, validation_alias="EMBEDDING_BATCH_SIZE")


@lru_cache
def get_settings() -> Settings:
    return Settings()
