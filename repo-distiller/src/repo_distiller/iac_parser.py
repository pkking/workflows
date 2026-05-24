import json
import yaml
from pathlib import Path
from typing import Dict, List, Optional


class IaCAnalyzer:

    def analyze(self, repo_path: Path) -> Dict:
        result = {"helm": [], "kustomize": [], "argocd": []}
        
        helm_charts = list(repo_path.rglob("Chart.yaml"))
        for chart_file in helm_charts:
            result["helm"].append(self._parse_helm(chart_file.parent))
            
        kustomize_files = list(repo_path.rglob("kustomization.yaml")) + \
                          list(repo_path.rglob("kustomization.yml"))
        for k_file in kustomize_files:
            result["kustomize"].append(self._parse_kustomize(k_file))
            
        argocd_apps = list(repo_path.rglob("Application.yaml")) + \
                      list(repo_path.rglob("Application.yml")) + \
                      list(repo_path.rglob("application.yaml"))
        for app_file in argocd_apps:
            result["argocd"].append(self._parse_argocd(app_file))
            
        return result

    def _parse_helm(self, chart_dir: Path) -> Dict:
        chart_file = chart_dir / "Chart.yaml"
        values_file = chart_dir / "values.yaml"
        
        chart_data = {}
        if chart_file.exists():
            chart_data = yaml.safe_load(chart_file.read_text()) or {}
            
        values_data = {}
        if values_file.exists():
            values_data = yaml.safe_load(values_file.read_text()) or {}
            
        return {
            "name": chart_data.get("name", chart_dir.name),
            "version": chart_data.get("version"),
            "dependencies": [d.get("name") for d in chart_data.get("dependencies", [])],
            "values_keys": list(self._flatten_dict(values_data).keys()),
            "path": str(chart_dir.relative_to(chart_dir.parent.parent.parent)), 
        }

    def _parse_kustomize(self, k_file: Path) -> Dict:
        data = yaml.safe_load(k_file.read_text()) or {}
        return {
            "name": k_file.parent.name,
            "bases": data.get("bases", []),
            "resources": data.get("resources", []),
            "patches": data.get("patches", []),
            "path": str(k_file.parent.relative_to(k_file.parent.parent.parent)),
        }

    def _parse_argocd(self, app_file: Path) -> Dict:
        data = yaml.safe_load(app_file.read_text()) or {}
        spec = data.get("spec", {})
        return {
            "name": data.get("metadata", {}).get("name"),
            "project": spec.get("project"),
            "source_repo": spec.get("source", {}).get("repoURL"),
            "source_path": spec.get("source", {}).get("path"),
            "destination": spec.get("destination"),
        }

    def _flatten_dict(self, d, parent_key='', sep='.'):
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)
