"""Infra deployment analyzer.

For any opensourceways repository, automatically discovers and analyzes
deployment configurations from infra-xxx repositories using GitHub token authentication.

Flow:
1. Prompt user for GitHub token (if not provided via CLI/env)
2. Clone infra repos using the token
3. Find matching deployment configs
4. Extract K8s deployment info
"""

import json
import subprocess
import os
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# Known infra repos to search
INFRA_REPOS = [
    "infra-common",
    "infra-openeuler",
    "infra-community",
    "infra-mindspore",
    "infra-openubmc",
    "infrastructure",
]

# Default base path for cloned infra repos
DEFAULT_INFRA_BASE = Path("/tmp")


class InfraAnalyzer:
    """Analyzes infra-xxx deployment configs for a target repository."""

    def __init__(self, infra_base: Path = DEFAULT_INFRA_BASE, token: Optional[str] = None):
        self.infra_base = infra_base
        self.token = token
        self.infra_paths: Dict[str, Path] = {}

    def discover_infra_repos(self) -> Dict[str, Path]:
        """Find which infra repos exist locally."""
        for repo_name in INFRA_REPOS:
            repo_path = self.infra_base / repo_name
            if repo_path.exists() and (repo_path / ".git").exists():
                self.infra_paths[repo_name] = repo_path
        return self.infra_paths

    def _clone_with_gh(self, org: str, repo_name: str, repo_path: Path) -> bool:
        """Try to clone using gh CLI.

        Note: GITHUB_TOKEN env var may override gh's keyring auth. We unset it.
        """
        try:
            env = os.environ.copy()
            env.pop("GITHUB_TOKEN", None)
            env.pop("GH_TOKEN", None)

            subprocess.run(["gh", "--version"], capture_output=True, check=True, env=env)

            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True, text=True, timeout=10, env=env
            )
            output = result.stdout + result.stderr
            has_auth = "✓ Logged in" in output or "Logged in to" in output

            if has_auth:
                subprocess.run(
                    ["gh", "repo", "clone", f"{org}/{repo_name}", str(repo_path), "--", "--depth=1"],
                    check=True, capture_output=True, timeout=120, env=env
                )
                return True
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        return False

    def _clone_with_token(self, org: str, repo_name: str, repo_path: Path) -> bool:
        """Clone using GitHub token via HTTPS."""
        if not self.token:
            return False

        url = f"https://{self.token}@github.com/{org}/{repo_name}"
        try:
            subprocess.run(
                ["git", "clone", "--depth=1", url, str(repo_path)],
                check=True, capture_output=True, timeout=120
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            stderr = e.stderr.decode() if e.stderr else ""
            if "403" in stderr or "401" in stderr or "Authentication" in stderr:
                raise RuntimeError(
                    f"Authentication failed for {org}/{repo_name}. "
                    f"Please check your GitHub token has 'repo' scope."
                )
            raise

    def clone_infra_repos(self, org: str = "opensourceways") -> Dict[str, Path]:
        """Clone missing infra repos using gh CLI or token.

        Priority:
        1. Already exists locally → skip
        2. gh CLI with valid auth → clone via gh
        3. GitHub token → clone via HTTPS with token
        4. Neither → error
        """
        missing = [r for r in INFRA_REPOS if r not in self.infra_paths]
        if not missing:
            return self.infra_paths

        print(f"  [infra] Need to clone {len(missing)} repos: {', '.join(missing)}")

        for repo_name in missing:
            repo_path = self.infra_base / repo_name

            # Try gh CLI first
            if self._clone_with_gh(org, repo_name, repo_path):
                self.infra_paths[repo_name] = repo_path
                print(f"  [infra] ✓ {repo_name} (via gh)")
                continue

            # Try token-based clone
            if self.token:
                try:
                    self._clone_with_token(org, repo_name, repo_path)
                    self.infra_paths[repo_name] = repo_path
                    print(f"  [infra] ✓ {repo_name} (via token)")
                    continue
                except RuntimeError as e:
                    raise e
                except Exception:
                    pass  # Fall through to error

            raise RuntimeError(
                f"Cannot clone {org}/{repo_name}.\n"
                f"Either:\n"
                f"  1. Login with gh CLI: gh auth login\n"
                f"  2. Provide a GitHub token with 'repo' scope:\n"
                f"     - Set GITHUB_TOKEN environment variable\n"
                f"     - Or pass --token to repo-distiller\n"
                f"     - Or enter when prompted"
            )

        return self.infra_paths

    def analyze(self, target_repo: str, target_org: str = "opensourceways",
                clone_if_missing: bool = True) -> Dict:
        """Full analysis: discover/clone infra repos, find matching deployments, extract configs.

        Args:
            target_repo: The target repository name (e.g., "software-package-server").
            target_org: The GitHub organization (default: "opensourceways").
            clone_if_missing: If True, clone missing infra repos.
        """
        self.discover_infra_repos()

        if clone_if_missing:
            self.clone_infra_repos(target_org)

        if not self.infra_paths:
            return {
                "infra_deployments": [],
                "environments": [],
                "summary": {
                    "total_environments": 0,
                    "total_components": 0,
                    "infra_repos_found": 0,
                },
            }

        # Find matching deployment configs
        deployments = self._find_deployments(target_repo)

        # Extract configs from each deployment
        environments = []
        for dep in deployments:
            env = self._extract_environment(dep)
            if env:
                environments.append(env)

        return {
            "infra_deployments": deployments,
            "environments": environments,
            "summary": {
                "total_environments": len(environments),
                "total_components": sum(len(e.get("components", [])) for e in environments),
                "infra_repos_found": len(self.infra_paths),
                "infra_repo_names": list(self.infra_paths.keys()),
            },
        }

    def _find_deployments(self, target_repo: str) -> List[Dict]:
        """Find deployment directories matching the target repo name."""
        deployments = []
        patterns = self._generate_patterns(target_repo)

        for infra_name, infra_path in self.infra_paths.items():
            matched_paths = set()
            for pattern in patterns:
                search_dirs = [
                    infra_path / "common-applications",
                    infra_path / "applications",
                    infra_path / "communities",
                    infra_path / "infra-common",
                ]
                for search_dir in search_dirs:
                    if not search_dir.exists():
                        continue
                    for match in search_dir.rglob(f"*{pattern}*"):
                        if match.is_dir() and self._has_k8s_files(match):
                            p = str(match)
                            if p not in matched_paths:
                                matched_paths.add(p)
                                dep = {
                                    "infra_repo": infra_name,
                                    "path": str(match.relative_to(self.infra_base)),
                                    "directory": match.name,
                                    "environment": self._infer_environment(infra_name, str(match)),
                                    "match_pattern": pattern,
                                }
                                deployments.append(dep)

        # Filter if too many matches
        if len(deployments) > 20:
            exact_name = target_repo.replace(".git", "")
            filtered = []
            for dep in deployments:
                d = dep["directory"].lower()
                n = exact_name.lower()
                if n in d or d.startswith(n[:10]):
                    filtered.append(dep)
            if filtered:
                deployments = filtered

        return deployments

    def _generate_patterns(self, target_repo: str) -> List[str]:
        """Generate search patterns, prioritized."""
        patterns = []
        seen = set()

        def add(p):
            if p and p not in seen and len(p) > 2:
                patterns.append(p)
                seen.add(p)

        name = target_repo.replace(".git", "")
        add(name)

        for prefix in ["openeuler-", "infra-", "mindspore-"]:
            if name.startswith(prefix):
                add(name[len(prefix):])

        add(name.replace("-", "_"))

        for sep in ["-", "_"]:
            if sep in name:
                parts = name.split(sep)
                for part in parts:
                    if len(part) > 5:
                        add(part)

        return patterns

    def _has_k8s_files(self, directory: Path) -> bool:
        """Check if a directory contains Kubernetes deployment files."""
        k8s_files = ["deployment.yaml", "kustomization.yaml", "configmap.yaml"]
        for f in k8s_files:
            if (directory / f).exists():
                return True
        for f in directory.rglob("deployment.yaml"):
            return True
        for f in directory.rglob("*-deployment.yaml"):
            return True
        return False

    def _infer_environment(self, infra_name: str, path: str) -> str:
        """Infer the environment type."""
        path_lower = path.lower()
        if "test" in path_lower or "test-environment" in infra_name:
            return "test"
        elif "prod" in path_lower or "production" in path_lower:
            return "production"
        elif "staging" in path_lower:
            return "staging"
        elif infra_name == "infra-common":
            return "test"
        else:
            return "production"

    def _extract_environment(self, deployment: Dict) -> Optional[Dict]:
        """Extract full environment configuration."""
        dep_path = self.infra_base / deployment["path"]
        if not dep_path.exists():
            return None

        env = {
            "infra_repo": deployment["infra_repo"],
            "environment": deployment["environment"],
            "path": deployment["path"],
            "components": [],
        }

        components = []
        self._extract_component(dep_path, components, deployment["environment"])

        for subdir in dep_path.iterdir():
            if subdir.is_dir():
                self._extract_component(subdir, components, deployment["environment"])

        env["components"] = components
        return env

    def _extract_component(self, component_dir: Path, components: List, env_type: str):
        """Extract configuration from a single component directory."""
        component = {
            "name": component_dir.name,
            "path": str(component_dir),
            "deployments": [],
            "configmaps": [],
            "services": [],
            "ingresses": [],
            "kustomization": None,
        }

        dep_file = component_dir / "deployment.yaml"
        if dep_file.exists():
            parsed = self._parse_k8s_deployment(dep_file)
            if parsed:
                component["deployments"].append(parsed)

        for f in component_dir.glob("*-deployment.yaml"):
            parsed = self._parse_k8s_deployment(f)
            if parsed:
                component["deployments"].append(parsed)

        cm_file = component_dir / "configmap.yaml"
        if cm_file.exists():
            parsed = self._parse_k8s_configmap(cm_file)
            if parsed:
                component["configmaps"].append(parsed)

        svc_file = component_dir / "service.yaml"
        if svc_file.exists():
            parsed = self._parse_k8s_service(svc_file)
            if parsed:
                component["services"].append(parsed)

        ing_file = component_dir / "ingress.yaml"
        if ing_file.exists():
            parsed = self._parse_k8s_ingress(ing_file)
            if parsed:
                component["ingresses"].append(parsed)

        kust_file = component_dir / "kustomization.yaml"
        if kust_file.exists():
            parsed = self._parse_kustomization(kust_file)
            if parsed:
                component["kustomization"] = parsed

        if component["deployments"] or component["configmaps"]:
            components.append(component)

    def _parse_k8s_deployment(self, path: Path) -> Optional[Dict]:
        """Parse a Kubernetes Deployment YAML (supports multi-document)."""
        if not HAS_YAML:
            return None
        try:
            content = path.read_text()
            docs = list(yaml.safe_load_all(content))
            for data in docs:
                if not isinstance(data, dict):
                    continue
                if data.get("kind") != "Deployment":
                    continue

                spec = data.get("spec", {})
                template = spec.get("template", {})
                template_spec = template.get("spec", {})
                containers = template_spec.get("containers", [])

                result = {
                    "name": data.get("metadata", {}).get("name", ""),
                    "namespace": data.get("metadata", {}).get("namespace", ""),
                    "image": "",
                    "args": [],
                    "env": [],
                    "resources": {},
                    "strategy": spec.get("strategy", {}),
                    "replicas": spec.get("replicas"),
                    "liveness_probe": None,
                    "readiness_probe": None,
                    "volumes": [],
                    "file": str(path),
                }

                if containers:
                    c = containers[0]
                    result["image"] = c.get("image", "")
                    result["args"] = c.get("args", [])
                    result["resources"] = c.get("resources", {})
                    result["liveness_probe"] = c.get("livenessProbe")
                    result["readiness_probe"] = c.get("readinessProbe")

                    for env_var in c.get("env", []):
                        env_info = {"name": env_var.get("name", "")}
                        if "value" in env_var:
                            env_info["value"] = env_var["value"]
                        if "valueFrom" in env_var:
                            vf = env_var["valueFrom"]
                            if "secretKeyRef" in vf:
                                env_info["type"] = "secret"
                                env_info["secret"] = vf["secretKeyRef"].get("name", "")
                                env_info["key"] = vf["secretKeyRef"].get("key", "")
                            elif "configMapKeyRef" in vf:
                                env_info["type"] = "configmap"
                                env_info["configmap"] = vf["configMapKeyRef"].get("name", "")
                                env_info["key"] = vf["configMapKeyRef"].get("key", "")
                        result["env"].append(env_info)

                    for vm in c.get("volumeMounts", []):
                        result["volumes"].append({
                            "name": vm.get("name", ""),
                            "mount_path": vm.get("mountPath", ""),
                            "sub_path": vm.get("subPath", ""),
                        })

                return result
            return None
        except Exception:
            return None

    def _parse_k8s_configmap(self, path: Path) -> Optional[Dict]:
        """Parse a Kubernetes ConfigMap YAML (supports multi-document)."""
        if not HAS_YAML:
            return None
        try:
            content = path.read_text()
            docs = list(yaml.safe_load_all(content))
            for data in docs:
                if not isinstance(data, dict):
                    continue
                if data.get("kind") != "ConfigMap":
                    continue

                result = {
                    "name": data.get("metadata", {}).get("name", ""),
                    "namespace": data.get("metadata", {}).get("namespace", ""),
                    "data": {},
                    "file": str(path),
                }

                raw_data = data.get("data", {})
                for key, value in raw_data.items():
                    if isinstance(value, str):
                        if key.endswith(".yaml") or key.endswith(".yml"):
                            try:
                                parsed = yaml.safe_load(value)
                                result["data"][key] = parsed if isinstance(parsed, dict) else value
                            except Exception:
                                result["data"][key] = value
                        else:
                            result["data"][key] = value

                return result
            return None
        except Exception:
            return None

    def _parse_k8s_service(self, path: Path) -> Optional[Dict]:
        """Parse a Kubernetes Service YAML."""
        if not HAS_YAML:
            return None
        try:
            content = path.read_text()
            docs = list(yaml.safe_load_all(content))
            for data in docs:
                if not isinstance(data, dict):
                    continue
                if data.get("kind") != "Service":
                    continue
                spec = data.get("spec", {})
                return {
                    "name": data.get("metadata", {}).get("name", ""),
                    "type": spec.get("type", "ClusterIP"),
                    "ports": spec.get("ports", []),
                    "file": str(path),
                }
            return None
        except Exception:
            return None

    def _parse_k8s_ingress(self, path: Path) -> Optional[Dict]:
        """Parse a Kubernetes Ingress YAML."""
        if not HAS_YAML:
            return None
        try:
            content = path.read_text()
            docs = list(yaml.safe_load_all(content))
            for data in docs:
                if not isinstance(data, dict):
                    continue
                if data.get("kind") != "Ingress":
                    continue
                spec = data.get("spec", {})
                rules = spec.get("rules", [])
                hosts = []
                paths = []
                for rule in rules:
                    host = rule.get("host", "")
                    if host:
                        hosts.append(host)
                    for p in rule.get("http", {}).get("paths", []):
                        paths.append({
                            "path": p.get("path", ""),
                            "path_type": p.get("pathType", ""),
                        })
                return {
                    "name": data.get("metadata", {}).get("name", ""),
                    "hosts": hosts,
                    "paths": paths,
                    "file": str(path),
                }
            return None
        except Exception:
            return None

    def _parse_kustomization(self, path: Path) -> Optional[Dict]:
        """Parse a Kustomization YAML."""
        if not HAS_YAML:
            return None
        try:
            data = yaml.safe_load(path.read_text())
            if not isinstance(data, dict):
                return None
            return {
                "resources": data.get("resources", []),
                "namespace": data.get("namespace", ""),
                "name_prefix": data.get("namePrefix", ""),
                "file": str(path),
            }
        except Exception:
            return None
