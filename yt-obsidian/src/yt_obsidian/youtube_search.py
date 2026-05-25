import re
from datetime import datetime

from googleapiclient.discovery import build

from yt_obsidian.models import VideoSearchResult


def search_topic(
    topic: str, api_key: str, max_results_per_sort: int = 10
) -> list[VideoSearchResult]:
    youtube = build("youtube", "v3", developerKey=api_key)

    sort_orders = ["viewCount", "date", "rating", "relevance"]
    seen_ids: set[str] = set()
    results: list[VideoSearchResult] = []

    for sort in sort_orders:
        request = youtube.search().list(
            part="snippet",
            q=topic,
            type="video",
            order=sort,
            maxResults=max_results_per_sort,
        )
        response = request.execute()

        for item in response.get("items", []):
            if item.get("id", {}).get("kind") != "youtube#video":
                continue
            video_id = item["id"]["videoId"]
            if video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            results.append(_parse_video_item(item))

    if not results:
        return []

    stats = _get_statistics([r.video_id for r in results], api_key)

    for result in results:
        video_stats = stats.get(result.video_id, {})
        result.view_count = video_stats.get("view_count", 0)
        result.comment_count = video_stats.get("comment_count", 0)
        result.like_count = video_stats.get("like_count", 0)
        result.duration_seconds = video_stats.get("duration_seconds", 0)
        result.score = VideoSearchResult.compute_score(
            result.view_count,
            result.comment_count,
            result.like_count,
            result.published_at,
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return results


def _get_statistics(video_ids: list[str], api_key: str) -> dict[str, dict]:
    youtube = build("youtube", "v3", developerKey=api_key)
    stats_map: dict[str, dict] = {}

    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        request = youtube.videos().list(
            part="statistics,contentDetails", id=",".join(batch)
        )
        response = request.execute()

        for item in response.get("items", []):
            vid = item["id"]
            statistics = item.get("statistics", {})
            content_details = item.get("contentDetails", {})

            duration_str = content_details.get("duration", "PT0S")
            duration_seconds = _parse_duration(duration_str)

            stats_map[vid] = {
                "view_count": int(statistics.get("viewCount", 0)),
                "comment_count": int(statistics.get("commentCount", 0)),
                "like_count": int(statistics.get("likeCount", 0)),
                "duration_seconds": duration_seconds,
            }

    return stats_map


def _parse_video_item(item: dict) -> VideoSearchResult:
    snippet = item["snippet"]
    return VideoSearchResult(
        video_id=item["id"]["videoId"],
        title=snippet["title"],
        channel=snippet["channelTitle"],
        published_at=datetime.fromisoformat(snippet["publishedAt"]),
        view_count=0,
        comment_count=0,
        like_count=0,
        duration_seconds=0,
        score=0.0,
    )


def _parse_duration(duration_str: str) -> int:
    pattern = r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
    match = re.match(pattern, duration_str)
    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds
