import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from yt_obsidian.models import ConceptNote


def write_note(note: ConceptNote, vault_path: Path) -> Path:
    sources_dir = vault_path / "sources" / "youtube"
    concepts_dir = vault_path / "concepts"
    methodologies_dir = vault_path / "methodologies"

    sources_dir.mkdir(parents=True, exist_ok=True)
    concepts_dir.mkdir(parents=True, exist_ok=True)
    methodologies_dir.mkdir(parents=True, exist_ok=True)

    main_note_path = sources_dir / f"{note.slug}.md"
    main_note_path.write_text(_build_main_note(note), encoding="utf-8")

    for concept in note.concepts:
        concept_slug = _generate_slug(concept.get("name", "untitled"))
        concept_path = concepts_dir / f"{concept_slug}.md"
        concept_path.write_text(_build_concept_note(concept, note), encoding="utf-8")

    for methodology in note.methodologies:
        method_slug = _generate_slug(methodology.get("name", "untitled"))
        method_path = methodologies_dir / f"{method_slug}.md"
        method_path.write_text(_build_methodology_note(methodology, note), encoding="utf-8")

    return main_note_path


def _build_frontmatter(note: ConceptNote) -> str:
    now = datetime.now(timezone.utc)
    fm = {
        "title": note.title,
        "aliases": [],
        "tags": note.tags,
        "status": "processed",
        "created": now.isoformat(),
        "updated": now.isoformat(),
        "source": note.source_videos[0] if note.source_videos else "",
        "video_id": note.source_videos[0] if note.source_videos else "",
        "channel": note.channel,
        "duration": note.duration_seconds,
        "published": note.published_at,
        "concepts_count": len(note.concepts),
        "methodologies_count": len(note.methodologies),
        "trace_file": note.trace_file,
    }
    return yaml.dump(fm, default_flow_style=False, sort_keys=False)


def _format_concepts(concepts: list[dict]) -> str:
    if not concepts:
        return ""
    lines = ["## Key Concepts\n"]
    for concept in concepts:
        name = concept.get("name", "Untitled")
        definition = concept.get("definition", "")
        context = concept.get("context", "")
        lines.append(f"### {name}\n")
        lines.append(f"{definition}\n")
        lines.append(f"**Context:** {context}\n")
    return "\n".join(lines) + "\n"


def _format_methodologies(methodologies: list[dict]) -> str:
    if not methodologies:
        return ""
    lines = ["## Methodologies\n"]
    for method in methodologies:
        name = method.get("name", "Untitled")
        description = method.get("description", "")
        steps = method.get("steps", [])
        best_practices = method.get("best_practices", "")
        lines.append(f"### {name}\n")
        lines.append(f"{description}\n")
        lines.append("**Steps:**")
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")
        lines.append("")
        lines.append(f"**Best Practices:** {best_practices}\n")
    return "\n".join(lines) + "\n"


def _generate_slug(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def _build_main_note(note: ConceptNote) -> str:
    frontmatter = _build_frontmatter(note)
    concepts_md = _format_concepts(note.concepts)
    methodologies_md = _format_methodologies(note.methodologies)

    body_parts = [f"# {note.title}\n"]
    if concepts_md:
        body_parts.append(concepts_md)
    if methodologies_md:
        body_parts.append(methodologies_md)

    return f"---\n{frontmatter}---\n\n" + "\n".join(body_parts)


def _build_concept_note(concept: dict, parent: ConceptNote) -> str:
    now = datetime.now(timezone.utc)
    name = concept.get("name", "Untitled")
    slug = _generate_slug(name)
    fm = {
        "title": name,
        "aliases": [],
        "tags": parent.tags + ["concept"],
        "status": "processed",
        "created": now.isoformat(),
        "updated": now.isoformat(),
        "source": f"[[{parent.slug}]]",
        "definition": concept.get("definition", ""),
        "context": concept.get("context", ""),
    }
    frontmatter = yaml.dump(fm, default_flow_style=False, sort_keys=False)
    body = f"# {name}\n\n{concept.get('definition', '')}\n\n**Context:** {concept.get('context', '')}\n"
    return f"---\n{frontmatter}---\n\n{body}"


def _build_methodology_note(methodology: dict, parent: ConceptNote) -> str:
    now = datetime.now(timezone.utc)
    name = methodology.get("name", "Untitled")
    slug = _generate_slug(name)
    steps = methodology.get("steps", [])
    fm = {
        "title": name,
        "aliases": [],
        "tags": parent.tags + ["methodology"],
        "status": "processed",
        "created": now.isoformat(),
        "updated": now.isoformat(),
        "source": f"[[{parent.slug}]]",
        "description": methodology.get("description", ""),
        "steps_count": len(steps),
        "best_practices": methodology.get("best_practices", ""),
    }
    frontmatter = yaml.dump(fm, default_flow_style=False, sort_keys=False)

    steps_md = "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1))
    body = (
        f"# {name}\n\n"
        f"{methodology.get('description', '')}\n\n"
        f"**Steps:**\n{steps_md}\n\n"
        f"**Best Practices:** {methodology.get('best_practices', '')}\n"
    )
    return f"---\n{frontmatter}---\n\n{body}"
