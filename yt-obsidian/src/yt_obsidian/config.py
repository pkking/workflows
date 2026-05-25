"""Configuration management for yt-obsidian pipeline."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class Config:
    youtube_api_key: str
    openai_api_key: str | None
    vault_path: Path
    output_dir: Path
    max_videos: int
    whisper_mode: Literal["auto", "local", "api"]
    dry_run: bool


def load_config(
    vault_path: str | Path = "./obsidian-vault",
    output_dir: str | Path = "./yt-obsidian-output",
    max_videos: int = 5,
    whisper_mode: Literal["auto", "local", "api"] = "auto",
    dry_run: bool = False,
) -> Config:
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY")
    if not youtube_api_key:
        raise ValueError("YOUTUBE_API_KEY environment variable is required")

    openai_api_key = os.environ.get("OPENAI_API_KEY")

    valid_modes = ("auto", "local", "api")
    if whisper_mode not in valid_modes:
        raise ValueError(f"whisper_mode must be one of {valid_modes}, got '{whisper_mode}'")

    if not (1 <= max_videos <= 20):
        raise ValueError(f"max_videos must be between 1 and 20, got {max_videos}")

    vault = Path(vault_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    return Config(
        youtube_api_key=youtube_api_key,
        openai_api_key=openai_api_key,
        vault_path=vault,
        output_dir=out,
        max_videos=max_videos,
        whisper_mode=whisper_mode,
        dry_run=dry_run,
    )


def detect_whisper_available() -> bool:
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        return False
