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
    poiesis_model_vision: str = "ollama/gemma4:12b"

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

    # Jira Cloud. Off unless all four of the first block are set; a run never waits
    # on Jira and never fails because of it (see integrations/tracker.py).
    jira_base_url: str = ""            # https://your-site.atlassian.net
    jira_email: str = ""               # the Atlassian account the API token belongs to
    jira_api_token: str = ""           # id.atlassian.com > Security > API tokens
    jira_project_key: str = ""         # every run lands in this one project
    # A run becomes one issue of this type, parent of its epics. Needs Jira Premium
    # with the hierarchy set up; without it epics are created with no parent.
    jira_initiative_type: str = "Initiative"
    jira_board_id: int = 0             # 0 = the project's first scrum board
    jira_sprint_days: int = 14

    # Local models. The native Ollama client (llm.py) uses these; the hosted
    # profiles ignore them. num_ctx is sent with every request, so the Modelfile
    # variants are no longer needed to get a usable context window.
    poiesis_local_num_ctx: int = 32768
    poiesis_local_keep_alive: str = "30m"
    poiesis_local_idle_timeout: int = 900      # seconds with no token before a call is abandoned
    poiesis_local_min_tokens: int = 8000       # floor on the reply budget for local models
    # The Developer returns whole files; a story that seeds 150 rows needs room.
    poiesis_local_coding_min_tokens: int = 16000
    # A reply that hits its budget is asked again with double the budget, up to this.
    poiesis_local_max_tokens: int = 28000
    # Roles allowed to "think" before answering (Qwen3 / gpt-oss style reasoning).
    # Thinking improves the Analyst, Architect and Reviewer; the Developer writes
    # files, where it mostly spends the budget.
    poiesis_local_think_roles: str = "reasoning"
    poiesis_local_think_budget: int = 6000     # extra reply tokens allowed when thinking is on
    # Tokens per GPU batch while reading the prompt. Windows kills a GPU kernel that
    # runs longer than its timeout (2 s by default) and takes the machine down with a
    # VIDEO_TDR_FAILURE bugcheck; a laptop GPU that throttles can push a 512-token
    # batch past it. 128 keeps each batch well inside the limit at a modest cost.
    poiesis_local_num_batch: int = 128

    # Engine. One run at a time on a single GPU; more only makes both slower.
    poiesis_max_concurrent_runs: int = 1
    poiesis_restart_deployments_on_boot: bool = True

    # Observability. Spans and model calls are always stored in Postgres; set an
    # OTLP endpoint (Jaeger in compose: http://jaeger:4318) to export them too.
    otel_exporter_otlp_endpoint: str = ""
    poiesis_log_format: str = "text"           # text | json
    poiesis_trace_prompt_chars: int = 120000   # how much of each prompt/reply the trace keeps

    # Git remote. Every run's workspace is pushed to a remote as the build goes,
    # and released on the default branch with a tag. Off unless a template is set.
    #   https://github.com/acme/poiesis-{slug}.git   (token used over HTTPS)
    #   git@github.com:acme/poiesis-{slug}.git       (needs the container's SSH key)
    git_remote_template: str = ""
    git_token: str = ""
    git_username: str = "poiesis"
    git_default_branch: str = "main"
    git_push_each_story: bool = True
    # GitHub only: create the repository under this user or organisation when the
    # remote does not exist yet, and open a pull request at release.
    github_owner: str = ""
    github_api: str = "https://api.github.com"
    github_private: bool = True
    git_open_pull_request: bool = True

    # Vector recall over the portfolio and past runs (Qdrant). Off if unreachable.
    poiesis_vectors: bool = True

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
