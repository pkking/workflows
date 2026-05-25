import json
from pathlib import Path

from yt_obsidian.traceability import TraceLogger, get_tool_version


class TestTraceLogger:
    def test_record_and_save_json(self, tmp_path):
        logger = TraceLogger("test-run", "test topic", tmp_path)
        logger.record(
            stage="search",
            tool="youtube_api",
            tool_version="v3",
            inputs={"topic": "test"},
            outputs={"total_found": 5},
            status="success",
            duration_ms=100,
        )
        json_path = logger.save_json()
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert data["run_id"] == "test-run"
        assert data["topic"] == "test topic"
        assert len(data["records"]) == 1
        assert data["records"][0]["stage"] == "search"

    def test_save_markdown_trace(self, tmp_path):
        logger = TraceLogger("test-run", "test topic", tmp_path)
        logger.record(
            stage="search",
            tool="youtube_api",
            tool_version="v3",
            inputs={"topic": "test"},
            outputs={},
            status="success",
            duration_ms=100,
        )
        vault = tmp_path / "vault"
        vault.mkdir()
        md_path = logger.save_markdown_trace(
            vault_path=vault,
            video_id="abc123",
            video_title="Test Video",
            agent_rounds=[
                {"role": "skeptic", "round": 1, "output_summary": "Found issues", "challenge_status": "resolved"},
                {"role": "synthesizer", "round": 2, "output_summary": "Consensus", "challenge_status": "consensus", "consensus": "All agreed"},
            ],
        )
        assert md_path.exists()
        content = md_path.read_text()
        assert "Test Video" in content
        assert "abc123" in content
        assert "search" in content
        assert "Agent Challenge Rounds" in content
        assert "Consensus" in content


class TestGetToolVersion:
    def test_unknown_tool(self):
        assert get_tool_version("nonexistent-tool") == "unknown"
