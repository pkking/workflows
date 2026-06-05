"""State machine analyzer.

Extracts state machines from Go code by analyzing:
- State/phase constant definitions
- State-checking methods (IsXxx(), IsValid(), etc.)
- State transition functions (methods that change state fields)
- Guard conditions (checks before transitions)
"""

import re
from pathlib import Path
from typing import Dict, List, Any, Optional


class StateMachineAnalyzer:
    """Detects and extracts state machines from code."""

    # Patterns for state-checking methods
    STATE_CHECK_PATTERNS = [
        re.compile(r'func\s+\([^)]+\)\s+Is(\w+)\s*\('),
        re.compile(r'func\s+\([^)]+\)\s+Can(\w+)\s*\('),
        re.compile(r'func\s+\([^)]+\)\s+Has(\w+)\s*\('),
    ]

    # Patterns for state transitions (methods that assign to state fields)
    TRANSITION_PATTERNS = [
        re.compile(r'(entity|pkg|self|s|\.|this)\.?(\w+)\s*=\s*.*Phase'),
        re.compile(r'\.Phase\s*=\s*(\w+)'),
        re.compile(r'\.State\s*=\s*(\w+)'),
        re.compile(r'\.Status\s*=\s*(\w+)'),
    ]

    # Patterns for state constant definitions
    STATE_CONST_PATTERNS = [
        re.compile(r'(?:const|var)\s+(\w+Phase\w*|State\w*|\w+Status\w*)'),
        re.compile(r'packagePhase\w*|State\w*|Status\w*'),
    ]

    def analyze(self, ast_data: List[Dict]) -> Dict:
        """Run full state machine analysis."""
        return {
            "state_machines": self._detect_state_machines(ast_data),
            "summary": {
                "total_machines": 0,
                "total_states": 0,
                "total_transitions": 0,
            },
        }

    def _detect_state_machines(self, ast_data: List[Dict]) -> List[Dict]:
        """Detect state machines from constants and transition methods."""
        machines: Dict[str, Dict] = {}

        # Phase 1: Collect state constants
        for f in ast_data:
            for const in f.get("constants", []):
                name = const.get("name", "")
                value = const.get("value", "")

                # Match patterns like PackagePhaseReviewing, StateClosed, etc.
                m = re.match(r'(\w+)(Phase|State|Status)(\w+)', name)
                if m:
                    entity = m.group(1).lower() if m.group(1) else "unknown"
                    machine_key = f"{m.group(1)}{m.group(2)}"
                    if machine_key not in machines:
                        machines[machine_key] = {
                            "name": machine_key,
                            "entity": m.group(1),
                            "type": m.group(2),
                            "states": [],
                            "transitions": [],
                            "guards": [],
                            "source_file": f.get("path", ""),
                        }
                    machines[machine_key]["states"].append({
                        "name": name,
                        "value": value,
                        "line": const.get("line", 0),
                        "file": f.get("path", ""),
                    })

        # Phase 2: Collect state-checking methods from symbols
        for f in ast_data:
            for sym in f.get("symbols", []):
                if sym.get("type") != "method_declaration":
                    continue
                name = sym.get("name", "")
                receiver = sym.get("receiver", "")

                for pattern in self.STATE_CHECK_PATTERNS:
                    m = pattern.match(f"func {receiver} {name}(")
                    if m:
                        check_type = m.group(1)
                        # Find which state machine this belongs to
                        for machine_key, machine in machines.items():
                            state_names = [s["name"].lower() for s in machine["states"]]
                            if check_type.lower() in [sn.replace(machine["type"].lower(), "").replace(machine["entity"].lower(), "") for sn in state_names]:
                                machine["guards"].append({
                                    "method": name,
                                    "receiver": receiver,
                                    "file": f.get("path", ""),
                                    "line": sym.get("line", 0),
                                })
                            break

        # Phase 3: Analyze state transitions from function content
        # (This requires source-level analysis, so we use heuristics from symbols)
        for f in ast_data:
            for sym in f.get("symbols", []):
                if sym.get("type") not in ("method_declaration", "function_declaration"):
                    continue
                name = sym.get("name", "")

                # Methods that likely perform state transitions
                transition_keywords = ["Close", "Approve", "Reject", "Start", "Complete",
                                       "Transition", "Handle", "Update", "Review"]
                for kw in transition_keywords:
                    if kw.lower() in name.lower():
                        # This method might contain state transitions
                        for machine_key, machine in machines.items():
                            if machine["source_file"] == f.get("path", "") or \
                               machine["entity"].lower() in f.get("path", "").lower():
                                machine["transitions"].append({
                                    "method": name,
                                    "file": f.get("path", ""),
                                    "line": sym.get("line", 0),
                                    "receiver": sym.get("receiver", ""),
                                })
                                break

        # Build result list
        result = []
        for machine_key, machine in machines.items():
            if not machine["states"]:
                continue

            # Deduplicate states
            seen_states = set()
            unique_states = []
            for s in machine["states"]:
                if s["name"] not in seen_states:
                    seen_states.add(s["name"])
                    unique_states.append(s)
            machine["states"] = unique_states

            # Deduplicate transitions
            seen_transitions = set()
            unique_transitions = []
            for t in machine["transitions"]:
                key = (t["method"], t["file"])
                if key not in seen_transitions:
                    seen_transitions.add(key)
                    unique_transitions.append(t)
            machine["transitions"] = unique_transitions

            result.append(machine)

        return result

    def analyze_from_source(self, repo_path: Path) -> List[Dict]:
        """Deep analysis from source files (more accurate than AST-only)."""
        machines = self._scan_source_for_state_machines(repo_path)
        return machines

    def _scan_source_for_state_machines(self, repo_path: Path) -> List[Dict]:
        """Scan Go source files for state machine patterns."""
        go_files = list(repo_path.rglob("*.go"))
        # Skip vendor, test, and mock files
        go_files = [f for f in go_files if
                    "vendor" not in str(f) and
                    "_test.go" not in str(f) and
                    "_mock.go" not in str(f)]

        machines: Dict[str, Dict] = {}

        for f in go_files:
            try:
                content = f.read_text()
            except Exception:
                continue

            # Find state constants
            self._extract_state_constants(content, str(f), machines)

            # Find state-checking methods
            self._extract_state_checks(content, str(f), machines)

            # Find state transitions
            self._extract_transitions(content, str(f), machines)

        return list(machines.values())

    def _extract_state_constants(self, content: str, file_path: str, machines: Dict):
        """Extract state constant definitions."""
        # Match const blocks with phase/state/status patterns
        const_pattern = re.compile(
            r'const\s*\((.*?)\)', re.DOTALL
        )
        for m in const_pattern.finditer(content):
            block = m.group(1)
            for line in block.split('\n'):
                line = line.strip()
                if not line or line.startswith('//'):
                    continue
                # Match: Name = "value" or Name = Type("value")
                cm = re.match(r'(\w+)\s*=\s*.*?"([^"]+)"', line)
                if cm:
                    name = cm.group(1)
                    value = cm.group(2)
                    state_m = re.match(r'(\w*?)(Phase|State|Status)(\w+)', name)
                    if state_m:
                        key = f"{state_m.group(1)}{state_m.group(2)}"
                        if key not in machines:
                            machines[key] = {
                                "name": key,
                                "entity": state_m.group(1),
                                "type": state_m.group(2),
                                "states": [],
                                "transitions": [],
                                "guards": [],
                                "source_file": file_path,
                            }
                        machines[key]["states"].append({
                            "name": name,
                            "value": value,
                            "file": file_path,
                        })

    def _extract_state_checks(self, content: str, file_path: str, machines: Dict):
        """Extract state-checking methods."""
        for m in re.finditer(
            r'func\s+\([^)]+\)\s+(Is\w+)\s*\(\s*\)\s*(bool)?\s*\{',
            content
        ):
            method_name = m.group(1)
            line_num = content[:m.start()].count('\n') + 1

            # Find the state this checks for
            for key, machine in machines.items():
                for state in machine["states"]:
                    state_name = state["name"]
                    # IsReviewing checks for PackagePhaseReviewing
                    if state_name.lower().replace(machine["entity"].lower(), "").replace(machine["type"].lower(), "") == method_name[2:].lower():
                        machine["guards"].append({
                            "method": method_name,
                            "file": file_path,
                            "line": line_num,
                        })

    def _extract_transitions(self, content: str, file_path: str, machines: Dict):
        """Extract state transitions from method bodies."""
        for m in re.finditer(r'func\s+\([^)]+\)\s+(\w+)\s*\([^)]*\)\s*(error)?\s*\{', content):
            method_name = m.group(1)
            start = m.end()

            # Find the method body (simplified: look for next func or end of file)
            next_func = re.search(r'\nfunc\s+', content[start:])
            if next_func:
                body = content[start:start + next_func.start()]
            else:
                body = content[start:]

            # Look for state assignments: .Phase = xxx
            for assign_m in re.finditer(r'\.Phase\s*=\s*(\w+)', body):
                target_state = assign_m.group(1)
                line_num = content[:start + assign_m.start()].count('\n') + 1

                # Find which machine this belongs to
                for key, machine in machines.items():
                    state_names = [s["name"] for s in machine["states"]]
                    if target_state in state_names:
                        machine["transitions"].append({
                            "method": method_name,
                            "target_state": target_state,
                            "file": file_path,
                            "line": line_num,
                        })
                        break
