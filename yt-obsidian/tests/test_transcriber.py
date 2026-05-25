import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from yt_obsidian.models import VideoAsset, TranscriptionResult
from yt_obsidian.transcriber import _convert_subtitle_to_text, transcribe


class TestConvertSubtitleToText:
    def test_srt_format(self, tmp_path):
        srt = """1
00:00:00,000 --> 00:00:05,000
Hello world

2
00:00:05,000 --> 00:00:10,000
This is a test
"""
        sub_path = tmp_path / "test.srt"
        sub_path.write_text(srt)
        result = _convert_subtitle_to_text(sub_path)
        assert "Hello world" in result
        assert "This is a test" in result
        assert "-->" not in result

    def test_vtt_format(self, tmp_path):
        vtt = """WEBVTT

00:00:00.000 --> 00:00:05.000
Hello from VTT
"""
        sub_path = tmp_path / "test.vtt"
        sub_path.write_text(vtt)
        result = _convert_subtitle_to_text(sub_path)
        assert "Hello from VTT" in result


class TestTranscribe:
    def test_uses_subtitle_when_available(self, tmp_path):
        sub_path = tmp_path / "sub.srt"
        sub_path.write_text("1\n00:00:00 --> 00:00:05\nTest subtitle\n")
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"fake audio")
        asset = VideoAsset(
            video_id="abc123",
            audio_path=audio_path,
            subtitle_path=sub_path,
        )
        result = transcribe(asset, whisper_mode="auto")
        assert result.source == "subtitle"
        assert "Test subtitle" in result.text

    def test_raises_when_no_method_available(self, tmp_path):
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"fake audio")
        asset = VideoAsset(
            video_id="abc123",
            audio_path=audio_path,
            subtitle_path=None,
        )
        with patch("yt_obsidian.transcriber._whisper_local_transcribe", side_effect=ImportError("whisper not installed")):
            with pytest.raises(ImportError, match="whisper not installed"):
                transcribe(asset, whisper_mode="local")

    def test_auto_mode_falls_back_to_api(self, tmp_path):
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"fake audio")
        asset = VideoAsset(
            video_id="abc123",
            audio_path=audio_path,
            subtitle_path=None,
        )
        with patch("yt_obsidian.transcriber._whisper_local_transcribe", side_effect=ImportError):
            with patch("yt_obsidian.transcriber._whisper_api_transcribe") as mock_api:
                mock_api.return_value = TranscriptionResult(
                    video_id="abc123", text="API result", language="en", source="whisper_api",
                )
                import os
                os.environ["OPENAI_API_KEY"] = "test-key"
                try:
                    result = transcribe(asset, whisper_mode="auto")
                    assert result.source == "whisper_api"
                    assert mock_api.called
                finally:
                    del os.environ["OPENAI_API_KEY"]
