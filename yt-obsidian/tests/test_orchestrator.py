import pytest
from datetime import datetime, timezone

from yt_obsidian.models import VideoSearchResult, ConceptNote, TranscriptionResult
from yt_obsidian.orchestrator import Orchestrator


class TestExtractSection:
    def test_extract_concepts_with_subheadings(self):
        content = """
## Key Concepts

### Concept 1: Machine Learning
Machine learning is a subset of AI that enables systems to learn from data.

### Concept 2: Neural Networks
Neural networks are computing systems inspired by biological brains.
"""
        result = Orchestrator._extract_section(content, "Key Concepts")
        assert len(result) == 2
        assert result[0]["name"] == "Concept 1: Machine Learning"
        assert "Machine learning" in result[0]["definition"]
        assert result[1]["name"] == "Concept 2: Neural Networks"

    def test_extract_methodologies_with_steps(self):
        content = """
## Methodologies

### Agile Development
A iterative approach to software development.

1. Plan the sprint
2. Daily standups
3. Sprint review

### Test-Driven Development
Write tests before implementation.

1. Write failing test
2. Write minimal code
3. Refactor
"""
        result = Orchestrator._extract_section(content, "Methodologies")
        assert len(result) == 2
        assert result[0]["name"] == "Agile Development"
        assert len(result[0]["steps"]) == 3
        assert result[0]["steps"][0] == "Plan the sprint"

    def test_extract_section_missing_heading(self):
        content = "## Other Section\n\nSome content"
        result = Orchestrator._extract_section(content, "Key Concepts")
        assert result == []

    def test_extract_fallback_list_items(self):
        content = """
## Key Concepts

- Concept A
- Concept B
"""
        result = Orchestrator._extract_section(content, "Key Concepts")
        assert len(result) == 2
        assert result[0]["name"] == "Concept A"


class TestHasChallenges:
    def test_no_challenges(self):
        assert Orchestrator._has_challenges("NO_CHALLENGES") is False
        assert Orchestrator._has_challenges("  NO_CHALLENGES") is False
        assert Orchestrator._has_challenges("no_challenges") is False

    def test_has_challenges(self):
        assert Orchestrator._has_challenges("I found several issues") is True
        assert Orchestrator._has_challenges("The concept extractor missed X") is True


class TestGenerateSlug:
    def test_basic_slug(self):
        assert Orchestrator._generate_slug("Hello World") == "hello-world"

    def test_special_chars(self):
        assert Orchestrator._generate_slug("Hello, World!") == "hello-world"

    def test_multiple_spaces(self):
        assert Orchestrator._generate_slug("Hello   World") == "hello-world"

    def test_underscores(self):
        assert Orchestrator._generate_slug("Hello_World") == "hello-world"


class TestParseConceptNote:
    def test_parses_video_metadata(self, tmp_path):
        orchestrator = Orchestrator(tmp_path, None)
        video = VideoSearchResult(
            video_id="abc123",
            title="Test Video",
            channel="Test Channel",
            published_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            view_count=1000,
            comment_count=50,
            like_count=100,
            duration_seconds=630,
            score=1.5,
        )
        content = "# Test Video\n\n## Key Concepts\n\n### Concept 1\nDefinition here.\n\n## Methodologies\n\n### Method 1\nDescription.\n\n1. Step one"
        note = orchestrator._parse_concept_note(content, video, "trace.md")
        assert note.title == "Test Video"
        assert note.slug == "test-video"
        assert note.channel == "Test Channel"
        assert note.duration_seconds == 630
        assert note.published_at == "2024-01-15T10:00:00+00:00"
        assert len(note.concepts) == 1
        assert len(note.methodologies) == 1
