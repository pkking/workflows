"""AST parsing using tree-sitter with language-specific extractors."""

import json
from pathlib import Path
from typing import Dict, List, Optional

import tree_sitter_python
import tree_sitter_typescript
import tree_sitter_go
from tree_sitter import Language, Parser, Node

LANGUAGES = {
    ".py": Language(tree_sitter_python.language()),
    ".ts": Language(tree_sitter_typescript.language_typescript()),
    ".tsx": Language(tree_sitter_typescript.language_tsx()),
    ".go": Language(tree_sitter_go.language()),
}

PARSERS = {ext: Parser(lang) for ext, lang in LANGUAGES.items()}


class ExtractorResult:
    """Holds extracted information from a file."""
    def __init__(self, path: str):
        self.path = path
        self.symbols: List[Dict] = []
        self.apis: List[Dict] = []
        self.models: List[Dict] = []
        self.entry_points: List[Dict] = []
        self.imports: List[str] = []

    def to_dict(self) -> Dict:
        return {
            "path": self.path,
            "symbols": self.symbols,
            "apis": self.apis,
            "models": self.models,
            "entry_points": self.entry_points,
            "imports": self.imports,
        }


class LanguageExtractor:
    """Base class for language-specific extraction."""

    def __init__(self, parser: Parser, language: Language):
        self.parser = parser
        self.language = language

    def extract(self, source: bytes, path: str) -> ExtractorResult:
        raise NotImplementedError


class PythonExtractor(LanguageExtractor):
    """Extracts Python-specific structures."""

    def extract(self, source: bytes, path: str) -> ExtractorResult:
        result = ExtractorResult(path)
        tree = self.parser.parse(source)
        root = tree.root_node

        self._extract_symbols(root, source, result)
        self._extract_apis(root, source, result)
        self._extract_imports(root, source, result)
        return result

    def _extract_symbols(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type in ("function_definition", "class_definition"):
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode("utf-8") if name_node else "unknown"
            result.symbols.append({
                "type": node.type,
                "name": name,
                "line": node.start_point.row,
                "params": self._get_params(node, source),
            })
        
        for child in node.children:
            self._extract_symbols(child, source, result)

    def _extract_apis(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type == "decorated_definition":
            for dec in node.children:
                if dec.type == "decorator":
                    dec_text = dec.text.decode("utf-8")
                    if "@" in dec_text and ("route" in dec_text or "api" in dec_text.lower()):
                        func_node = node.child_by_field_name("definition")
                        if func_node:
                            name_node = func_node.child_by_field_name("name")
                            result.apis.append({
                                "route": dec_text,
                                "handler": name_node.text.decode("utf-8") if name_node else "unknown",
                                "line": node.start_point.row,
                            })
        for child in node.children:
            self._extract_apis(child, source, result)

    def _extract_imports(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type == "import_statement" or node.type == "import_from_statement":
            result.imports.append(node.text.decode("utf-8"))
        for child in node.children:
            self._extract_imports(child, source, result)

    def _get_params(self, node: Node, source: bytes) -> str:
        params_node = node.child_by_field_name("parameters")
        return params_node.text.decode("utf-8") if params_node else ""


class TypeScriptExtractor(LanguageExtractor):
    """Extracts TypeScript-specific structures."""

    def extract(self, source: bytes, path: str) -> ExtractorResult:
        result = ExtractorResult(path)
        tree = self.parser.parse(source)
        root = tree.root_node

        self._extract_symbols(root, source, result)
        self._extract_apis(root, source, result)
        self._extract_imports(root, source, result)
        return result

    def _extract_symbols(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type in ("function_declaration", "class_declaration", "interface_declaration", "type_alias_declaration", "variable_declarator"):
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode("utf-8") if name_node else "unknown"
            result.symbols.append({
                "type": node.type,
                "name": name,
                "line": node.start_point.row,
            })
        
        for child in node.children:
            self._extract_symbols(child, source, result)

    def _extract_apis(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                func_text = func_node.text.decode("utf-8")
                if "route" in func_text or "get" in func_text or "post" in func_text or "put" in func_text or "delete" in func_text:
                    args_node = node.child_by_field_name("arguments")
                    result.apis.append({
                        "method": func_text.split(".")[-1] if "." in func_text else func_text,
                        "path": args_node.text.decode("utf-8") if args_node else "unknown",
                        "line": node.start_point.row,
                    })
        for child in node.children:
            self._extract_apis(child, source, result)

    def _extract_imports(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type == "import_statement":
            result.imports.append(node.text.decode("utf-8"))
        for child in node.children:
            self._extract_imports(child, source, result)


class GoExtractor(LanguageExtractor):
    """Extracts Go-specific structures."""

    def extract(self, source: bytes, path: str) -> ExtractorResult:
        result = ExtractorResult(path)
        tree = self.parser.parse(source)
        root = tree.root_node

        self._extract_symbols(root, source, result)
        self._extract_apis(root, source, result)
        self._extract_imports(root, source, result)
        return result

    def _extract_symbols(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type == "function_declaration" or node.type == "method_declaration":
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode("utf-8") if name_node else "unknown"
            result.symbols.append({
                "type": node.type,
                "name": name,
                "line": node.start_point.row,
                "receiver": self._get_receiver(node, source),
            })
        elif node.type == "type_declaration":
            spec_node = node.child_by_field_name("type")
            if spec_node:
                name_node = spec_node.child_by_field_name("name")
                name = name_node.text.decode("utf-8") if name_node else "unknown"
                result.models.append({
                    "type": "struct",
                    "name": name,
                    "line": node.start_point.row,
                })
        
        for child in node.children:
            self._extract_symbols(child, source, result)

    def _extract_apis(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                func_text = func_node.text.decode("utf-8")
                if "HandleFunc" in func_text or "GET" in func_text or "POST" in func_text:
                    args_node = node.child_by_field_name("arguments")
                    result.apis.append({
                        "handler": func_text,
                        "route": args_node.text.decode("utf-8") if args_node else "unknown",
                        "line": node.start_point.row,
                    })
        for child in node.children:
            self._extract_apis(child, source, result)

    def _extract_imports(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type == "import_declaration":
            result.imports.append(node.text.decode("utf-8"))
        for child in node.children:
            self._extract_imports(child, source, result)

    def _get_receiver(self, node: Node, source: bytes) -> str:
        recv_node = node.child_by_field_name("receiver")
        return recv_node.text.decode("utf-8") if recv_node else ""


EXTRACTORS = {
    ".py": PythonExtractor,
    ".ts": TypeScriptExtractor,
    ".tsx": TypeScriptExtractor,
    ".go": GoExtractor,
}


class ASTAnalyzer:
    """Extracts structure from source code."""

    def analyze_file(self, file_path: Path) -> Optional[Dict]:
        ext = file_path.suffix
        extractor_cls = EXTRACTORS.get(ext)
        if not extractor_cls:
            return None

        lang = LANGUAGES.get(ext)
        parser = PARSERS.get(ext)
        if not lang or not parser:
            return None

        extractor = extractor_cls(parser, lang)
        
        try:
            source = file_path.read_bytes()
            result = extractor.extract(source, str(file_path))
            return result.to_dict()
        except Exception:
            return None
