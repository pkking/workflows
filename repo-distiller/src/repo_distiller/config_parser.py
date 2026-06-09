"""Parse configuration files (YAML, JSON, TOML, env) to extract external service
connections, feature flags, and key parameters.

Used to identify databases, message brokers, cloud services, and auth providers
from actual configuration values.
"""

import re
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# Patterns that indicate external service connections
CONNECTION_PATTERNS = {
    "mongodb": re.compile(r'mongo(?:db)?://', re.IGNORECASE),
    "postgresql": re.compile(r'(?:postgres(?:ql)?|psql)://', re.IGNORECASE),
    "mysql": re.compile(r'mysql://', re.IGNORECASE),
    "redis": re.compile(r'redis://', re.IGNORECASE),
    "kafka": re.compile(r'kafka://|kafka\.(?:brokers|bootstrap|servers)', re.IGNORECASE),
    "rabbitmq": re.compile(r'amqp://', re.IGNORECASE),
    "elasticsearch": re.compile(r'elastic(?:search)?://', re.IGNORECASE),
    "smtp": re.compile(r'smtp://', re.IGNORECASE),
    "http_api": re.compile(r'https?://', re.IGNORECASE),
}

# Key names that often contain service configuration
CONFIG_KEY_PATTERNS = {
    "database": re.compile(r'(?:db|database|mongo|postgres|mysql|redis)\w*', re.IGNORECASE),
    "broker": re.compile(r'(?:kafka|broker|mq|rabbit|queue|amqp)\w*', re.IGNORECASE),
    "auth": re.compile(r'(?:auth|token|secret|key|password|jwt|oauth|oidc|cla)\w*', re.IGNORECASE),
    "api_endpoint": re.compile(r'(?:endpoint|url|uri|host|addr(?:ess)?|api[_-]?url)\w*', re.IGNORECASE),
    "encryption": re.compile(r'(?:encrypt|cipher|aes|gcm|crypto)\w*', re.IGNORECASE),
    "pagination": re.compile(r'(?:page|limit|max[_-]?num|count[_-]?per[_-]?page)\w*', re.IGNORECASE),
}

# Sensitive key patterns (should never be in plaintext)
SENSITIVE_PATTERNS = {
    "password": re.compile(r'(?:password|passwd|pwd)\w*', re.IGNORECASE),
    "secret": re.compile(r'(?:secret|token|api[_-]?key|access[_-]?key)\w*', re.IGNORECASE),
    "private_key": re.compile(r'(?:private[_-]?key|priv[_-]?key)\w*', re.IGNORECASE),
}


