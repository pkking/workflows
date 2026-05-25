import hashlib
import subprocess
from datetime import datetime
from pathlib import Path

from yt_obsidian.models import AgentOutput

ROLES = {
    "concept_extractor": (
        "You are a Concept Extractor specializing in identifying key concepts, "
        "definitions, frameworks, and mental models from video transcripts.\n"
        "\n"
        "Your task:\n"
        "1. Identify all key concepts mentioned in the transcript\n"
        "2. For each concept, provide: name, clear definition, context/examples from the video\n"
        "3. Identify relationships between concepts\n"
        "4. Note any novel insights or unique perspectives\n"
        "\n"
        "Format your output as structured markdown with clear headings.\n"
        "Be thorough but precise. Do not invent concepts not present in the transcript."
    ),
    "methodology_analyst": (
        "You are a Methodology Analyst specializing in extracting step-by-step methods, "
        "processes, techniques, and best practices from video transcripts.\n"
        "\n"
        "Your task:\n"
        "1. Extract all methodologies, frameworks, and processes described\n"
        "2. For each methodology, provide: name, step-by-step breakdown, prerequisites, "
        "expected outcomes, common pitfalls mentioned\n"
        "3. Identify best practices and recommendations\n"
        "4. Note any tools, resources, or references mentioned\n"
        "\n"
        "Format your output as structured markdown with numbered steps.\n"
        "Be precise about what is explicitly stated vs implied."
    ),
    "skeptic": (
        "You are a Skeptic/Challenger. Your role is to critically analyze the outputs "
        "from the Concept Extractor and Methodology Analyst.\n"
        "\n"
        "Your task:\n"
        "1. Identify any concepts or methodologies that appear to be hallucinations "
        "(not supported by the transcript)\n"
        "2. Point out gaps, contradictions, or overgeneralizations\n"
        "3. Challenge assumptions and ask: 'Is this really what the video says?'\n"
        "4. Identify missing concepts or methodologies that should have been extracted\n"
        "5. Flag any vague or ambiguous extractions that need clarification\n"
        "\n"
        "Be thorough and rigorous. Your job is to ensure accuracy before content goes "
        "into the knowledge base.\n"
        "\n"
        "If everything is accurate and complete, output: NO_CHALLENGES"
    ),
    "synthesizer": (
        "You are the Synthesizer/Integrator. Your role is to reach consensus across all "
        "agent outputs and produce the final structured Obsidian-ready note.\n"
        "\n"
        "Your task:\n"
        "1. Review the Concept Extractor and Methodology Analyst outputs\n"
        "2. Consider the Skeptic's challenges and resolve each one\n"
        "3. For challenged items: either keep (with clarification), modify, or remove\n"
        "4. Produce a final consolidated output with:\n"
        "   - Verified concepts (only those supported by transcript)\n"
        "   - Verified methodologies (only those explicitly described)\n"
        "   - Confidence level for each item (high/medium/low)\n"
        "5. Format as Obsidian-ready markdown with Dataview frontmatter\n"
        "\n"
        "If there are unresolved conflicts, flag them explicitly rather than forcing consensus."
    ),
}


def _build_prompt(
    role: str,
    transcript: str,
    previous_outputs: tuple = (),
    instruction: str | None = None,
) -> str:
    parts = [ROLES[role]]

    truncated = transcript[:50000] if len(transcript) > 50000 else transcript
    parts.append(f"\n\n### Transcript\n{truncated}")

    if previous_outputs:
        parts.append("\n\n### Previous Outputs\n")
        for i, output in enumerate(previous_outputs, 1):
            parts.append(f"\n--- Output {i} ---\n{output}\n")

    if instruction:
        parts.append(f"\n\n### Additional Instruction\n{instruction}")

    return "".join(parts)


def invoke_agent(
    role: str,
    transcript: str,
    output_dir: Path,
    *previous_outputs: str,
    instruction: str | None = None,
    round_num: int = 0,
) -> AgentOutput:
    prompt_text = _build_prompt(role, transcript, previous_outputs, instruction)

    suffix = f"_round{round_num}" if round_num > 0 else ""
    prompt_file = output_dir / f"{role}{suffix}_prompt.md"
    output_file = output_dir / f"{role}{suffix}_output.md"

    prompt_file.write_text(prompt_text)

    subprocess.run(
        ["pi", "--prompt", prompt_text, "--output", str(output_file)],
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )

    output_content = output_file.read_text()
    input_hash = hashlib.sha256(prompt_text.encode()).hexdigest()[:12]

    return AgentOutput(
        role=role,
        content=output_content,
        timestamp=datetime.now(),
        input_hash=input_hash,
    )
