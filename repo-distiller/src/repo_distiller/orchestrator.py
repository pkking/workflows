import json
import subprocess
from pathlib import Path
from typing import Dict

from rich.console import Console

console = Console()

ROLES = {
    "pm": (
        "You are a Project Manager. Analyze the provided AST (features), Git history (decisions/bugs), "
        "and IaC (deployment context). Identify the main user problems this system solves. "
        "List the Feature List prioritized by user value. Highlight any contradictions between the code "
        "and the deployment config. Focus on User Experience consistency."
    ),
    "architect": (
        "You are a Software Architect. Review the code structure (AST) and infrastructure (IaC). "
        "Assess technical feasibility of the identified features. Check if the tech stack and directory "
        "structure align with standard team conventions. Identify architectural risks like circular "
        "dependencies or tight coupling (from Git co-change analysis)."
    ),
    "dfx": (
        "You are a DFX Engineer (Reliability, Maintainability, Observability). Challenge the proposals. "
        "Look for Single Points of Failure (SPOF) in the IaC. Check if the code has adequate logging/"
        "error handling (inferred from AST/imports). Is the system observable? Are there maintainability "
        "issues like high churn files (from Git analysis)?"
    ),
    "ux": (
        "You are a UX Engineer. Focus on the best user experience. Check for UI consistency patterns "
        "in the AST (e.g., component reuse). Challenge any proposal that degrades performance or breaks "
        "design consistency. Look for hardcoded values or lack of accessibility features."
    ),
    "security": (
        "You are a Security Engineer. Focus on compliance, data privacy, and vulnerability. "
        "Check for exposed secrets in IaC values. Analyze API endpoints (from AST) for proper auth patterns. "
        "Challenge any proposal that introduces security risks."
    ),
    "integrator": (
        "You are the Integrator. Review all proposals and critiques. Your goal is to reach a consensus. "
        "Resolve conflicts between roles (e.g., PM wants speed, Security wants safety). Produce a final "
        "'Consensus Report' that lists: 1. Agreed Features, 2. Technical Decisions, 3. Risk Mitigations, "
        "4. Action Items."
    ),
}


class Orchestrator:

    def __init__(self, context_file: Path, output_dir: Path):
        self.context_file = context_file
        self.output_dir = output_dir

    def run(self):
        context_data = json.loads(self.context_file.read_text())
        
        console.print("[bold blue]Phase 1: Proponents (PM & Architect)[/bold blue]")
        pm_result = self._invoke_agent("pm", context_data)
        arch_result = self._invoke_agent("architect", context_data)

        console.print("[bold blue]Phase 2: Challengers (DFX, UX, Security)[/bold blue]")
        dfx_result = self._invoke_agent("dfx", context_data, pm_result, arch_result)
        ux_result = self._invoke_agent("ux", context_data, pm_result, arch_result)
        sec_result = self._invoke_agent("security", context_data, pm_result, arch_result)

        console.print("[bold blue]Phase 3: Integrator (Consensus)[/bold blue]")
        final_result = self._invoke_agent(
            "integrator", 
            context_data, 
            pm_result, 
            arch_result, 
            dfx_result, 
            ux_result, 
            sec_result
        )
        
        console.print("[bold green]Final report generated: final_report.md[/bold green]")

    def _invoke_agent(self, role: str, context: Dict, *previous_outputs: str) -> str:
        output_file = self.output_dir / f"{role}_output.md"
        
        prompt = self._build_prompt(role, context, previous_outputs)
        
        cmd = ["pi", "--prompt", prompt, "--output", str(output_file)]
        
        console.print(f"Running {role} agent...")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return output_file.read_text()
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Agent {role} failed: {e.stderr}[/red]")
            return ""

    def _build_prompt(self, role: str, context: Dict, previous_outputs: tuple) -> str:
        base_instruction = ROLES[role]
        context_str = json.dumps(context, indent=2, default=str)
        
        prompt = f"{base_instruction}\n\n### Context Data\n```json\n{context_str}\n```\n"
        
        if previous_outputs:
            prompt += "\n### Previous Outputs\n"
            for i, output in enumerate(previous_outputs):
                prompt += f"\n--- Output {i+1} ---\n{output}\n"
                
        prompt += "\n\nPlease generate your analysis based on the context and previous outputs."
        return prompt
