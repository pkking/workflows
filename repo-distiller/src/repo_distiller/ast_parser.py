"""Enhanced AST parsing using tree-sitter with language-specific extractors.

Extracts: symbols, API routes (with middleware), data models (struct fields + tags),
import lists, Swagger annotations, and state machine constants.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Any

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
        self.imports: List[str] = []
        self.constants: List[Dict] = []
        self.swagger_docs: List[Dict] = []
        self.function_calls: List[Dict] = []

    def to_dict(self) -> Dict:
        return {
            "path": self.path,
            "symbols": self.symbols,
            "apis": self.apis,
            "models": self.models,
            "imports": self.imports,
            "constants": self.constants,
            "swagger_docs": self.swagger_docs,
            "function_calls": self.function_calls,
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
        self._extract_symbols(tree.root_node, source, result)
        self._extract_apis(tree.root_node, source, result)
        self._extract_imports(tree.root_node, source, result)
        self._extract_constants(tree.root_node, source, result)
        return result

    def _extract_symbols(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type in ("function_definition", "class_definition", "async_function_definition"):
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode("utf-8") if name_node else "unknown"
            sym: Dict[str, Any] = {
                "type": node.type,
                "name": name,
                "line": node.start_point.row,
            }
            if node.type in ("function_definition", "async_function_definition"):
                sym["params"] = self._get_params(node, source)
                # Extract decorators
                decs = [c.text.decode("utf-8") for c in node.children if c.type == "decorator"]
                if decs:
                    sym["decorators"] = decs
            result.symbols.append(sym)

        for child in node.children:
            self._extract_symbols(child, source, result)

    def _extract_apis(self, node: Node, source: bytes, result: ExtractorResult):
        # Flask/FastAPI route decorators: @app.route, @router.get, etc.
        if node.type in ("decorated_definition", "function_definition"):
            decorators = []
            if node.type == "decorated_definition":
                decorators = [c for c in node.children if c.type == "decorator"]
            else:
                decorators = [c for c in node.children if c.type == "decorator"]

            for dec in decorators:
                dec_text = dec.text.decode("utf-8")
                # Match @router.get("/path"), @app.route("/path"), etc.
                m = re.search(
                    r'@[\w.]+\.(get|post|put|delete|patch|route)\s*\(\s*["\']([^"\']+)["\']',
                    dec_text, re.IGNORECASE
                )
                if m:
                    method = m.group(1).upper()
                    if method == "ROUTE":
                        method = "ANY"
                    path = m.group(2)
                    func_node = node.child_by_field_name("definition")
                    handler = ""
                    if func_node:
                        name_node = func_node.child_by_field_name("name")
                        handler = name_node.text.decode("utf-8") if name_node else ""
                    result.apis.append({
                        "method": method,
                        "path": path,
                        "handler": handler,
                        "middleware": [],
                        "line": node.start_point.row,
                    })

        for child in node.children:
            self._extract_apis(child, source, result)

    def _extract_imports(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type in ("import_statement", "import_from_statement"):
            result.imports.append(node.text.decode("utf-8"))
        for child in node.children:
            self._extract_imports(child, source, result)

    def _extract_constants(self, node: Node, source: bytes, result: ExtractorResult):
        # UPPER_CASE = "value" at module or class level
        if node.type == "assignment":
            left = node.child_by_field_name("left")
            if left and left.type == "identifier":
                name = left.text.decode("utf-8")
                if name.isupper() or (len(name) > 2 and name[0].isupper() and '_' in name):
                    right = node.child_by_field_name("right")
                    val = right.text.decode("utf-8").strip('"\'') if right else ""
                    result.constants.append({
                        "name": name,
                        "value": val,
                        "line": node.start_point.row,
                    })
        for child in node.children:
            self._extract_constants(child, source, result)

    def _get_params(self, node: Node, source: bytes) -> str:
        params_node = node.child_by_field_name("parameters")
        return params_node.text.decode("utf-8") if params_node else ""


class TypeScriptExtractor(LanguageExtractor):
    """Extracts TypeScript-specific structures."""

    def extract(self, source: bytes, path: str) -> ExtractorResult:
        result = ExtractorResult(path)
        tree = self.parser.parse(source)
        self._extract_symbols(tree.root_node, source, result)
        self._extract_apis(tree.root_node, source, result)
        self._extract_imports(tree.root_node, source, result)
        self._extract_models(tree.root_node, source, result)
        return result

    def _extract_symbols(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type in ("function_declaration", "class_declaration", "interface_declaration",
                         "type_alias_declaration", "variable_declarator", "method_definition"):
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
        # Express/Fastify: app.get("/path", ...), router.post("/path", ...)
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                func_text = func_node.text.decode("utf-8")
                m = re.search(r'\.(get|post|put|delete|patch|all|use)\s*$', func_text)
                if m:
                    method = m.group(1).upper()
                    args_node = node.child_by_field_name("arguments")
                    if args_node:
                        args = self._extract_route_args(args_node, source)
                        if args["path"]:
                            result.apis.append({
                                "method": method,
                                "path": args["path"],
                                "handler": args.get("handler", ""),
                                "middleware": args.get("middleware", []),
                                "line": node.start_point.row,
                            })
        for child in node.children:
            self._extract_apis(child, source, result)

    def _extract_route_args(self, args_node: Node, source: bytes) -> Dict:
        result: Dict = {"path": "", "handler": "", "middleware": []}
        children = [c for c in args_node.children if c.type not in (",", "(", ")")]
        for c in children:
            text = c.text.decode("utf-8")
            if c.type in ("string", "template_string"):
                result["path"] = text.strip('"\'`')
            elif c.type in ("identifier", "member_expression"):
                result["handler"] = text
            elif c.type == "function" or c.type == "arrow_function":
                result["handler"] = "(inline)"
            else:
                # Potential middleware
                if text and not text.startswith("{"):
                    result["middleware"].append(text)
        return result

    def _extract_models(self, node: Node, source: bytes, result: ExtractorResult):
        # Extract interface and type definitions with fields
        if node.type in ("interface_declaration", "type_alias_declaration"):
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode("utf-8") if name_node else "unknown"
            fields = []
            body = node.child_by_field_name("body")
            if body:
                fields = self._extract_ts_fields(body, source)
            result.models.append({
                "type": "interface" if node.type == "interface_declaration" else "type",
                "name": name,
                "fields": fields,
                "line": node.start_point.row,
            })
        for child in node.children:
            self._extract_models(child, source, result)

    def _extract_ts_fields(self, body: Node, source: bytes) -> List[Dict]:
        fields = []
        for child in body.children:
            if child.type in ("property_signature", "readonly_property_signature",
                             "optional_property_signature", "method_signature"):
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")
                if name_node:
                    field = {
                        "name": name_node.text.decode("utf-8"),
                        "type": type_node.text.decode("utf-8") if type_node else "any",
                    }
                    # Check for optional
                    if "optional" in child.type:
                        field["optional"] = True
                    fields.append(field)
        return fields

    def _extract_imports(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type == "import_statement":
            result.imports.append(node.text.decode("utf-8"))
        for child in node.children:
            self._extract_imports(child, source, result)


class GoExtractor(LanguageExtractor):
    """Enhanced Go-specific extraction: routes, struct fields, swagger, imports."""

    # HTTP method patterns for Gin/Echo/Mux-style routing
    ROUTE_PATTERN = re.compile(
        r'(?:\.((?:GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|ANY|Use|Group|Handle|HandleFunc)'
        r'|[A-Z][a-zA-Z]+))\s*\('
    )

    def extract(self, source: bytes, path: str) -> ExtractorResult:
        result = ExtractorResult(path)
        tree = self.parser.parse(source)

        # Parse swagger docs from comments (before functions)
        self._extract_swagger(tree.root_node, source, result)

        # Parse AST structures
        self._extract_symbols(tree.root_node, source, result)
        self._extract_apis(tree.root_node, source, result)
        self._extract_imports(tree.root_node, source, result)
        self._extract_models(tree.root_node, source, result)
        self._extract_constants(tree.root_node, source, result)

        # Post-process: attach swagger docs to APIs
        self._attach_swagger_to_apis(result)

        return result

    def _extract_symbols(self, node: Node, source: bytes, result: ExtractorResult):
        if node.type in ("function_declaration", "method_declaration"):
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode("utf-8") if name_node else "unknown"
            sym: Dict[str, Any] = {
                "type": node.type,
                "name": name,
                "line": node.start_point.row,
            }
            if node.type == "method_declaration":
                sym["receiver"] = self._get_receiver(node, source)
            result.symbols.append(sym)

        for child in node.children:
            self._extract_symbols(child, source, result)

    def _extract_apis(self, node: Node, source: bytes, result: ExtractorResult):
        """Extract API routes from function call expressions.

        Handles patterns like:
          r.GET("/path", middleware, handler)
          r.POST("/path", handler)
          r.PUT("/path", middleware1, middleware2, handler)
          engine.Handle("/path", handler)
          engine.HandleFunc("/path", handler)
          r.Group("/prefix")
        """
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                func_text = func_node.text.decode("utf-8")
                args_node = node.child_by_field_name("arguments")

                # Match HTTP method calls
                m = re.match(
                    r'(?:[\w.]+\.)?((?:GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|ANY))$',
                    func_text
                )
                if m and args_node:
                    method = m.group(1)
                    route_info = self._parse_gin_args(args_node, source)
                    result.apis.append({
                        "method": method,
                        "path": route_info["path"],
                        "handler": route_info.get("handler", ""),
                        "middleware": route_info.get("middleware", []),
                        "line": node.start_point.row,
                    })

                # Match Handle/HandleFunc
                if func_text.endswith("Handle") or func_text.endswith("HandleFunc"):
                    if args_node:
                        route_info = self._parse_gin_args(args_node, source)
                        result.apis.append({
                            "method": "ANY",
                            "path": route_info["path"],
                            "handler": route_info.get("handler", ""),
                            "middleware": route_info.get("middleware", []),
                            "line": node.start_point.row,
                        })

                # Match Group calls — record for context
                if func_text.endswith(".Group") and args_node:
                    children = [c for c in args_node.children if c.type not in (",", "(", ")")]
                    for c in children:
                        if c.type == "interpreted_string_literal":
                            prefix = c.text.decode("utf-8").strip('"')
                            result.apis.append({
                                "method": "GROUP",
                                "path": prefix,
                                "handler": "",
                                "middleware": [],
                                "line": node.start_point.row,
                            })

        for child in node.children:
            self._extract_apis(child, source, result)

    def _parse_gin_args(self, args_node: Node, source: bytes) -> Dict:
        """Parse Gin-style route arguments: path, [middleware...], handler."""
        result: Dict = {"path": "", "handler": "", "middleware": []}
        children = [c for c in args_node.children if c.type not in (",", "(", ")")]
        pending = []
        for c in children:
            text = c.text.decode("utf-8")
            if c.type == "interpreted_string_literal":
                result["path"] = text.strip('"')
            elif c.type in ("identifier", "qualified_type", "selector_expression"):
                pending.append(text)
            elif c.type == "function_literal":
                result["handler"] = "(inline)"
            elif c.type == "func_definition":
                result["handler"] = "(func_def)"

        # Last pending identifier is typically the handler, rest are middleware
        if pending:
            result["handler"] = pending[-1]
            result["middleware"] = pending[:-1]
        return result

    def _extract_imports(self, node: Node, source: bytes, result: ExtractorResult):
        """Extract individual import paths from import_declaration nodes.

        Handles both single imports and parenthesized import blocks.
        Tree structure: import_declaration -> ["import", import_spec_list]
                       import_spec_list -> ["(", import_spec..., ")"]
                       import_spec -> [name?, path]
        """
        if node.type == "import_declaration":
            # Find import_spec nodes (may be direct children or nested in import_spec_list)
            for child in node.children:
                if child.type == "import_spec":
                    self._parse_import_spec(child, result)
                elif child.type == "import_spec_list":
                    for spec in child.children:
                        if spec.type == "import_spec":
                            self._parse_import_spec(spec, result)

        for child in node.children:
            self._extract_imports(child, source, result)

    def _parse_import_spec(self, spec: Node, result: ExtractorResult):
        """Parse a single import_spec node."""
        path_node = spec.child_by_field_name("path")
        alias_node = spec.child_by_field_name("name")
        alias = alias_node.text.decode("utf-8") if alias_node else ""
        path = path_node.text.decode("utf-8").strip('"') if path_node else ""
        if path:
            entry = {"path": path}
            if alias:
                entry["alias"] = alias
            result.imports.append(entry)

    def _extract_models(self, node: Node, source: bytes, result: ExtractorResult):
        """Extract struct definitions with fields and tags.

        Tree structure: type_declaration -> ["type", type_spec...]
                       type_spec -> [name, type]
        Note: type_spec is accessed via child_by_field_name("type"), not as a direct child.
        """
        if node.type == "type_declaration":
            # type_spec is accessed via the "type" field name
            for child in node.children:
                if child.type == "type_spec":
                    self._parse_type_spec(child, source, result)

        for child in node.children:
            self._extract_models(child, source, result)

    def _parse_type_spec(self, spec: Node, source: bytes, result: ExtractorResult):
        """Parse a single type_spec node into a model entry."""
        name_node = spec.child_by_field_name("name")
        type_node = spec.child_by_field_name("type")
        if not name_node or not type_node:
            return
        name = name_node.text.decode("utf-8")
        if type_node.type == "struct_type":
            fields = self._extract_struct_fields(type_node, source)
            result.models.append({
                "type": "struct",
                "name": name,
                "fields": fields,
                "line": spec.start_point.row,
            })
        elif type_node.type == "interface_type":
            result.models.append({
                "type": "interface",
                "name": name,
                "fields": [],
                "line": spec.start_point.row,
            })

    def _extract_struct_fields(self, struct_node: Node, source: bytes) -> List[Dict]:
        """Extract struct fields with names, types, and tags (json, bson, gorm, etc.).

        Tree structure: struct_type -> ["struct", field_declaration_list]
                       field_declaration_list -> ["{", field_declaration..., "}"]
        """
        fields = []
        # Find field_declaration_list as a direct child
        for child in struct_node.children:
            if child.type == "field_declaration_list":
                for decl in child.children:
                    if decl.type == "field_declaration":
                        field = self._parse_field_declaration(decl, source)
                        if field:
                            fields.append(field)
                break
        return fields

    def _parse_field_declaration(self, node: Node, source: bytes) -> Optional[Dict]:
        """Parse a single struct field: Name Type `tags`."""
        names = []
        field_type = ""
        tags = {}

        for child in node.children:
            if child.type == "identifier" or child.type == "field_identifier":
                names.append(child.text.decode("utf-8"))
            elif child.type == "pointer_type":
                # *Type
                inner = child.child_by_field_name("type")
                if inner:
                    field_type = "*" + inner.text.decode("utf-8")
                else:
                    field_type = child.text.decode("utf-8")
            elif child.type in ("slice_type", "array_type", "map_type", "qualified_type",
                                "type_identifier", "generic_type"):
                field_type = child.text.decode("utf-8")
            elif child.type == "interpreted_string_literal":
                tags = self._parse_tags(child.text.decode("utf-8"))
            elif child.type == "raw_string_literal":
                # Go struct tags use backticks → raw_string_literal
                tags = self._parse_tags(child.text.decode("utf-8"))

        if not names:
            # Embedded field
            type_node = node.child_by_field_name("type")
            if type_node:
                names = [type_node.text.decode("utf-8")]
                field_type = names[0]

        if names:
            return {
                "names": names,
                "type": field_type,
                "tags": tags,
            }
        return None

    def _parse_tags(self, raw: str) -> Dict[str, str]:
        """Parse Go struct tags: `json:"name" bson:"name,omitempty" gorm:"column:id"`."""
        tags = {}
        raw = raw.strip('`')
        # Match key:"value" pairs
        for m in re.finditer(r'(\w+):"([^"]*)"', raw):
            key = m.group(1)
            val = m.group(2)
            tags[key] = val
        return tags

    def _extract_constants(self, node: Node, source: bytes, result: ExtractorResult):
        """Extract const blocks — useful for state machine detection."""
        if node.type == "const_declaration":
            spec = node.child_by_field_name("spec")
            if spec and spec.type == "const_spec":
                self._extract_const_spec(spec, source, result)
            else:
                for child in node.children:
                    if child.type == "const_spec":
                        self._extract_const_spec(child, source, result)
        for child in node.children:
            self._extract_constants(child, source, result)

    def _extract_const_spec(self, spec: Node, source: bytes, result: ExtractorResult):
        name_node = spec.child_by_field_name("name")
        value_node = spec.child_by_field_name("value")
        if name_node:
            name = name_node.text.decode("utf-8")
            value = value_node.text.decode("utf-8") if value_node else ""
            result.constants.append({
                "name": name,
                "value": value,
                "line": spec.start_point.row,
            })

    def _extract_swagger(self, node: Node, source: bytes, result: ExtractorResult):
        """Extract Swagger annotations from grouped comments.

        Swagger comments are individual `comment` nodes (each `// @...` line).
        We collect all comments, then group consecutive swagger-annotated comments
        into single doc blocks.
        """
        all_comments = self._collect_comments(node, source)

        # Group consecutive swagger comments
        groups: List[List[Node]] = []
        current_group: List[Node] = []
        prev_end = -1

        for comment in all_comments:
            text = comment.text.decode("utf-8")
            has_swagger = any(
                kw in text
                for kw in ['@Summary', '@Description', '@Tags', '@Router',
                           '@Param', '@Success', '@Failure', '@Accept', '@Produce']
            )
            if has_swagger:
                # Check if this comment is adjacent to the previous one
                if current_group and (comment.start_point.row - prev_end <= 2):
                    current_group.append(comment)
                else:
                    if current_group:
                        groups.append(current_group)
                    current_group = [comment]
                prev_end = comment.end_point.row
            else:
                if current_group:
                    groups.append(current_group)
                    current_group = []
        if current_group:
            groups.append(current_group)

        # Parse each group into a swagger doc
        for group in groups:
            doc: Dict[str, Any] = {"line": group[0].start_point.row}
            for comment in group:
                text = comment.text.decode("utf-8")
                for line in text.split('\n'):
                    line = line.strip().lstrip('/')
                    line = line.strip()
                    if line.startswith("@Summary"):
                        doc["summary"] = line[len("@Summary"):].strip()
                    elif line.startswith("@Description"):
                        doc["description"] = line[len("@Description"):].strip()
                    elif line.startswith("@Tags"):
                        doc.setdefault("tags", []).append(line[len("@Tags"):].strip())
                    elif line.startswith("@Router"):
                        m = re.search(r'(\S+)\s*\[(\w+)\]', line)
                        if m:
                            doc["router_path"] = m.group(1)
                            doc["router_method"] = m.group(2).upper()
                    elif line.startswith("@Param"):
                        doc.setdefault("params", []).append(line[len("@Param"):].strip())
                    elif line.startswith("@Success"):
                        doc.setdefault("responses", {})["success"] = line[len("@Success"):].strip()
                    elif line.startswith("@Failure"):
                        doc.setdefault("responses", {})["failure"] = line[len("@Failure"):].strip()
                    elif line.startswith("@Accept") or line.startswith("@Produce"):
                        doc["content_type"] = line.split()[0] if len(line.split()) > 1 else ""

            if "summary" in doc or "router_path" in doc:
                result.swagger_docs.append(doc)

    def _collect_comments(self, node: Node, source: bytes) -> List[Node]:
        """Recursively collect comment nodes."""
        comments = []
        if node.type in ("comment", "comment_group"):
            comments.append(node)
        for child in node.children:
            comments.extend(self._collect_comments(child, source))
        return comments

    def _attach_swagger_to_apis(self, result: ExtractorResult):
        """Match swagger docs to APIs by path+method."""
        for api in result.apis:
            if api["method"] == "GROUP":
                continue
            for doc in result.swagger_docs:
                if "router_path" in doc and "router_method" in doc:
                    # Normalize paths for comparison
                    api_path = api["path"].rstrip("/")
                    doc_path = doc["router_path"].rstrip("/")
                    if api_path == doc_path and api["method"] == doc["router_method"]:
                        api["swagger"] = doc
                        break

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
    """Extracts structure from source code with enhanced extraction."""

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
