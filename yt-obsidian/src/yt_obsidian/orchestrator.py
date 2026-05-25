import re
from datetime import datetime
from pathlib import Path

from yt_obsidian.agents import invoke_agent
from yt_obsidian.models import AgentOutput, ConceptNote, TranscriptionResult, VideoSearchResult
from yt_obsidian.traceability import TraceLogger, get_tool_version


class Orchestrator:
    def __init__(self, output_dir: Path, trace_logger: TraceLogger, vault_path: Path | None = None):
        self.output_dir = output_dir
        self.trace_logger = trace_logger
        self.vault_path = vault_path or output_dir.parent
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, transcript: TranscriptionResult, video: VideoSearchResult) -> ConceptNote:
        agent_rounds: list[dict] = []

        start = datetime.now()
        concept_out = invoke_agent(
            "concept_extractor", transcript.text, self.output_dir
        )
        method_out = invoke_agent(
            "methodology_analyst", transcript.text, self.output_dir
        )
        duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        self.trace_logger.record(
            stage="phase1_extraction",
            tool="pi",
            tool_version=get_tool_version("pi"),
            inputs={"video_id": transcript.video_id},
            outputs={
                "concept_extractor_hash": concept_out.input_hash,
                "methodology_analyst_hash": method_out.input_hash,
            },
            status="success",
            duration_ms=duration_ms,
        )

        start = datetime.now()
        skeptic_out = invoke_agent(
            "skeptic",
            transcript.text,
            self.output_dir,
            concept_out.content,
            method_out.content,
        )
        duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        self.trace_logger.record(
            stage="phase2_skeptic",
            tool="pi",
            tool_version=get_tool_version("pi"),
            inputs={
                "concept_hash": concept_out.input_hash,
                "method_hash": method_out.input_hash,
            },
            outputs={"skeptic_hash": skeptic_out.input_hash},
            status="success",
            duration_ms=duration_ms,
        )

        current_concept = concept_out
        current_method = method_out
        current_skeptic = skeptic_out
        round_num = 0

        while self._has_challenges(current_skeptic.content) and round_num < 3:
            round_num += 1
            agent_rounds.append({
                "role": "skeptic",
                "round": round_num,
                "output_summary": current_skeptic.content[:200],
                "challenge_status": "challenged",
            })

            start = datetime.now()
            current_concept = invoke_agent(
                "concept_extractor",
                transcript.text,
                self.output_dir,
                current_concept.content,
                current_method.content,
                current_skeptic.content,
                instruction=f"Round {round_num}: Address the skeptic's challenges. Revise your extraction accordingly.",
                round_num=round_num,
            )
            current_method = invoke_agent(
                "methodology_analyst",
                transcript.text,
                self.output_dir,
                current_concept.content,
                current_method.content,
                current_skeptic.content,
                instruction=f"Round {round_num}: Address the skeptic's challenges. Revise your extraction accordingly.",
                round_num=round_num,
            )
            current_skeptic = invoke_agent(
                "skeptic",
                transcript.text,
                self.output_dir,
                current_concept.content,
                current_method.content,
                round_num=round_num,
            )
            duration_ms = int((datetime.now() - start).total_seconds() * 1000)
            self.trace_logger.record(
                stage=f"phase2b_challenge_round_{round_num}",
                tool="pi",
                tool_version=get_tool_version("pi"),
                inputs={"round": round_num},
                outputs={
                    "concept_hash": current_concept.input_hash,
                    "method_hash": current_method.input_hash,
                    "skeptic_hash": current_skeptic.input_hash,
                },
                status="success",
                duration_ms=duration_ms,
            )

        if round_num > 0:
            agent_rounds[-1]["challenge_status"] = (
                "resolved" if not self._has_challenges(current_skeptic.content) else "max_rounds_reached"
            )

        start = datetime.now()
        synthesizer_out = invoke_agent(
            "synthesizer",
            transcript.text,
            self.output_dir,
            current_concept.content,
            current_method.content,
            current_skeptic.content,
        )
        duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        self.trace_logger.record(
            stage="phase3_synthesis",
            tool="pi",
            tool_version=get_tool_version("pi"),
            inputs={
                "concept_hash": current_concept.input_hash,
                "method_hash": current_method.input_hash,
                "challenge_rounds": round_num,
            },
            outputs={"synthesizer_hash": synthesizer_out.input_hash},
            status="success",
            duration_ms=duration_ms,
        )

        agent_rounds.append({
            "role": "synthesizer",
            "round": round_num + 1,
            "output_summary": synthesizer_out.content[:200],
            "challenge_status": "consensus",
            "consensus": synthesizer_out.content[:500],
        })

        trace_path = self.trace_logger.save_markdown_trace(
            vault_path=self.vault_path,
            video_id=transcript.video_id,
            video_title=video.title,
            agent_rounds=agent_rounds,
        )

        return self._parse_concept_note(synthesizer_out.content, video, str(trace_path))

    @staticmethod
    def _has_challenges(skeptic_output: str) -> bool:
        return not bool(re.search(r"^\s*NO_CHALLENGES", skeptic_output, re.MULTILINE | re.IGNORECASE))

    def _parse_concept_note(
        self, content: str, video: VideoSearchResult, trace_file: str
    ) -> ConceptNote:
        title = self._extract_title(content) or video.title
        slug = self._generate_slug(title)
        concepts = self._extract_section(content, "Key Concepts") or self._extract_section(content, "Concepts") or []
        methodologies = self._extract_section(content, "Methodologies") or []
        tags = self._generate_tags(concepts, methodologies)

        return ConceptNote(
            title=title,
            slug=slug,
            tags=tags,
            concepts=concepts,
            methodologies=methodologies,
            source_videos=[video.video_id],
            trace_file=trace_file,
            channel=video.channel,
            duration_seconds=video.duration_seconds,
            published_at=video.published_at.isoformat(),
        )

    @staticmethod
    def _generate_slug(title: str) -> str:
        slug = title.lower()
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"[^a-z0-9-]", "", slug)
        slug = re.sub(r"-{2,}", "-", slug)
        return slug.strip("-")

    @staticmethod
    def _extract_title(content: str) -> str | None:
        match = re.match(r"^#\s+(.+)$", content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _extract_section(content: str, heading: str) -> list[dict]:
        pattern = rf"^##\s+{re.escape(heading)}\s*$"
        match = re.search(pattern, content, re.MULTILINE)
        if not match:
            return []

        start = match.end()
        next_heading = re.search(r"^##\s+", content[start:], re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(content)
        section_text = content[start:end].strip()

        items = []
        subheadings = list(re.finditer(r"^###\s+(.+)$", section_text, re.MULTILINE))

        if subheadings:
            for i, sh in enumerate(subheadings):
                name = sh.group(1).strip()
                block_start = sh.end()
                block_end = subheadings[i + 1].start() if i + 1 < len(subheadings) else len(section_text)
                block = section_text[block_start:block_end].strip()
                lines = [l.strip() for l in block.split("\n") if l.strip() and not l.strip().startswith("#")]
                text = " ".join(lines)

                if heading in ("Key Concepts", "Concepts"):
                    items.append({"name": name, "definition": text, "context": ""})
                else:
                    steps = re.findall(r"^\d+\.\s+(.+)$", block, re.MULTILINE)
                    items.append({
                        "name": name,
                        "description": text,
                        "steps": steps,
                        "best_practices": "",
                    })
        else:
            for line in section_text.split("\n"):
                line = line.strip()
                if line.startswith("- ") or line.startswith("* "):
                    name = line[2:].strip()
                    if heading in ("Key Concepts", "Concepts"):
                        items.append({"name": name, "definition": "", "context": ""})
                    else:
                        items.append({"name": name, "description": "", "steps": [], "best_practices": ""})
                elif re.match(r"^\d+\.\s+", line):
                    name = re.sub(r"^\d+\.\s+", "", line).strip()
                    if heading in ("Key Concepts", "Concepts"):
                        items.append({"name": name, "definition": "", "context": ""})
                    else:
                        items.append({"name": name, "description": "", "steps": [], "best_practices": ""})

        return items

    @staticmethod
    def _generate_tags(concepts: list[dict], methodologies: list[dict]) -> list[str]:
        tags: set[str] = set()
        for item in concepts + methodologies:
            name = item.get("name", "")
            if name:
                tag = Orchestrator._generate_slug(name)
                if tag:
                    tags.add(f"concepts/{tag}" if item in concepts else f"methodologies/{tag}")
        return sorted(tags)
