from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    # Which provider drives the agent LLMs. Pricing + model names branch on this.
    # Embeddings always use OpenAI regardless.
    agent_provider: Literal["anthropic", "openai"] = "anthropic"
    agent_model_default: str = "claude-sonnet-4-6"
    agent_model_architect: str = "claude-opus-4-7"
    embedding_model: str = "text-embedding-3-large"
    daily_cost_limit_usd: float = 20.0
    ingest_cost_limit_usd: float = 5.0

    @property
    def active_api_key(self) -> str:
        """Return the API key for the configured agent provider."""
        return self.openai_api_key if self.agent_provider == "openai" else self.anthropic_api_key

    @property
    def active_default_model(self) -> str:
        """Sensible default per provider — keeps Architect routing meaningful."""
        if self.agent_provider == "openai":
            return "gpt-4o-mini" if self.agent_model_default.startswith("claude-") else self.agent_model_default
        return self.agent_model_default

    @property
    def active_architect_model(self) -> str:
        if self.agent_provider == "openai":
            return "gpt-4o" if self.agent_model_architect.startswith("claude-") else self.agent_model_architect
        return self.agent_model_architect

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme-neo4j"

    # Postgres
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "architect"
    postgres_user: str = "architect"
    postgres_password: str = "changeme-postgres"

    # Langfuse
    langfuse_host: str = "http://localhost:3001"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_log_level: str = "info"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
