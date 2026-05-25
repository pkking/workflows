"""CLI entry point for yt-obsidian pipeline."""

import uuid
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console

from yt_obsidian.config import load_config
from yt_obsidian.downloader import download_video
from yt_obsidian.orchestrator import Orchestrator
from yt_obsidian.obsidian_writer import write_note
from yt_obsidian.traceability import TraceLogger, get_tool_version
from yt_obsidian.transcriber import transcribe
from yt_obsidian.youtube_search import search_topic

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="yt-obsidian")
def main():
    """YouTube to Obsidian multi-agent analysis pipeline."""
    pass


@main.command()
@click.argument("topic")
@click.option("--vault", default="./obsidian-vault", help="Obsidian vault path")
@click.option("--max-videos", default=5, type=int, help="Maximum videos to analyze")
@click.option("--output-dir", default="./yt-obsidian-output", help="Working directory")
@click.option(
    "--whisper-mode",
    type=click.Choice(["auto", "local", "api"]),
    default="auto",
    help="Whisper transcription mode",
)
@click.option("--dry-run", is_flag=True, help="Search only, don't download")
def analyze(topic, vault, max_videos, output_dir, whisper_mode, dry_run):
    """Search YouTube, analyze videos, and write notes to Obsidian vault."""
    console.print(f"[bold green]yt-obsidian[/bold green] - Analyzing: [cyan]{topic}[/cyan]")
    console.print("")

    config = load_config(
        vault_path=Path(vault),
        output_dir=Path(output_dir),
        max_videos=max_videos,
        whisper_mode=whisper_mode,
        dry_run=dry_run,
    )

    run_id = str(uuid.uuid4())[:8]
    logger = TraceLogger(run_id, topic, config.output_dir)

    console.print("[yellow]Searching YouTube...[/yellow]")
    search_start = datetime.now()
    videos = search_topic(topic, config.youtube_api_key, max_results_per_sort=10)
    search_duration = int((datetime.now() - search_start).total_seconds() * 1000)
    logger.record(
        stage="search",
        tool="youtube_api",
        tool_version="v3",
        inputs={"topic": topic, "max_results_per_sort": 10},
        outputs={"total_found": len(videos)},
        status="success",
        duration_ms=search_duration,
    )

    if not videos:
        console.print("[red]No videos found for this topic.[/red]")
        logger.save_json()
        return

    console.print(f"Found [bold]{len(videos)}[/bold] unique videos across 4 sort orders")

    if dry_run:
        console.print("\n[bold]Dry run - top results:[/bold]")
        for i, v in enumerate(videos[:config.max_videos], 1):
            console.print(f"  {i}. {v.title} ({v.channel}) - Score: {v.score:.2f}")
        logger.save_json()
        return

    selected = videos[:config.max_videos]
    console.print(f"Processing top [bold]{len(selected)}[/bold] videos\n")

    for video in selected:
        video_output_dir = config.output_dir / video.video_id
        video_output_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"[bold]Processing:[/bold] {video.title}")

        dl_start = datetime.now()
        asset = download_video(video.video_id, video_output_dir)
        dl_duration = int((datetime.now() - dl_start).total_seconds() * 1000)
        logger.record(
            stage="download",
            tool="yt-dlp",
            tool_version=get_tool_version("yt-dlp"),
            inputs={"video_id": video.video_id},
            outputs={
                "audio_path": str(asset.audio_path),
                "subtitle_path": str(asset.subtitle_path) if asset.subtitle_path else None,
            },
            status="success",
            duration_ms=dl_duration,
        )

        tx_start = datetime.now()
        result = transcribe(asset, config.whisper_mode)
        tx_duration = int((datetime.now() - tx_start).total_seconds() * 1000)
        logger.record(
            stage="transcribe",
            tool="whisper" if result.source != "subtitle" else "youtube_captions",
            tool_version=get_tool_version("whisper") if result.source != "subtitle" else "n/a",
            inputs={"video_id": video.video_id, "mode": config.whisper_mode},
            outputs={"source": result.source, "language": result.language, "text_length": len(result.text)},
            status="success",
            duration_ms=tx_duration,
        )

        agent_start = datetime.now()
        orchestrator = Orchestrator(video_output_dir, logger, config.vault_path)
        note = orchestrator.run(result, video)
        agent_duration = int((datetime.now() - agent_start).total_seconds() * 1000)
        logger.record(
            stage="agent",
            tool="pi",
            tool_version=get_tool_version("pi"),
            inputs={"video_id": video.video_id},
            outputs={"concepts": len(note.concepts), "methodologies": len(note.methodologies)},
            status="success",
            duration_ms=agent_duration,
        )

        obs_start = datetime.now()
        note_path = write_note(note, config.vault_path)
        obs_duration = int((datetime.now() - obs_start).total_seconds() * 1000)
        logger.record(
            stage="obsidian",
            tool="obsidian_writer",
            tool_version="0.1.0",
            inputs={"video_id": video.video_id, "slug": note.slug},
            outputs={"note_path": str(note_path)},
            status="success",
            duration_ms=obs_duration,
        )

        console.print(f"  [green]Written:[/green] {note_path}")
        console.print("")

    logger.save_json()
    console.print(f"[bold green]Complete![/bold green] Run ID: {run_id}")
    console.print(f"Trace log: {config.output_dir / f'workflow-run-{run_id}.json'}")


if __name__ == "__main__":
    main()
