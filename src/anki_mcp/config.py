import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8765"


@dataclass(frozen=True)
class Config:
    anki_url: str
    auto_launch: bool
    data_dir: Path
    project_dir: Path | None


def _env_str(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def _env_bool(name: str, default: bool) -> bool:
    value = _env_str(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_path(name: str) -> Path | None:
    value = _env_str(name)
    return Path(value).expanduser() if value else None


def load_config() -> Config:
    data_dir = _env_path("CLAUDE_PLUGIN_DATA") or Path.home() / ".anki-mcp"
    data_dir.mkdir(parents=True, exist_ok=True)
    return Config(
        anki_url=(_env_str("ANKI_CONNECT_URL") or DEFAULT_URL).rstrip("/"),
        auto_launch=_env_bool("ANKI_AUTO_LAUNCH", default=True),
        data_dir=data_dir,
        project_dir=_env_path("CLAUDE_PROJECT_DIR"),
    )
