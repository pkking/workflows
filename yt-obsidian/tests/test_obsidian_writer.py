from datetime import datetime, timezone

from yt_obsidian.models import ConceptNote
from yt_obsidian.obsidian_writer import write_note, _generate_slug


class TestGenerateSlug:
    def test_basic(self):
        assert _generate_slug("Hello World") == "hello-world"

    def test_special_chars(self):
        assert _generate_slug("C++ Programming") == "c-programming"


class TestWriteNote:
    def test_writes_main_note(self, tmp_path):
        note = ConceptNote(
            title="Test Video Analysis",
            slug="test-video-analysis",
            tags=["concepts/test"],
            concepts=[{"name": "Test Concept", "definition": "A test concept", "context": ""}],
            methodologies=[{"name": "Test Method", "description": "A test method", "steps": ["step 1"], "best_practices": ""}],
            source_videos=["abc123"],
            trace_file="trace.md",
            channel="Test Channel",
            duration_seconds=300,
            published_at="2024-01-15T10:00:00Z",
        )
        result = write_note(note, tmp_path)
        assert result.exists()
        content = result.read_text()
        assert "Test Video Analysis" in content
        assert "Test Channel" in content
        assert "300" in content

    def test_creates_directory_structure(self, tmp_path):
        note = ConceptNote(
            title="Test",
            slug="test",
            tags=[],
            concepts=[],
            methodologies=[],
            source_videos=["abc123"],
            trace_file="trace.md",
        )
        write_note(note, tmp_path)
        assert (tmp_path / "sources" / "youtube").exists()
        assert (tmp_path / "concepts").exists()
        assert (tmp_path / "methodologies").exists()

    def test_writes_concept_notes(self, tmp_path):
        note = ConceptNote(
            title="Test",
            slug="test",
            tags=[],
            concepts=[{"name": "Concept A", "definition": "Def A", "context": ""}],
            methodologies=[],
            source_videos=["abc123"],
            trace_file="trace.md",
        )
        write_note(note, tmp_path)
        concept_path = tmp_path / "concepts" / "concept-a.md"
        assert concept_path.exists()
        content = concept_path.read_text()
        assert "Concept A" in content

    def test_writes_methodology_notes(self, tmp_path):
        note = ConceptNote(
            title="Test",
            slug="test",
            tags=[],
            concepts=[],
            methodologies=[{"name": "Method B", "description": "Desc B", "steps": ["1", "2"], "best_practices": ""}],
            source_videos=["abc123"],
            trace_file="trace.md",
        )
        write_note(note, tmp_path)
        method_path = tmp_path / "methodologies" / "method-b.md"
        assert method_path.exists()
