import os
from pathlib import Path

from yt_obsidian.models import TranscriptionResult, VideoAsset


def transcribe(asset: VideoAsset, whisper_mode: str = "auto") -> TranscriptionResult:
    if asset.subtitle_path and asset.subtitle_path.exists():
        text = _convert_subtitle_to_text(asset.subtitle_path)
        return TranscriptionResult(
            video_id=asset.video_id,
            text=text,
            language="en",
            source="subtitle",
        )

    if whisper_mode in ("auto", "local"):
        try:
            return _whisper_local_transcribe(asset.audio_path, asset.video_id)
        except ImportError:
            if whisper_mode == "local":
                raise

    if whisper_mode in ("auto", "api") and os.environ.get("OPENAI_API_KEY"):
        return _whisper_api_transcribe(asset.audio_path, asset.video_id)

    methods_tried = []
    if whisper_mode in ("auto", "local"):
        methods_tried.append("local whisper (not installed)")
    if whisper_mode in ("auto", "api"):
        if os.environ.get("OPENAI_API_KEY"):
            methods_tried.append("API (failed)")
        else:
            methods_tried.append("API (no OPENAI_API_KEY)")

    raise ValueError(
        f"No transcription method available. Methods tried: {', '.join(methods_tried)}. "
        "Install openai-whisper for local transcription (pip install openai-whisper), "
        "or set OPENAI_API_KEY for API transcription."
    )


def _convert_subtitle_to_text(subtitle_path: Path) -> str:
    content = subtitle_path.read_text(encoding="utf-8")
    lines = content.strip().splitlines()
    text_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "-->" in line:
            continue
        if line.isdigit():
            continue
        text_lines.append(line)

    return " ".join(text_lines)


def _whisper_api_transcribe(audio_path: Path, video_id: str) -> TranscriptionResult:
    from openai import OpenAI

    client = OpenAI()
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=f,
            language="en",
            response_format="verbose_json",
        )

    segments = []
    if hasattr(response, "segments"):
        for seg in response.segments:
            segments.append({
                "id": seg.get("id"),
                "start": seg.get("start"),
                "end": seg.get("end"),
                "text": seg.get("text"),
            })

    return TranscriptionResult(
        video_id=video_id,
        text=response.text,
        language=response.language or "en",
        source="whisper_api",
        segments=segments,
    )


def _whisper_local_transcribe(audio_path: Path, video_id: str) -> TranscriptionResult:
    try:
        import whisper
    except ImportError:
        raise ImportError(
            "openai-whisper is not installed. "
            "Install it with: pip install openai-whisper"
        )

    model = whisper.load_model("base")
    result = model.transcribe(str(audio_path), language="en")

    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "id": seg.get("id"),
            "start": seg.get("start"),
            "end": seg.get("end"),
            "text": seg.get("text"),
        })

    return TranscriptionResult(
        video_id=video_id,
        text=result.get("text", "").strip(),
        language=result.get("language", "en"),
        source="whisper_local",
        segments=segments,
    )


def check_whisper_available() -> bool:
    try:
        import whisper
        return True
    except ImportError:
        return False
