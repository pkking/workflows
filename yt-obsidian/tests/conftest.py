import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_youtube_api():
    """Mock googleapiclient.discovery.build to return sample search results."""
    sample_search_response = {
        "items": [
            {
                "id": {"kind": "youtube#video", "videoId": "dQw4w9WgXcQ"},
                "snippet": {
                    "title": "Sample Video Title",
                    "channelTitle": "Sample Channel",
                    "publishedAt": "2024-01-15T10:00:00Z",
                },
            }
        ]
    }

    sample_stats_response = {
        "items": [
            {
                "id": "dQw4w9WgXcQ",
                "statistics": {
                    "viewCount": "1000000",
                    "commentCount": "5000",
                    "likeCount": "50000",
                },
                "contentDetails": {"duration": "PT10M30S"},
            }
        ]
    }

    mock_videos = MagicMock()
    mock_videos.list.return_value.execute.return_value = sample_stats_response

    mock_search = MagicMock()
    mock_search.list.return_value.execute.return_value = sample_search_response

    mock_service = MagicMock()
    mock_service.search.return_value = mock_search
    mock_service.videos.return_value = mock_videos

    with patch("yt_obsidian.youtube_search.build", return_value=mock_service) as mock_build:
        yield mock_build


@pytest.fixture
def mock_pi_cli():
    """Mock subprocess.run to simulate pi CLI returning agent outputs."""
    sample_agent_output = """## Concepts

### Concept 1: Sample Concept
Definition of the sample concept as described in the video.

## Methodologies

### Methodology 1: Sample Method
1. Step one
2. Step two
3. Step three
"""

    def _mock_run(*args, **kwargs):
        output_path = None
        for i, arg in enumerate(args[0]):
            if arg == "--output" and i + 1 < len(args[0]):
                output_path = args[0][i + 1]
                break
        if output_path:
            Path(output_path).write_text(sample_agent_output)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    with patch("yt_obsidian.agents.subprocess.run", side_effect=_mock_run) as mock:
        yield mock


@pytest.fixture
def sample_video_result():
    """Return a sample VideoSearchResult instance."""
    from yt_obsidian.models import VideoSearchResult

    return VideoSearchResult(
        video_id="dQw4w9WgXcQ",
        title="Sample Video Title",
        channel="Sample Channel",
        published_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        view_count=1000000,
        comment_count=5000,
        like_count=50000,
        duration_seconds=630,
        score=2.3456,
    )


@pytest.fixture
def sample_transcription():
    """Return a sample TranscriptionResult instance."""
    from yt_obsidian.models import TranscriptionResult

    return TranscriptionResult(
        video_id="dQw4w9WgXcQ",
        text="This is a sample transcription of a video transcript.",
        language="en",
        source="subtitle",
        segments=[
            {"id": 0, "start": 0.0, "end": 5.0, "text": "This is a sample transcription"},
            {"id": 1, "start": 5.0, "end": 10.0, "text": "of a video transcript."},
        ],
    )


@pytest.fixture
def tmp_vault(tmp_path):
    """Return a temporary directory for Obsidian vault testing."""
    vault = tmp_path / "test-vault"
    vault.mkdir()
    (vault / "sources" / "youtube").mkdir(parents=True)
    (vault / "concepts").mkdir()
    (vault / "methodologies").mkdir()
    (vault / "traces").mkdir()
    return vault


@pytest.fixture
def tmp_output(tmp_path):
    """Return a temporary directory for output testing."""
    output = tmp_path / "test-output"
    output.mkdir()
    return output
