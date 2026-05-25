"""YouTube video audio and subtitle downloader using yt-dlp."""

import logging
from pathlib import Path

import yt_dlp

from yt_obsidian.models import VideoAsset

logger = logging.getLogger(__name__)

# Preferred subtitle languages (checked in order)
_SUBTITLE_LANGS = ["en", "en-US", "en-GB"]


def download_video(video_id: str, output_dir: Path) -> VideoAsset:
    """Download audio and subtitles for a YouTube video.

    Tries to extract subtitles first, then downloads audio.
    Returns a VideoAsset with paths to downloaded files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    subtitle_path, subtitle_lang = _try_extract_subtitles(video_id, output_dir)
    audio_path = _download_audio(video_id, output_dir)

    return VideoAsset(
        video_id=video_id,
        audio_path=audio_path,
        subtitle_path=subtitle_path,
        subtitle_language=subtitle_lang,
    )


def _try_extract_subtitles(
    video_id: str, output_dir: Path
) -> tuple[Path | None, str | None]:
    """Attempt to download subtitles for a video.

    Checks both manual subtitles and automatic captions.
    Returns (subtitle_path, language) or (None, None) if unavailable.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": _SUBTITLE_LANGS,
        "subtitlesformat": "srt",
        "outtmpl": str(output_dir / "%(id)s"),
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            logger.warning("Could not extract info for video %s", video_id)
            return None, None

        # Check manual subtitles first, then automatic captions
        subtitles = info.get("subtitles") or {}
        automatic = info.get("automatic_captions") or {}

        lang = _find_available_lang(subtitles, automatic)
        if lang is None:
            logger.info("No subtitles found for video %s", video_id)
            return None, None

        # Download the subtitles
        logger.info("Downloading subtitles for video %s (lang=%s)", video_id, lang)
        ydl.download([url])

        # Determine the subtitle file path
        subtitle_path = output_dir / f"{video_id}.{lang}.srt"
        if subtitle_path.exists():
            return subtitle_path, lang

        # Fallback: search for any .srt file with the video_id prefix
        for f in output_dir.glob(f"{video_id}*.srt"):
            return f, lang

        logger.warning("Subtitle file not found after download for %s", video_id)
        return None, None


def _find_available_lang(
    subtitles: dict, automatic: dict
) -> str | None:
    """Find the first available subtitle language from preferred list."""
    for lang in _SUBTITLE_LANGS:
        if lang in subtitles:
            return lang
    for lang in _SUBTITLE_LANGS:
        if lang in automatic:
            return lang
    return None


def _download_audio(video_id: str, output_dir: Path) -> Path:
    """Download audio from a YouTube video as WAV.

    Returns the path to the downloaded audio file.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    expected_path = output_dir / f"{video_id}.wav"

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "0",
            }
        ],
        "outtmpl": str(output_dir / f"{video_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    if expected_path.exists():
        return expected_path

    # Fallback: find the actual file (extension may vary before postprocessing)
    for f in output_dir.glob(f"{video_id}.*"):
        if f.suffix == ".wav":
            return f

    raise FileNotFoundError(f"Audio file not found for video {video_id}")


def get_video_info(video_id: str) -> dict:
    """Extract metadata for a YouTube video without downloading.

    Returns dict with title, channel, duration, description, thumbnail.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            raise ValueError(f"Could not extract info for video {video_id}")

        return {
            "title": info.get("title", ""),
            "channel": info.get("channel", "") or info.get("uploader", ""),
            "duration": info.get("duration", 0),
            "description": info.get("description", ""),
            "thumbnail": info.get("thumbnail", ""),
        }