class ConfigParser:
    """Parse configuration files to extract service connections and parameters."""

    def analyze(self, repo_path: Path) -> Dict:
        result: Dict[str, Any] = {
            "yaml_configs": [],
            "json_configs": [],
            "env_files": [],
            "service_connections": [],
            "sensitive_values": [],
            "feature_flags": [],
            "config_summary": {},
        }

        # YAML configs — skip .github, vendor, node_modules
        yaml_files = self._find_files(repo_path, ["*.yaml", "*.yml"],
                                       skip_dirs=[".git", "vendor", "node_modules", ".github"])
        for f in yaml_files:
            parsed = self._parse_yaml(f)
            if parsed:
                entry = {"path": str(f.relative_to(repo_path)), "data": parsed}
                result["yaml_configs"].append(entry)

        # JSON configs
        json_files = self._find_files(repo_path, ["*.json"],
                                       skip_dirs=[".git", "vendor", "node_modules", ".github"])
        for f in json_files:
            parsed = self._parse_json(f)
            if parsed:
                entry = {"path": str(f.relative_to(repo_path)), "data": parsed}
                result["json_configs"].append(entry)

        # .env files
        env_files = self._find_files(repo_path, [".env", ".env.*"],
                                      skip_dirs=[".git", "vendor", "node_modules"])
        for f in env_files:
            parsed = self._parse_env(f)
            if parsed:
                entry = {"path": str(f.relative_to(repo_path)), "data": parsed}
                result["env_files"].append(entry)

        # Extract service connections
        result["service_connections"] = self._extract_connections(result)

        # Detect sensitive values
        result["sensitive_values"] = self._detect_sensitive(result)

        # Extract feature flags and key parameters
        result["feature_flags"] = self._extract_flags(result)

        # Summary
        result["config_summary"] = {
            "total_yaml": len(result["yaml_configs"]),
            "total_json": len(result["json_configs"]),
            "total_env": len(result["env_files"]),
            "services_found": len(result["service_connections"]),
            "sensitive_found": len(result["sensitive_values"]),
        }

        return result

    def _find_files(self, repo_path: Path, patterns: List[str],
                    skip_dirs: List[str]) -> List[Path]:
        """Find files matching patterns, skipping certain directories."""
        found = []
        for pattern in patterns:
            for f in repo_path.rglob(pattern):
                if f.is_file():
                    # Check if any skip dir is in the path
                    skip = False
                    rel = f.relative_to(repo_path)
                    for sd in skip_dirs:
                        if sd in rel.parts:
                            skip = True
                            break
                    if not skip:
                        found.append(f)
        return found

    def _parse_yaml(self, path: Path) -> Optional[Dict]:
        """Parse a YAML file into a dict."""
        if not HAS_YAML:
            return None
        try:
            data = yaml.safe_load(path.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return None

    def _parse_json(self, path: Path) -> Optional[Dict]:
        """Parse a JSON file into a dict."""
        try:
            import json
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return None

    def _parse_env(self, path: Path) -> Optional[Dict]:
        """Parse a .env file into a dict."""
        try:
            result = {}
            for line in path.read_text().split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    result[key] = value
            return result
        except Exception:
            return None

    def _extract_connections(self, result: Dict) -> List[Dict]:
        """Extract service connection strings from config data."""
        connections: List[Dict] = []

        def scan(obj: Any, path: str = ""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    new_path = f"{path}.{key}" if path else key
                    if isinstance(value, str):
                        self._check_connection(value, key, new_path, connections)
                    elif isinstance(value, dict):
                        scan(value, new_path)
                    elif isinstance(value, list):
                        for i, item in enumerate(value):
                            if isinstance(item, str):
                                self._check_connection(item, key, f"{new_path}[{i}]", connections)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    if isinstance(item, str):
                        self._check_connection(item, "", f"{path}[{i}]", connections)
                    elif isinstance(item, (dict, list)):
                        scan(item, f"{path}[{i}]")

        for entry in result.get("yaml_configs", []):
            scan(entry.get("data", {}), entry.get("path", ""))
        for entry in result.get("json_configs", []):
            scan(entry.get("data", {}), entry.get("path", ""))
        for entry in result.get("env_files", []):
            scan(entry.get("data", {}), entry.get("path", ""))

        return connections

    def _check_connection(self, value: str, key: str, path: str,
                          connections: List[Dict]):
        """Check if a string value looks like a service connection."""
        for service, pattern in CONNECTION_PATTERNS.items():
            if pattern.search(value):
                connections.append({
                    "service": service,
                    "value_masked": self._mask_sensitive(value),
                    "config_path": path,
                    "key": key,
                })
                return  # Only match first pattern

    def _detect_sensitive(self, result: Dict) -> List[Dict]:
        """Detect potentially sensitive values in configs."""
        sensitive: List[Dict] = []

        def scan(obj: Any, path: str = ""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    new_path = f"{path}.{key}" if path else key
                    # Check if key name suggests sensitivity
                    if isinstance(key, str):
                        for sens_type, pattern in SENSITIVE_PATTERNS.items():
                            if pattern.match(key):
                                if isinstance(value, str) and len(value) > 0:
                                    # Check if it's a placeholder (not actual secret)
                                    if not self._is_placeholder(value):
                                        sensitive.append({
                                            "type": sens_type,
                                            "key": key,
                                            "config_path": new_path,
                                            "is_plaintext": True,
                                            "value_preview": value[:8] + "..." if len(value) > 8 else value,
                                        })
                    # Recurse into nested structures
                    if isinstance(value, (dict, list)):
                        scan(value, new_path)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    scan(item, f"{path}[{i}]")

        for entry in result.get("yaml_configs", []):
            scan(entry.get("data", {}), entry.get("path", ""))
        for entry in result.get("env_files", []):
            scan(entry.get("data", {}), entry.get("path", ""))

        return sensitive

    def _extract_flags(self, result: Dict) -> List[Dict]:
        """Extract feature flags and key parameters from configs."""
        flags: List[Dict] = []

        def scan(obj: Any, path: str = ""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    new_path = f"{path}.{key}" if path else key
                    # Boolean flags
                    if isinstance(value, bool):
                        flags.append({
                            "key": key,
                            "value": value,
                            "config_path": new_path,
                            "type": "boolean_flag",
                        })
                    # Numeric limits/thresholds
                    elif isinstance(value, (int, float)):
                        if any(p.match(key) for p in CONFIG_KEY_PATTERNS.values()):
                            flags.append({
                                "key": key,
                                "value": value,
                                "config_path": new_path,
                                "type": "numeric_param",
                            })
                    # String endpoints/URLs
                    elif isinstance(value, str):
                        for flag_type, pattern in CONFIG_KEY_PATTERNS.items():
                            if pattern.match(key) and len(value) > 0:
                                flags.append({
                                    "key": key,
                                    "value": self._mask_sensitive(value) if any(
                                        sp.match(key) for sp in SENSITIVE_PATTERNS.values()
                                    ) else value,
                                    "config_path": new_path,
                                    "type": f"{flag_type}_param",
                                })
                                break
                    # Recurse
                    if isinstance(value, (dict, list)):
                        scan(value, new_path)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    scan(item, f"{path}[{i}]")

        for entry in result.get("yaml_configs", []):
            scan(entry.get("data", {}), entry.get("path", ""))

        return flags

    @staticmethod
    def _mask_sensitive(value: str) -> str:
        """Mask sensitive values, showing only first/last chars."""
        if len(value) <= 8:
            return "***"
        return value[:4] + "..." + value[-4:]

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        """Check if a value is a placeholder rather than a real secret."""
        placeholders = [
            "changeme", "replace_me", "your_", "example", "placeholder",
            "xxx", "TODO", "FIXME", "${", "{{", "<", "insert", "default",
            "none", "null", "empty",
        ]
        lower = value.lower()
        return any(p in lower for p in placeholders)
