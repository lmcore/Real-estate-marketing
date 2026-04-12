"""Runtime configuration loaded from environment / .env file."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Global Shadow Tester settings.

    Values can be overridden via environment variables prefixed with ``SHADOW_``
    or via a ``.env`` file at the project root.
    """

    model_config = SettingsConfigDict(
        env_prefix="SHADOW_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    default_commune: str = Field(
        default="04112",
        description="Default INSEE commune code (Manosque = 04112).",
    )
    cache_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "cache",
        description="Where DVF CSV downloads are cached.",
    )
    db_path: Path = Field(
        default=PROJECT_ROOT / "data" / "shadow_tester.sqlite",
        description="SQLite database path.",
    )
    dvf_base_url: str = Field(
        default="https://files.data.gouv.fr/geo-dvf/latest/csv",
        description="Base URL for Etalab's geo-DVF CSV files.",
    )
    anthropic_api_key: str | None = Field(
        default=None,
        description="Anthropic API key for Claude Vision photo analysis. "
        "Set via SHADOW_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY env var.",
    )
    vision_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model to use for photo condition analysis.",
    )
    vision_max_photos: int = Field(
        default=4,
        description="Max photos to send for vision analysis (controls cost).",
    )
    log_level: str = Field(default="INFO")

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
        logging.basicConfig(
            level=_settings.log_level,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        )
        # Fallback: accept bare ANTHROPIC_API_KEY env var (standard convention).
        if _settings.anthropic_api_key is None:
            import os

            _settings.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    return _settings
