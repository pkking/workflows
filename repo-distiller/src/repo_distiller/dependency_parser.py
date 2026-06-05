"""Parse dependency manifests: go.mod, package.json, requirements.txt, pyproject.toml.

Extracts direct dependencies, versions, known external services, and version conflicts.
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# Known external service libraries mapped to service names
KNOWN_SERVICE_LIBS = {
    # Databases
    "go.mongodb.org/mongo-driver": "mongodb",
    "gorm.io/driver/postgres": "postgresql",
    "gorm.io/driver/mysql": "mysql",
    "gorm.io/driver/sqlite": "sqlite",
    "gorm.io/gorm": "gorm",
    "github.com/lib/pq": "postgresql",
    "github.com/go-sql-driver/mysql": "mysql",
    "github.com/mattn/go-sqlite3": "sqlite",
    "psycopg2": "postgresql",
    "mysql-connector-python": "mysql",
    "sqlite3": "sqlite",
    "redis": "redis",
    "github.com/redis/go-redis": "redis",
    # Message queues
    "github.com/IBM/sarama": "kafka",
    "github.com/Shopify/sarama": "kafka",
    "github.com/confluentinc/confluent-kafka-go": "kafka",
    "kafka-python": "kafka",
    "confluent-kafka": "kafka",
    "pika": "rabbitmq",
    "celery": "rabbitmq/redis",
    # Cloud SDKs
    "github.com/aws/aws-sdk-go": "aws",
    "boto3": "aws",
    "github.com/Azure/azure-sdk-for-go": "azure",
    "github.com/googleapis/google-cloud-go": "gcp",
    "google-cloud-storage": "gcp",
    "huaweicloud-sdk-go-v3": "huaweicloud",
    # Auth
    "github.com/golang-jwt/jwt": "jwt",
    "github.com/dgrijalva/jwt-go": "jwt",
    "github.com/coreos/go-oidc": "oidc",
    "PyJWT": "jwt",
    # HTTP clients
    "github.com/go-resty/resty": "http-client",
    "requests": "http-client",
    "httpx": "http-client",
    "aiohttp": "http-client",
    # Web frameworks
    "github.com/gin-gonic/gin": "gin",
    "github.com/gorilla/mux": "gorilla-mux",
    "github.com/labstack/echo": "echo",
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "express": "express",
    # Testing
    "github.com/stretchr/testify": "testify",
    "pytest": "pytest",
    "jest": "jest",
    # Logging
    "github.com/sirupsen/logrus": "logrus",
    "go.uber.org/zap": "zap",
    "loguru": "loguru",
    # Serialization
    "github.com/json-iterator/go": "json-iterator",
    "github.com/goccy/go-json": "go-json",
    # Misc
    "github.com/google/uuid": "uuid",
    "github.com/robfig/cron": "cron",
}

# Well-known internal/common library patterns (likely org-specific, not external services)
INTERNAL_LIB_PATTERNS = [
    r"^github\.com/[\w-]+/server-common-lib",
    r"^github\.com/[\w-]+/robot-.*-lib",
    r"^github\.com/[\w-]+/mongodb-lib",
    r"^github\.com/[\w-]+/kafka-lib",
]


class DependencyParser:
    """Parses dependency manifests and identifies external services."""

    def analyze(self, repo_path: Path) -> Dict:
        result: Dict[str, Any] = {
            "go_mod": None,
            "package_json": None,
            "requirements_txt": None,
            "pyproject_toml": None,
            "external_services": [],
            "version_conflicts": [],
            "dependency_summary": {},
        }

        # go.mod
        go_mod_files = list(repo_path.rglob("go.mod"))
        # Only consider root-level go.mod files (one per binary)
        for f in go_mod_files:
            parsed = self._parse_go_mod(f)
            if parsed:
                rel = str(f.relative_to(repo_path))
                if rel not in ("go.mod",):
                    result["go_mod"] = result.get("go_mod") or {}
                    result["go_mod"][rel] = parsed
                else:
                    result["go_mod"] = parsed

        # package.json
        pkg_json_files = list(repo_path.rglob("package.json"))
        for f in pkg_json_files:
            parsed = self._parse_package_json(f)
            if parsed:
                rel = str(f.relative_to(repo_path))
                if rel == "package.json":
                    result["package_json"] = parsed
                else:
                    result["package_json"] = result.get("package_json") or {}
                    result["package_json"][rel] = parsed

        # requirements.txt
        req_files = list(repo_path.rglob("requirements.txt"))
        for f in req_files:
            parsed = self._parse_requirements_txt(f)
            if parsed:
                rel = str(f.relative_to(repo_path))
                if rel == "requirements.txt":
                    result["requirements_txt"] = parsed
                else:
                    result["requirements_txt"] = result.get("requirements_txt") or {}
                    result["requirements_txt"][rel] = parsed

        # pyproject.toml
        pyproject_files = list(repo_path.rglob("pyproject.toml"))
        for f in pyproject_files:
            parsed = self._parse_pyproject_toml(f)
            if parsed:
                rel = str(f.relative_to(repo_path))
                if rel == "pyproject.toml":
                    result["pyproject_toml"] = parsed
                else:
                    result["pyproject_toml"] = result.get("pyproject_toml") or {}
                    result["pyproject_toml"][rel] = parsed

        # Identify external services
        result["external_services"] = self._identify_services(result)

        # Detect version conflicts
        result["version_conflicts"] = self._detect_conflicts(result)

        # Summary
        all_deps = self._collect_all_deps(result)
        result["dependency_summary"] = {
            "total_direct": len(all_deps),
            "total_services": len(result["external_services"]),
            "total_conflicts": len(result["version_conflicts"]),
            "languages": self._detect_languages(result),
        }

        return result

    def _parse_go_mod(self, path: Path) -> Optional[Dict]:
        """Parse go.mod into direct deps, indirect deps, go version, module name."""
        try:
            content = path.read_text()
        except Exception:
            return None

        result: Dict[str, Any] = {
            "module": "",
            "go_version": "",
            "direct_deps": [],
            "indirect_deps": [],
            "replace": [],
        }

        lines = content.split('\n')
        in_require = False
        in_replace = False

        for line in lines:
            stripped = line.strip()

            # Module declaration
            m = re.match(r'^module\s+(\S+)', stripped)
            if m:
                result["module"] = m.group(1)
                continue

            # Go version
            m = re.match(r'^go\s+([\d.]+)', stripped)
            if m:
                result["go_version"] = m.group(1)
                continue

            # Replace block
            if stripped.startswith("replace ("):
                in_replace = True
                continue
            if stripped == ")" and in_replace:
                in_replace = False
                continue
            if in_replace:
                m = re.match(r'(\S+)\s+(?:=>)?\s*(\S+)', stripped)
                if m:
                    result["replace"].append({
                        "from": m.group(1),
                        "to": m.group(2) if m.group(2) != "=>" else "",
                    })
                continue

            # Single replace directive
            if stripped.startswith("replace ") and "(" not in stripped:
                m = re.match(r'replace\s+(\S+)\s+=>\s+(\S+)', stripped)
                if m:
                    result["replace"].append({"from": m.group(1), "to": m.group(2)})
                continue

            # Require block
            if stripped.startswith("require ("):
                in_require = True
                continue
            if stripped == ")" and in_require:
                in_require = False
                continue

            if in_require or stripped.startswith("require "):
                # Parse: module version // indirect
                # Go versions start with 'v': v1.10.0, v0.0.0-20231114071554-b2af9944cf3a
                m = re.match(r'(\S+)\s+(v?[\d][.\da-z-]*)', stripped)
                if m and not stripped.startswith("require"):
                    dep = {
                        "name": m.group(1),
                        "version": m.group(2),
                    }
                    if "// indirect" in stripped:
                        result["indirect_deps"].append(dep)
                    else:
                        result["direct_deps"].append(dep)

            # Single require directive
            if stripped.startswith("require ") and "(" not in stripped:
                m = re.match(r'require\s+(\S+)\s+(v?[\d][.\da-z-]*)', stripped)
                if m:
                    dep = {"name": m.group(1), "version": m.group(2)}
                    if "// indirect" in stripped:
                        result["indirect_deps"].append(dep)
                    else:
                        result["direct_deps"].append(dep)

        return result

    def _parse_package_json(self, path: Path) -> Optional[Dict]:
        """Parse package.json into dependencies."""
        try:
            data = json.loads(path.read_text())
        except Exception:
            return None

        return {
            "name": data.get("name", ""),
            "version": data.get("version", ""),
            "dependencies": data.get("dependencies", {}),
            "dev_dependencies": data.get("devDependencies", {}),
        }

    def _parse_requirements_txt(self, path: Path) -> Optional[Dict]:
        """Parse requirements.txt into dependency list."""
        try:
            content = path.read_text()
        except Exception:
            return None

        deps = []
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('-'):
                continue
            # Parse: package==version, package>=version, package~=version
            m = re.match(r'^([\w.-]+)\s*([><=~!]+)?\s*([\d.]+)?', line)
            if m:
                deps.append({
                    "name": m.group(1),
                    "operator": m.group(2) or "",
                    "version": m.group(3) or "",
                })
        return {"dependencies": deps}

    def _parse_pyproject_toml(self, path: Path) -> Optional[Dict]:
        """Parse pyproject.toml dependencies."""
        try:
            if not HAS_YAML:
                return None
            # TOML parsing is tricky without toml library; do basic extraction
            content = path.read_text()
            deps = []

            # Look for dependencies = [...] or requires = [...]
            in_deps = False
            for line in content.split('\n'):
                stripped = line.strip()
                if stripped.startswith("dependencies") and stripped.endswith("["):
                    in_deps = True
                    continue
                if stripped.startswith("requires") and stripped.endswith("["):
                    in_deps = True
                    continue
                if in_deps:
                    if stripped == "]":
                        in_deps = False
                        continue
                    m = re.match(r'"([^"]+)"', stripped)
                    if m:
                        deps.append(m.group(1))
        except Exception:
            return None

        return {"dependencies": deps} if deps else None

    def _identify_services(self, result: Dict) -> List[Dict]:
        """Identify external services from dependency names."""
        services: List[Dict] = []
        seen = set()

        def scan_deps(deps_list, source):
            for dep in deps_list:
                name = dep.get("name", "") if isinstance(dep, dict) else dep
                for pattern, service in KNOWN_SERVICE_LIBS.items():
                    if pattern in name.lower():
                        key = f"{service}:{name}"
                        if key not in seen:
                            seen.add(key)
                            services.append({
                                "service": service,
                                "library": name,
                                "version": dep.get("version", "") if isinstance(dep, dict) else "",
                                "source": source,
                            })

        # Scan go.mod
        go_mod = result.get("go_mod")
        if go_mod:
            if isinstance(go_mod, dict) and "direct_deps" in go_mod:
                scan_deps(go_mod["direct_deps"], "go.mod (root)")
                scan_deps(go_mod.get("indirect_deps", []), "go.mod (indirect)")
            elif isinstance(go_mod, dict):
                for path, mod in go_mod.items():
                    if isinstance(mod, dict):
                        scan_deps(mod.get("direct_deps", []), f"go.mod ({path})")

        # Scan package.json
        pkg = result.get("package_json")
        if pkg:
            if isinstance(pkg, dict) and "dependencies" in pkg:
                if isinstance(pkg["dependencies"], dict):
                    for name, ver in pkg["dependencies"].items():
                        scan_deps([{"name": name, "version": ver}], "package.json (deps)")
                if isinstance(pkg.get("dev_dependencies"), dict):
                    for name, ver in pkg["dev_dependencies"].items():
                        scan_deps([{"name": name, "version": ver}], "package.json (devDeps)")
            elif isinstance(pkg, dict):
                for path, mod in pkg.items():
                    if isinstance(mod, dict) and isinstance(mod.get("dependencies"), dict):
                        for name, ver in mod["dependencies"].items():
                            scan_deps([{"name": name, "version": ver}], f"package.json ({path})")

        # Scan requirements.txt
        req = result.get("requirements_txt")
        if req:
            if isinstance(req, dict) and "dependencies" in req:
                scan_deps(req["dependencies"], "requirements.txt")
            elif isinstance(req, dict):
                for path, mod in req.items():
                    if isinstance(mod, dict) and "dependencies" in mod:
                        scan_deps(mod["dependencies"], f"requirements.txt ({path})")

        return services

    def _detect_conflicts(self, result: Dict) -> List[Dict]:
        """Detect potential version conflicts (same library used at different versions)."""
        conflicts = []
        all_versions: Dict[str, List[Dict]] = {}

        def collect(dep_name, version, source):
            key = dep_name.lower()
            if key not in all_versions:
                all_versions[key] = []
            all_versions[key].append({"version": version, "source": source})

        # Collect from go.mod
        go_mod = result.get("go_mod")
        if go_mod:
            if isinstance(go_mod, dict) and "direct_deps" in go_mod:
                for d in go_mod["direct_deps"]:
                    collect(d["name"], d["version"], "go.mod direct")
                for d in go_mod.get("indirect_deps", []):
                    collect(d["name"], d["version"], "go.mod indirect")
            elif isinstance(go_mod, dict):
                for path, mod in go_mod.items():
                    if isinstance(mod, dict):
                        for d in mod.get("direct_deps", []):
                            collect(d["name"], d["version"], f"go.mod ({path})")

        # Collect from package.json
        pkg = result.get("package_json")
        if pkg:
            if isinstance(pkg, dict) and "dependencies" in pkg:
                if isinstance(pkg["dependencies"], dict):
                    for name, ver in pkg["dependencies"].items():
                        collect(name, ver, "package.json")
            elif isinstance(pkg, dict):
                for path, mod in pkg.items():
                    if isinstance(mod, dict) and isinstance(mod.get("dependencies"), dict):
                        for name, ver in mod["dependencies"].items():
                            collect(name, ver, f"package.json ({path})")

        # Find conflicts
        for name, entries in all_versions.items():
            versions = set(e["version"] for e in entries)
            if len(versions) > 1:
                conflicts.append({
                    "library": name,
                    "versions": list(versions),
                    "sources": [f"{e['source']}@{e['version']}" for e in entries],
                })

        return conflicts

    def _collect_all_deps(self, result: Dict) -> List[str]:
        """Collect all dependency names."""
        deps = []

        def add(dep_name):
            if dep_name and dep_name not in deps:
                deps.append(dep_name)

        go_mod = result.get("go_mod")
        if go_mod:
            if isinstance(go_mod, dict) and "direct_deps" in go_mod:
                for d in go_mod["direct_deps"]:
                    add(d["name"])
            elif isinstance(go_mod, dict):
                for mod in go_mod.values():
                    if isinstance(mod, dict):
                        for d in mod.get("direct_deps", []):
                            add(d["name"])

        pkg = result.get("package_json")
        if pkg:
            if isinstance(pkg, dict) and "dependencies" in pkg:
                if isinstance(pkg["dependencies"], dict):
                    for name in pkg["dependencies"]:
                        add(name)
            elif isinstance(pkg, dict):
                for mod in pkg.values():
                    if isinstance(mod, dict) and isinstance(mod.get("dependencies"), dict):
                        for name in mod["dependencies"]:
                            add(name)

        return deps

    def _detect_languages(self, result: Dict) -> List[str]:
        langs = []
        if result.get("go_mod"):
            langs.append("go")
        if result.get("package_json"):
            langs.append("typescript/javascript")
        if result.get("requirements_txt") or result.get("pyproject_toml"):
            langs.append("python")
        return langs
