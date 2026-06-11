"""Runtime configuration helpers for the Search Agent project."""

from __future__ import annotations

import logging
import os
import sys
from functools import lru_cache
from pathlib import Path

import anthropic
from baseten_performance_client import PerformanceClient
try:
    import pysqlite3  # type: ignore
    sys.modules["sqlite3"] = pysqlite3
except Exception:
    pass
import chromadb
import structlog
import tinker
from openai import OpenAI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_FILES = (
    str(REPO_ROOT / ".env.local"),
    str(REPO_ROOT / ".env"),
)


def init_logging(
    app_level: int = logging.INFO,
    *,
    lib_level: int = logging.WARNING,
    colors: bool = True,
    pad_event: bool = True,
    pad_level: bool = False,
) -> None:
    """Configure structured logging without lowering library log thresholds."""

    logging.basicConfig(level=lib_level, format="%(message)s")
    structlog.configure_once(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(
                colors=colors, pad_event=pad_event, pad_level=pad_level
            ),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(app_level),
        cache_logger_on_first_use=True,
    )


class Config(BaseSettings):
    """Runtime configuration loaded from environment variables or .env files."""

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: SecretStr
    anthropic_api_key: SecretStr
    chroma_api_key: SecretStr
    chroma_database: str
    huggingface_token: SecretStr
    tinker_api_key: SecretStr
    browsecompplus_qrels_gold_path: str
    browsecompplus_qrels_evidence_path: str
    browsecompplus_queries_path: str
    browsecompplus_answers_path: str
    moonshot_api_key: SecretStr
    baseten_api_key: SecretStr
    baseten_model_url: str
    jina_api_key: SecretStr
    contextual_api_key: SecretStr

    def get_chroma_client(self) -> chromadb.ClientAPI:
        return chromadb.CloudClient(
            api_key=self.chroma_api_key.get_secret_value(),
            database=self.chroma_database,
        )

    def get_openai_client(self) -> OpenAI:
        return OpenAI(api_key=self.openai_api_key.get_secret_value())

    def get_anthropic_client(self) -> anthropic.Anthropic:
        return anthropic.Anthropic(api_key=self.anthropic_api_key.get_secret_value())

    def get_moonshot_client(self) -> OpenAI:
        return OpenAI(
            api_key=self.moonshot_api_key.get_secret_value(),
            base_url="https://api.moonshot.ai/v1",
        )

    def get_tinker_service_client(self) -> tinker.ServiceClient:
        return tinker.ServiceClient(api_key=self.tinker_api_key.get_secret_value())

    def get_baseten_client(self) -> PerformanceClient:
        return PerformanceClient(
            base_url=self.baseten_model_url,
            api_key=self.baseten_api_key.get_secret_value(),
        )


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return a cached settings instance."""

    config = Config()  # type: ignore[call-arg]
    init_logging()
    if config.huggingface_token:
        # Populate this here since HF libraries are cumbersome to configure otherwise
        os.environ["HF_TOKEN"] = config.huggingface_token.get_secret_value()
    if config.tinker_api_key:
        os.environ["TINKER_API_KEY"] = config.tinker_api_key.get_secret_value()
    if config.jina_api_key:
        os.environ["CHROMA_JINA_API_KEY"] = config.jina_api_key.get_secret_value()
    return config
