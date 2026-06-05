"""Deployment topology analyzer.

Extracts deployment information from:
- Dockerfiles (base image, build steps, exposed ports, health checks)
- Main entry points (server ports, config file paths)
- Environment variables and command-line flags
- CI/CD workflow files
"""

import re
from pathlib import Path
from typing import Dict, List, Any, Optional


class DeployParser:
    """Analyzes deployment topology from Dockerfiles and entry points."""

    def analyze(self, repo_path: Path) -> Dict:
        """Run full deployment analysis."""
        return {
            "dockerfiles": self._parse_dockerfiles(repo_path),
            "entry_points": self._find_entry_points(repo_path),
            "ci_workflows": self._parse_ci_workflows(repo_path),
            "topology": {},
            "summary": {
                "total_services": 0,
                "total_ports": 0,
                "has_healthcheck": False,
            },
        }

    def _parse_dockerfiles(self, repo_path: Path) -> List[Dict]:
        """Parse all Dockerfiles in the repository."""
        dockerfiles = []
        for f in repo_path.rglob("Dockerfile"):
            parsed = self._parse_single_dockerfile(f)
            if parsed:
                rel_path = str(f.relative_to(repo_path))
                parsed["path"] = rel_path
                dockerfiles.append(parsed)
        return dockerfiles

    def _parse_single_dockerfile(self, path: Path) -> Optional[Dict]:
        """Parse a single Dockerfile."""
        try:
            content = path.read_text()
        except Exception:
            return None

        result: Dict[str, Any] = {
            "base_image": "",
            "build_stages": [],
            "exposed_ports": [],
            "env_vars": [],
            "entrypoint": "",
            "cmd": "",
            "healthcheck": None,
            "workdir": "",
            "copy_sources": [],
            "run_commands": [],
            "labels": {},
            "multi_stage": False,
            "build_args": [],
        }

        lines = content.split('\n')
        current_stage = 0
        in_multiline = False
        multiline_buf = ""

        for line in lines:
            stripped = line.strip()

            # Skip comments and empty lines
            if not stripped or stripped.startswith('#'):
                continue

            # Handle line continuations
            if in_multiline:
                multiline_buf += " " + stripped.rstrip('\\')
                if not stripped.endswith('\\'):
                    in_multiline = False
                    stripped = multiline_buf
                    multiline_buf = ""
                else:
                    continue
            elif stripped.endswith('\\'):
                in_multiline = True
                multiline_buf = stripped.rstrip('\\')
                continue

            # Parse directives
            if stripped.upper().startswith("FROM "):
                parts = stripped.split()
                if len(parts) >= 2:
                    image = parts[1]
                    if current_stage == 0 and not result["base_image"]:
                        result["base_image"] = image
                    result["build_stages"].append({
                        "stage": current_stage,
                        "image": image,
                        "alias": parts[3] if len(parts) > 3 and parts[2].upper() == "AS" else "",
                    })
                    current_stage += 1
                    if current_stage > 1:
                        result["multi_stage"] = True

            elif stripped.upper().startswith("EXPOSE "):
                ports = stripped.split()[1:]
                for port in ports:
                    result["exposed_ports"].append(port)

            elif stripped.upper().startswith("ENV "):
                # ENV KEY=VALUE or ENV KEY VALUE
                env_part = stripped[4:].strip()
                if '=' in env_part:
                    key, _, value = env_part.partition('=')
                    result["env_vars"].append({"key": key.strip(), "value": value.strip()})
                else:
                    parts = env_part.split(None, 1)
                    if parts:
                        result["env_vars"].append({"key": parts[0], "value": parts[1] if len(parts) > 1 else ""})

            elif stripped.upper().startswith("ENTRYPOINT "):
                result["entrypoint"] = stripped[11:].strip()

            elif stripped.upper().startswith("CMD "):
                result["cmd"] = stripped[4:].strip()

            elif stripped.upper().startswith("HEALTHCHECK "):
                hc_content = stripped[12:].strip()
                if hc_content.upper() == "NONE":
                    result["healthcheck"] = {"disabled": True}
                else:
                    result["healthcheck"] = {
                        "disabled": False,
                        "command": hc_content,
                    }

            elif stripped.upper().startswith("WORKDIR "):
                result["workdir"] = stripped[8:].strip()

            elif stripped.upper().startswith("COPY "):
                parts = stripped.split()
                if len(parts) >= 3:
                    result["copy_sources"].append({
                        "src": parts[1],
                        "dest": parts[-1],
                    })

            elif stripped.upper().startswith("RUN "):
                result["run_commands"].append(stripped[4:].strip())

            elif stripped.upper().startswith("ARG "):
                arg_part = stripped[4:].strip()
                result["build_args"].append(arg_part)

            elif stripped.upper().startswith("LABEL "):
                label_part = stripped[6:].strip()
                if '=' in label_part:
                    key, _, value = label_part.partition('=')
                    result["labels"][key.strip()] = value.strip()

        return result

    def _find_entry_points(self, repo_path: Path) -> List[Dict]:
        """Find main entry points and their configurations."""
        entry_points = []

        # Find main.go files
        for main_file in repo_path.rglob("main.go"):
            # Skip vendor, test directories
            rel = str(main_file.relative_to(repo_path))
            if "vendor" in rel:
                continue

            parsed = self._parse_main_go(main_file, repo_path)
            if parsed:
                entry_points.append(parsed)

        return entry_points

    def _parse_main_go(self, path: Path, repo_path: Path) -> Optional[Dict]:
        """Parse a main.go file for server configuration."""
        try:
            content = path.read_text()
        except Exception:
            return None

        result: Dict[str, Any] = {
            "path": str(path.relative_to(repo_path)),
            "service_name": path.parent.name if path.parent.name != "." else "main",
            "flags": [],
            "config_file": "",
            "ports": [],
            "databases": [],
            "external_services": [],
        }

        # Extract command-line flags
        for m in re.finditer(r'flag\.String\(\s*"([^"]+)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"', content):
            result["flags"].append({
                "name": m.group(1),
                "default": m.group(2),
                "usage": m.group(3),
            })

        for m in re.finditer(r'flag\.Int\(\s*"([^"]+)"\s*,\s*(\d+)\s*,\s*"([^"]*)"', content):
            result["flags"].append({
                "name": m.group(1),
                "default": int(m.group(2)),
                "usage": m.group(3),
            })

        # Extract config file path from flags
        for flag in result["flags"]:
            if "config" in flag.get("name", "").lower():
                result["config_file"] = flag.get("default", "")

        # Extract port configurations
        for m in re.finditer(r':(\d{2,5})|ListenAndServe[^:]*:(\d{2,5})|Port["\s:=]+(\d{2,5})', content):
            port = m.group(1) or m.group(2) or m.group(3)
            if port and port not in result["ports"]:
                result["ports"].append(port)

        # Extract database connections
        if "mongo" in content.lower():
            result["databases"].append("mongodb")
        if "postgres" in content.lower() or "gorm" in content.lower():
            result["databases"].append("postgresql")
        if "mysql" in content.lower():
            result["databases"].append("mysql")
        if "redis" in content.lower():
            result["databases"].append("redis")

        # Extract external service references
        if "kafka" in content.lower():
            result["external_services"].append("kafka")
        if "gitee" in content.lower():
            result["external_services"].append("gitee")
        if "gitcode" in content.lower():
            result["external_services"].append("gitcode")
        if "huaweicloud" in content.lower():
            result["external_services"].append("huaweicloud")
        if "smtp" in content.lower() or "gomail" in content.lower():
            result["external_services"].append("smtp")

        return result

    def _parse_ci_workflows(self, repo_path: Path) -> List[Dict]:
        """Parse GitHub Actions workflow files."""
        workflows = []
        import yaml

        for wf_file in (repo_path / ".github" / "workflows").rglob("*.yml"):
            try:
                data = yaml.safe_load(wf_file.read_text())
                if isinstance(data, dict):
                    workflows.append({
                        "name": data.get("name", wf_file.stem),
                        "path": str(wf_file.relative_to(repo_path)),
                        "triggers": list(data.get("on", {}).keys()) if isinstance(data.get("on"), dict) else [],
                        "jobs": list(data.get("jobs", {}).keys()),
                        "job_count": len(data.get("jobs", {})),
                    })
            except Exception:
                pass

        return workflows

    def _build_topology(self, dockerfiles: List[Dict], entry_points: List[Dict]) -> Dict:
        """Build deployment topology from parsed data."""
        services = []

        for ep in entry_points:
            service = {
                "name": ep["service_name"],
                "entry_point": ep["path"],
                "ports": ep.get("ports", []),
                "databases": ep.get("databases", []),
                "external_services": ep.get("external_services", []),
                "has_dockerfile": False,
                "has_healthcheck": False,
            }

            # Match with Dockerfile
            for df in dockerfiles:
                df_dir = str(Path(df["path"]).parent)
                ep_dir = str(Path(ep["path"]).parent)
                if df_dir == ep_dir or (df_dir == "." and ep_dir == "."):
                    service["has_dockerfile"] = True
                    service["has_healthcheck"] = df.get("healthcheck") is not None and df.get("healthcheck", {}).get("disabled", False) is False
                    service["dockerfile_path"] = df["path"]
                    service["base_image"] = df.get("base_image", "")
                    service["exposed_ports"] = df.get("exposed_ports", [])
                    break

            services.append(service)

        return {
            "services": services,
            "total_services": len(services),
        }
