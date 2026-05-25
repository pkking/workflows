import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from yt_obsidian.models import TraceRecord, WorkflowRun


def get_tool_version(tool_name: str) -> str:
    if tool_name == "yt-dlp":
        try:
            result = subprocess.run(
                ["yt-dlp", "--version"],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"
    elif tool_name == "pi":
        try:
            result = subprocess.run(
                ["pi", "--version"],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"
    elif tool_name == "whisper":
        try:
            import whisper
            return whisper.__version__
        except Exception:
            return "unknown"
    return "unknown"


class TraceLogger:
    def __init__(self, run_id: str, topic: str, output_dir: Path):
        self.run_id = run_id
        self.topic = topic
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.start_time = datetime.now()
        self.records: list[TraceRecord] = []

    def record(
        self,
        stage: str,
        tool: str,
        tool_version: str,
        inputs: dict,
        outputs: dict,
        status: str,
        duration_ms: int,
    ) -> None:
        self.records.append(
            TraceRecord(
                run_id=self.run_id,
                stage=stage,
                tool=tool,
                tool_version=tool_version,
                inputs=inputs,
                outputs=outputs,
                status=status,
                duration_ms=duration_ms,
            )
        )

    def save_json(self) -> Path:
        workflow_run = WorkflowRun(
            run_id=self.run_id,
            topic=self.topic,
            start_time=self.start_time,
            end_time=datetime.now(),
            config={
                "yt-dlp": get_tool_version("yt-dlp"),
                "pi": get_tool_version("pi"),
                "whisper": get_tool_version("whisper"),
            },
            records=self.records,
        )
        json_path = self.output_dir / f"workflow-run-{self.run_id}.json"
        json_path.write_text(
            json.dumps(workflow_run.model_dump(mode="json"), indent=2, default=str),
            encoding="utf-8",
        )
        return json_path

    def save_markdown_trace(
        self,
        vault_path: Path,
        video_id: str,
        video_title: str,
        agent_rounds: list[dict],
    ) -> Path:
        traces_dir = vault_path / "traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        md_path = traces_dir / f"{video_id}-trace.md"

        lines: list[str] = []
        lines.append(f"# Trace: {video_title}")
        lines.append("")
        lines.append(f"**Run ID:** `{self.run_id}`")
        lines.append(f"**Video:** [{video_title}](https://youtube.com/watch?v={video_id})")
        lines.append(f"**Topic:** {self.topic}")
        lines.append(f"**Start:** {self.start_time.isoformat()}")
        lines.append(f"**End:** {datetime.now().isoformat()}")
        lines.append("")
        lines.append("## Stages")
        lines.append("")

        for rec in self.records:
            lines.append(f"### {rec.stage}")
            lines.append("")
            lines.append(f"- **Time:** {rec.timestamp.isoformat()}")
            lines.append(f"- **Tool:** {rec.tool} ({rec.tool_version})")
            lines.append(f"- **Status:** {rec.status}")
            lines.append(f"- **Duration:** {rec.duration_ms}ms")
            if rec.inputs:
                lines.append(f"- **Inputs:** `{json.dumps(rec.inputs, default=str)[:200]}`")
            if rec.outputs:
                lines.append(f"- **Outputs:** `{json.dumps(rec.outputs, default=str)[:200]}`")
            lines.append("")

        if agent_rounds:
            lines.append("## Agent Challenge Rounds")
            lines.append("")

            for i, rnd in enumerate(agent_rounds, start=1):
                lines.append(f"### Round {i}")
                lines.append("")
                lines.append(f"- **Agent Role:** {rnd.get('role', 'unknown')}")
                lines.append(f"- **Output Summary:** {rnd.get('output_summary', rnd.get('content', ''))[:300]}")
                lines.append(f"- **Challenge Status:** {rnd.get('challenge_status', 'N/A')}")
                lines.append("")

        lines.append("## Consensus")
        lines.append("")
        consensus = agent_rounds[-1].get("consensus", "No consensus reached") if agent_rounds else "No agent rounds"
        lines.append(str(consensus)[:500])
        lines.append("")

        md_path.write_text("\n".join(lines), encoding="utf-8")
        return md_path
