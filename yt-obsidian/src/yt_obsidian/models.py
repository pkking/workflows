from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VideoSearchResult(BaseModel):
    video_id: str
    title: str
    channel: str
    published_at: datetime
    view_count: int
    comment_count: int
    like_count: int
    duration_seconds: int
    score: float

    @staticmethod
    def compute_score(
        view_count: int,
        comment_count: int,
        like_count: int,
        published_at: datetime,
    ) -> float:
        import math

        now = datetime.now(published_at.tzinfo) if published_at.tzinfo else datetime.now()
        days_old = max((now - published_at).total_seconds() / 86400, 1)
        recency = 1.0 / math.log10(days_old + 1)

        views_norm = math.log10(view_count + 1)
        comments_norm = math.log10(comment_count + 1)
        rating = like_count / max(view_count, 1)

        score = (
            0.40 * views_norm
            + 0.25 * recency
            + 0.20 * comments_norm
            + 0.15 * rating
        )
        return round(score, 4)


class VideoAsset(BaseModel):
    video_id: str
    audio_path: Path
    subtitle_path: Path | None = None
    subtitle_language: str | None = None


class TranscriptionResult(BaseModel):
    video_id: str
    text: str
    language: str
    source: Literal["subtitle", "whisper_local", "whisper_api"]
    segments: list[dict] = Field(default_factory=list)


class AgentOutput(BaseModel):
    role: str
    content: str
    timestamp: datetime
    input_hash: str


class ConceptNote(BaseModel):
    title: str
    slug: str
    tags: list[str] = Field(default_factory=list)
    concepts: list[dict] = Field(default_factory=list)
    methodologies: list[dict] = Field(default_factory=list)
    source_videos: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    trace_file: str
    channel: str = ""
    duration_seconds: int = 0
    published_at: str = ""


class TraceRecord(BaseModel):
    run_id: str
    stage: str
    timestamp: datetime = Field(default_factory=datetime.now)
    tool: str
    tool_version: str
    inputs: dict = Field(default_factory=dict)
    outputs: dict = Field(default_factory=dict)
    duration_ms: int
    status: Literal["success", "error", "skipped"]


class WorkflowRun(BaseModel):
    run_id: str
    topic: str
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: datetime | None = None
    config: dict = Field(default_factory=dict)
    records: list[TraceRecord] = Field(default_factory=list)
