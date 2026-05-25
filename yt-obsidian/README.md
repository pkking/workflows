# yt-obsidian

Multi-agent YouTube video analysis pipeline that extracts concepts and methodologies into an Obsidian vault.

## Features

- **Smart YouTube Search**: Searches across 4 sort orders (views, date, rating, relevance) with weighted ranking
- **Subtitle-First Transcription**: Extracts YouTube captions first (free/fast), falls back to Whisper only when needed
- **Multi-Agent Analysis**: Uses `pi` framework with 4 specialized agents in a challenge/consensus pattern:
  - Concept Extractor: Identifies key concepts, definitions, frameworks
  - Methodology Analyst: Extracts step-by-step methods, processes, techniques
  - Skeptic: Challenges accuracy, catches hallucinations, identifies gaps
  - Synthesizer: Reaches consensus, produces final structured output
- **Full Traceability**: JSON logs + Markdown trace files for every stage
- **Obsidian-Ready Notes**: Dataview-compatible frontmatter, nested tags, kebab-case filenames

## Installation

```bash
cd yt-obsidian
pip install -e .
# Optional: for local Whisper transcription
pip install -e ".[whisper]"
```

## Usage

```bash
# Basic usage - search topic, analyze top 5 videos, write to Obsidian vault
yt-obsidian analyze "machine learning fundamentals" --vault ~/ObsidianVault

# Custom options
yt-obsidian analyze "react best practices" \
  --vault ~/ObsidianVault \
  --max-videos 3 \
  --whisper-mode api \
  --output-dir ./yt-output

# Dry run - search only, don't download
yt-obsidian analyze "python design patterns" --dry-run
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `YOUTUBE_API_KEY` | Yes | YouTube Data API v3 key |
| `OPENAI_API_KEY` | Optional | Required for Whisper API transcription mode |

## CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--vault` | `./obsidian-vault` | Obsidian vault path |
| `--max-videos` | `5` | Maximum videos to analyze |
| `--output-dir` | `./yt-obsidian-output` | Working directory for downloads/logs |
| `--whisper-mode` | `auto` | Transcription: `auto`, `local`, `api` |
| `--dry-run` | `false` | Search only, skip download/analysis |

## Output Structure

```
obsidian-vault/
├── sources/
│   └── youtube/
│       ├── video-abc123.md          # Analyzed video note
│       └── video-def456.md
├── concepts/
│   ├── concept-name-1.md            # Extracted concept note
│   └── concept-name-2.md
├── methodologies/
│   ├── methodology-name-1.md        # Extracted methodology note
│   └── methodology-name-2.md
└── traces/
    ├── video-abc123-trace.md        # Full trace of analysis process
    └── video-def456-trace.md

yt-obsidian-output/
└── workflow-run-{run_id}.json       # Machine-readable trace log
```

## Architecture

```
YouTube API (search) → yt-dlp (download) → Transcription → Multi-Agent (pi) → Obsidian Notes
                                                    ↓
                                          Challenge/Consensus Loop
                                          (up to 3 rounds)
```
