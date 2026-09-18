from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    poiesis_llm_profile: Literal["local", "groq", "cloud"] = "local"

    ollama_base_url: str = "http://ollama:11434"
    poiesis_model_reasoning: str = "ollama/qwen2.5:14b-instruct"
    poiesis_model_coding: str = "ollama/qwen2.5-coder:14b"
    poiesis_model_fast: str = "ollama/qwen2.5:7b-instruct"
    poiesis_model_embed: str = "ollama/nomic-embed-text"

    groq_api_key: str = ""
    anthropic_api_key: str = ""

    database_url: str = "postgresql+psycopg://poiesis:poiesis@postgres:5432/poiesis"
    redis_url: str = "redis://redis:6379/0"
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "poiesisdev"
    qdrant_url: str = "http://qdrant:6333"
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "poiesis"
    minio_secret_key: str = "poiesisdev"

    poiesis_pack: str = "packs/default.yaml"
    poiesis_workspace_root: str = "/workspaces"
    # Where the same directory lives as far as the *host* Docker daemon is concerned.
    # Sandbox containers are launched as siblings through the mounted socket, so the
    # daemon resolves bind-mount sources on the host, not inside the orchestrator.
    # Leave blank only when the orchestrator runs on the host itself.
    poiesis_workspace_host_root: str = ""
    poiesis_max_sprint_stories: int = 6

    # Generated applications. Each gets a port from this range on the Docker host.
    poiesis_deploy_port_start: int = 8100
    poiesis_deploy_port_end: int = 8199
    # The address people type to open an app. Apps publish on the Docker host,
    # which from the Windows desktop is localhost.
    poiesis_deploy_public_host: str = "localhost"
    # The host interface apps bind to. 127.0.0.1 keeps unauthenticated, model-written
    # code off the network until access control exists.
    poiesis_deploy_bind: str = "127.0.0.1"
    # Seconds to wait for every service to report healthy on a first build.
    poiesis_deploy_timeout: int = 600

    @property
    def checkpoint_dsn(self) -> str:
        """LangGraph's Postgres saver wants a raw libpq DSN, not a SQLAlchemy URL."""
        return self.database_url.replace("+psycopg", "")


@lru_cache
def settings() -> Settings:
    return Settings()


@lru_cache
def pack() -> dict:
    """Domain pack: gate policy, definition of done, agent tone. Swappable per org."""
    path = Path(settings().poiesis_pack)
    if not path.exists():
        path = Path(__file__).parent.parent / settings().poiesis_pack
    return yaml.safe_load(path.read_text(encoding="utf-8"))


_ARCHETYPE_META = {"default"}


def archetype_names() -> list[str]:
    return [k for k in (pack().get("archetypes") or {}) if k not in _ARCHETYPE_META]


def archetype(name: str | None = None) -> dict:
    """The runtime contract for a run: services, ports, healthchecks, scaffold.

    Falls back to the pack's default rather than raising, because an agent that
    invents an archetype name should degrade to a working application, not stop
    the run.
    """
    block = pack().get("archetypes") or {}
    fallback = block.get("default") or "web-app"
    chosen = block.get(name) if name else None
    if not isinstance(chosen, dict):
        name = fallback
        chosen = block.get(fallback) or {}
    return {"name": name, **chosen}


def scaffold_root() -> Path:
    """Where the scaffold templates live, mirroring how packs are resolved."""
    local = Path("scaffolds")
    if local.is_dir():
        return local
    return Path(__file__).parent.parent / "scaffolds"
