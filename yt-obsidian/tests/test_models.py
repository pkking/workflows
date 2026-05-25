from datetime import datetime, timezone

from yt_obsidian.models import VideoSearchResult


class TestVideoSearchResult:
    def test_compute_score_basic(self):
        published = datetime(2024, 1, 15, tzinfo=timezone.utc)
        score = VideoSearchResult.compute_score(
            view_count=1000000,
            comment_count=5000,
            like_count=50000,
            published_at=published,
        )
        assert isinstance(score, float)
        assert score > 0

    def test_compute_score_recent_video(self):
        recent = datetime.now(timezone.utc)
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        recent_score = VideoSearchResult.compute_score(1000000, 5000, 50000, recent)
        old_score = VideoSearchResult.compute_score(1000000, 5000, 50000, old)
        assert recent_score > old_score

    def test_compute_score_high_views(self):
        published = datetime(2024, 1, 15, tzinfo=timezone.utc)
        high_views = VideoSearchResult.compute_score(10000000, 5000, 50000, published)
        low_views = VideoSearchResult.compute_score(100, 5000, 50000, published)
        assert high_views >= 0
        assert low_views >= 0
