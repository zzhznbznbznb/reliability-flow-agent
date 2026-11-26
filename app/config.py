"""Application settings.

Secrets are never embedded here. LLM credentials are resolved at runtime by the
LLM provider module (Phase 5), either from the user's OpenCode auth store or
from an explicitly configured environment variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str
    version: str
    phase: str
    project_root: Path
    data_dir: Path
    web_dir: Path
    experiments_dir: Path
    agent_session_dir: Path
    api_base_url: str
    llm_enabled: bool
    llm_provider: str
    llm_model: str
    llm_base_url: str
    llm_auth_mode: str
    opencode_auth_file: Path
    pi_cli_path: str | None
    pi_node_path: str | None
    pi_api_key: str | None
    agent_timeout_seconds: float
    agent_idle_timeout_seconds: float
    agent_max_sessions: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = PROJECT_ROOT / "data"
    return Settings(
        app_name="reliability-flow-agent",
        version="0.3.0",
        phase="4B",
        project_root=PROJECT_ROOT,
        data_dir=data_dir,
        web_dir=PROJECT_ROOT / "web",
        experiments_dir=Path(
            os.getenv("RFA_EXPERIMENTS_DIR", str(data_dir / "experiments"))
        ),
        agent_session_dir=Path(
            os.getenv("RFA_AGENT_SESSION_DIR", str(data_dir / "agent_sessions"))
        ),
        api_base_url=os.getenv("RFA_API_BASE_URL", "http://127.0.0.1:8000"),
        llm_enabled=_env_bool("RFA_LLM_ENABLED", False),
        llm_provider=os.getenv("RFA_LLM_PROVIDER", "opencode-go"),
        llm_model=os.getenv("RFA_LLM_MODEL", "deepseek-v4.1-flash"),
        llm_base_url=os.getenv(
            "RFA_LLM_BASE_URL",
            "https://opencode.ai/inference/go/openai/v1",
        ),
        llm_auth_mode=os.getenv("RFA_LLM_AUTH_MODE", "opencode-auth"),
        opencode_auth_file=Path(
            os.getenv(
                "RFA_OPENCODE_AUTH_FILE",
                str(Path.home() / ".local" / "share" / "opencode" / "auth.json"),
            )
        ),
        pi_cli_path=os.getenv("RFA_PI_CLI_PATH") or None,
        pi_node_path=os.getenv("RFA_PI_NODE_PATH") or None,
        pi_api_key=os.getenv("RFA_PI_API_KEY") or None,
        agent_timeout_seconds=_env_float("RFA_AGENT_TIMEOUT_SECONDS", 600.0),
        agent_idle_timeout_seconds=_env_float(
            "RFA_AGENT_IDLE_TIMEOUT_SECONDS", 1800.0
        ),
        agent_max_sessions=_env_int("RFA_AGENT_MAX_SESSIONS", 8),
    )
