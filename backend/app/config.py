from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# The environment file lives at the repository root. Resolving it from this file
# instead of the current working directory means `cd backend && pytest` or
# `uvicorn app.main:app` read the same configuration as commands run from the
# root. In the container the file does not exist, so the process environment is
# the only source, which is what Compose provides.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Runtime configuration. Every secret comes from the environment."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(
        default="postgresql+asyncpg://lcsp:lcsp@localhost:5432/lcsp",
        validation_alias="DATABASE_URL",
    )
    # Dedicated database for the integration suites, which truncate the corpus
    # tables. Read through Settings so a value in the local environment file
    # counts, not only one exported in the shell.
    database_url_test: str = Field(default="", validation_alias="DATABASE_URL_TEST")
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
    # Calibrated on 2026-11-12 against 25 annotated questions with the real
    # rerank model: the best score of answerable questions never dropped below
    # 0.958, while out-of-law questions never exceeded 0.757. 0.85 sits in that
    # gap. The previous 0.35 was a guess and abstained on 5 of 20 valid
    # questions while letting 4 of 5 out-of-law ones through.
    rerank_threshold: float = Field(default=0.85, validation_alias="RERANK_THRESHOLD")
    embedding_batch_size: int = Field(default=16, validation_alias="EMBEDDING_BATCH_SIZE")


@lru_cache
def get_settings() -> Settings:
    return Settings()
