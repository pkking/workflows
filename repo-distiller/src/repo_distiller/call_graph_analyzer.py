"""Call graph and error propagation analysis.

Extracts:
- Function/method call graphs from AST data
- Error creation → propagation → consumption chains
"""

import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict

import tree_sitter_go
from tree_sitter import Language, Parser, Node


# ─── Go-specific AST walker ──────────────────────────────────────────────

GO_LANG = Language(tree_sitter_go.language())
GO_PARSER = Parser(GO_LANG)


class CallGraphExtractor:
    """Builds call graphs from Go source code."""

    def __init__(self):
        self.symbols: Dict[str, Dict] = {}  # "package.FuncName" → info
        self.methods: Dict[str, Dict] = {}  # "ReceiverType.MethodName" → info
        self.calls: List[Dict] = []
        self.imports_by_file: Dict[str, List[str]] = {}

    def analyze_repo(self, repo_path: Path) -> Dict:
        """Analyze all Go files in a repository."""
        go_files = list(repo_path.rglob("*.go"))
        go_files = [f for f in go_files if "vendor" not in str(f) and "_test.go" not in str(f) and "_mock.go" not in str(f)]

        # Phase 1: Build symbol table
        for f in go_files:
            try:
                source = f.read_bytes()
                tree = GO_PARSER.parse(source)
                file_info = self._extract_file_info(tree.root_node, source, str(f.relative_to(repo_path)))
                self._merge_file_info(file_info)
            except Exception:
                continue

        # Phase 2: Extract calls (needs symbol table built first)
        for f in go_files:
            try:
                source = f.read_bytes()
                tree = GO_PARSER.parse(source)
                self._extract_calls(tree.root_node, source, str(f.relative_to(repo_path)))
            except Exception:
                continue

        # Phase 3: Resolve calls to symbols
        resolved = self._resolve_calls()

        return {
            "symbols": self.symbols,
            "methods": self.methods,
            "calls": self.calls,
            "resolved_calls": resolved,
            "summary": {
                "total_symbols": len(self.symbols),
                "total_methods": len(self.methods),
                "total_calls": len(self.calls),
                "total_resolved": len(resolved),
            },
        }

    def _extract_file_info(self, node: Node, source: bytes, file_path: str) -> Dict:
        """Extract package name, functions, methods, and imports from a file."""
        info = {"path": file_path, "package": "", "functions": [], "methods": [], "imports": []}

        for child in node.children:
            if child.type == "package_clause":
                # Package name is a package_identifier child
                for gc in child.children:
                    if gc.type == "package_identifier":
                        info["package"] = gc.text.decode("utf-8")
                        break

            elif child.type == "import_declaration":
                self._extract_imports_from_decl(child, info["imports"])

            elif child.type == "function_declaration":
                # Function name is an identifier child (not accessed via field name)
                func_name = ""
                params_node = None
                results_node = None
                for gc in child.children:
                    if gc.type == "identifier":
                        func_name = gc.text.decode("utf-8")
                    elif gc.type == "parameter_list":
                        if not params_node:  # First parameter_list is params
                            params_node = gc
                        else:  # Second parameter_list is results
                            results_node = gc

                if func_name:
                    params = params_node.text.decode("utf-8") if params_node else ""
                    results = results_node.text.decode("utf-8") if results_node else ""
                    info["functions"].append({
                        "name": func_name,
                        "line": child.start_point.row,
                        "params": params,
                        "results": results,
                        "full_key": f"{info['package']}.{func_name}",
                    })

            elif child.type == "method_declaration":
                # Method name is a field_identifier child; receiver is first parameter_list
                method_name = ""
                recv_type = ""
                params_node = None
                results_node = None
                for gc in child.children:
                    if gc.type == "field_identifier":
                        method_name = gc.text.decode("utf-8")
                    elif gc.type == "parameter_list":
                        # First param_list after func is the receiver
                        if not recv_type:
                            # Extract receiver type from parameter_list
                            for pc in gc.children:
                                if pc.type == "parameter_declaration":
                                    for pcc in pc.children:
                                        if pcc.type == "type_identifier":
                                            recv_type = pcc.text.decode("utf-8")
                                            break
                                    break
                        elif not params_node:
                            params_node = gc
                        else:
                            results_node = gc

                if method_name and recv_type:
                    params = params_node.text.decode("utf-8") if params_node else ""
                    results = results_node.text.decode("utf-8") if results_node else ""
                    info["methods"].append({
                        "name": method_name,
                        "receiver": recv_type,
                        "line": child.start_point.row,
                        "params": params,
                        "results": results,
                        "full_key": f"{recv_type}.{method_name}",
                    })

        return info

    def _extract_imports_from_decl(self, node: Node, imports: List):
        """Extract import paths from an import_declaration."""
        for child in node.children:
            if child.type == "import_spec":
                path = ""
                alias = ""
                for gc in child.children:
                    if gc.type == "interpreted_string_literal":
                        path = gc.text.decode("utf-8").strip('"')
                    elif gc.type == "identifier" or gc.type == "package_identifier":
                        alias = gc.text.decode("utf-8")
                if path:
                    imports.append({"path": path, "alias": alias})
            elif child.type == "import_spec_list":
                for spec in child.children:
                    if spec.type == "import_spec":
                        path = ""
                        alias = ""
                        for gc in spec.children:
                            if gc.type == "interpreted_string_literal":
                                path = gc.text.decode("utf-8").strip('"')
                            elif gc.type == "identifier" or gc.type == "package_identifier":
                                alias = gc.text.decode("utf-8")
                        if path:
                            imports.append({"path": path, "alias": alias})

    def _merge_file_info(self, info: Dict):
        """Merge file info into the global symbol table."""
        for func in info["functions"]:
            key = func["full_key"]
            self.symbols[key] = {
                "name": func["name"],
                "package": info["package"],
                "file": info["path"],
                "line": func["line"],
                "params": func["params"],
                "results": func["results"],
            }

        for method in info["methods"]:
            key = method["full_key"]
            if key not in self.methods:
                self.methods[key] = []
            self.methods[key].append({
                "receiver": method["receiver"],
                "file": info["path"],
                "line": method["line"],
                "params": method["params"],
                "results": method["results"],
            })

        self.imports_by_file[info["path"]] = info["imports"]

    def _extract_calls(self, node: Node, source: bytes, file_path: str):
        """Extract all call expressions from a file."""
        # Find which function/method we're inside
        current_func = None
        for child in node.children:
            if child.type in ("function_declaration", "method_declaration"):
                name_node = child.child_by_field_name("name")
                if name_node:
                    current_func = name_node.text.decode("utf-8")
                self._extract_calls_recursive(child, source, file_path, current_func)

    def _extract_calls_recursive(self, node: Node, source: bytes, file_path: str, caller: str):
        """Recursively find call expressions."""
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            args_node = node.child_by_field_name("arguments")
            if func_node:
                call_text = func_node.text.decode("utf-8")
                args_text = args_node.text.decode("utf-8")[:100] if args_node else ""

                # Parse the call into components
                parsed = self._parse_call_text(call_text)

                call_info = {
                    "caller": caller,
                    "caller_file": file_path,
                    "line": node.start_point.row,
                    "raw": call_text,
                    "args_preview": args_text,
                    **parsed,
                }
                self.calls.append(call_info)

        for child in node.children:
            self._extract_calls_recursive(child, source, file_path, caller)

    def _parse_call_text(self, text: str) -> Dict:
        """Parse a call expression text into components.

        Examples:
          "ctl.service.ApplyNewPkg" → selector=ctl.service, method=ApplyNewPkg
          "commonctl.SendError" → selector=commonctl, function=SendError
          "errors.New" → selector=errors, function=New
          "fmt.Errorf" → selector=fmt, function=Errorf
          "middleware.UserChecking().FetchUser" → chain call
        """
        result: Dict = {"type": "unknown", "package": "", "name": "", "receiver": ""}

        # Chain calls: x.y().z → two calls
        if "()" in text:
            result["type"] = "chained"
            result["raw_chain"] = text
            # Split on () to get the chain
            parts = text.split("()")
            result["name"] = parts[-1].lstrip(".").split("(")[0] if parts else ""
            result["receiver"] = parts[0] if parts else ""
            return result

        # Qualified calls: pkg.Func or receiver.Method
        if "." in text:
            parts = text.rsplit(".", 1)
            result["receiver"] = parts[0]
            result["name"] = parts[1]

            # Check if receiver is a known package alias
            if "/" in result["receiver"] or result["receiver"] in ("errors", "fmt", "log", "os", "io", "net", "http", "context", "strings", "strconv", "time", "json", "yaml"):
                result["type"] = "package_call"
                result["package"] = result["receiver"]
            else:
                result["type"] = "method_call"
        else:
            result["type"] = "local_call"
            result["name"] = text

        return result

    def _resolve_calls(self) -> List[Dict]:
        """Try to resolve calls to their target symbols."""
        resolved = []
        for call in self.calls:
            res = dict(call)
            res["resolved"] = False
            res["target_file"] = ""
            res["target_line"] = 0

            if call["type"] == "method_call":
                # Try to match receiver.name to methods
                key = f"{call['receiver']}.{call['name']}"
                if key in self.methods:
                    res["resolved"] = True
                    res["target_file"] = self.methods[key][0]["file"]
                    res["target_line"] = self.methods[key][0]["line"]
                    res["target_key"] = key

            elif call["type"] == "package_call":
                # Try to match package.name to symbols
                key = f"{call['package']}.{call['name']}"
                if key in self.symbols:
                    res["resolved"] = True
                    res["target_file"] = self.symbols[key]["file"]
                    res["target_line"] = self.symbols[key]["line"]
                    res["target_key"] = key

            elif call["type"] == "chained":
                # Chained calls: middleware.UserChecking().FetchUser
                key = call.get("name", "")
                receiver = call.get("receiver", "")
                if key:
                    # Try exact match first
                    for method_key in self.methods:
                        if method_key == f"{receiver}.{key}" or method_key.endswith(f".{key}"):
                            res["resolved"] = True
                            res["target_file"] = self.methods[method_key][0]["file"]
                            res["target_line"] = self.methods[method_key][0]["line"]
                            res["target_key"] = method_key
                            break

            elif call["type"] == "local_call":
                # Local function call — try to match within the same package
                key = call.get("name", "")
                if key:
                    for sym_key, sym_info in self.symbols.items():
                        if sym_key.endswith(f".{key}"):
                            res["resolved"] = True
                            res["target_file"] = sym_info["file"]
                            res["target_line"] = sym_info["line"]
                            res["target_key"] = sym_key
                            break

            resolved.append(res)

        return resolved



# ─── Error Flow Analyzer ─────────────────────────────────────────────────

class ErrorFlowAnalyzer:
    """Analyzes error creation, propagation, and consumption patterns."""

    def analyze_repo(self, repo_path: Path) -> Dict:
        """Analyze all Go files for error flow patterns."""
        go_files = list(repo_path.rglob("*.go"))
        go_files = [f for f in go_files if "vendor" not in str(f) and "_test.go" not in str(f) and "_mock.go" not in str(f)]

        errors_created = []
        errors_propagated = []
        errors_consumed = []
        error_patterns = []

        for f in go_files:
            try:
                source = f.read_bytes()
                tree = GO_PARSER.parse(source)
                file_path = str(f.relative_to(repo_path))

                self._extract_error_creations(tree.root_node, source, file_path, errors_created)
                self._extract_error_propagations(tree.root_node, source, file_path, errors_propagated)
                self._extract_error_consumptions(tree.root_node, source, file_path, errors_consumed)
                self._extract_error_patterns(tree.root_node, source, file_path, error_patterns)
            except Exception:
                continue

        # Build error flow chains
        chains = self._build_error_chains(errors_created, errors_propagated, errors_consumed)

        return {
            "errors_created": errors_created,
            "errors_propagated": errors_propagated,
            "errors_consumed": errors_consumed,
            "error_patterns": error_patterns,
            "error_chains": chains,
            "summary": {
                "total_creations": len(errors_created),
                "total_propagations": len(errors_propagated),
                "total_consumptions": len(errors_consumed),
                "total_chains": len(chains),
                "unhandled_errors": len([c for c in chains if not c["has_handler"]]),
            },
        }

    def _extract_error_creations(self, node: Node, source: bytes, file_path: str, results: List):
        """Find error creation sites."""
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                func_text = func_node.text.decode("utf-8")
                # Match error creation patterns
                error_patterns = [
                    "errors.New", "fmt.Errorf", "allerror.New",
                    "allerror.NewNotFound", "allerror.NewBadRequest",
                    "allerror.NewUnauthorized", "allerror.NewForbidden",
                    "NewError", "NewNotFound", "NewBadRequest",
                    "NewUnauthorized", "NewForbidden",
                ]
                for pat in error_patterns:
                    if func_text == pat or func_text.endswith(f".{pat}"):
                        results.append({
                            "file": file_path,
                            "line": node.start_point.row,
                            "type": "creation",
                            "function": func_text,
                            "raw": node.text.decode("utf-8")[:120],
                        })
                        break

        for child in node.children:
            self._extract_error_creations(child, source, file_path, results)

    def _extract_error_propagations(self, node: Node, source: bytes, file_path: str, results: List):
        """Find error return statements."""
        if node.type == "return_statement":
            text = node.text.decode("utf-8")
            if "err" in text.lower():
                # Check parent is a function/method
                results.append({
                    "file": file_path,
                    "line": node.start_point.row,
                    "type": "propagation",
                    "raw": text.strip()[:100],
                })

        for child in node.children:
            self._extract_error_propagations(child, source, file_path, results)

    def _extract_error_consumptions(self, node: Node, source: bytes, file_path: str, results: List):
        """Find error handling sites (if err != nil patterns)."""
        if node.type == "if_statement":
            condition = node.child_by_field_name("condition")
            if condition:
                cond_text = condition.text.decode("utf-8")
                if "err" in cond_text.lower() and "nil" in cond_text.lower():
                    # Check what happens in the body
                    body = node.child_by_field_name("consequence")
                    if body:
                        body_text = body.text.decode("utf-8")
                        handler_type = self._classify_error_handler(body_text)
                        results.append({
                            "file": file_path,
                            "line": node.start_point.row,
                            "type": "consumption",
                            "handler_type": handler_type,
                            "condition": cond_text,
                            "handler_preview": body_text[:100],
                        })

        for child in node.children:
            self._extract_error_consumptions(child, source, file_path, results)

    def _extract_error_patterns(self, node: Node, source: bytes, file_path: str, results: List):
        """Find error-related patterns: swallowed errors, error wrapping, etc."""
        # Swallowed errors: err is assigned but never checked
        if node.type == "short_var_declaration":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left and right:
                left_text = left.text.decode("utf-8")
                right_text = right.text.decode("utf-8")
                if "err" in left_text.lower() and ("()" in right_text or "call_expression" in right_text):
                    # Check if there's a subsequent err check
                    parent = node.parent
                    if parent:
                        next_siblings = []
                        found_node = False
                        for sibling in parent.children:
                            if found_node:
                                next_siblings.append(sibling)
                            if sibling == node:
                                found_node = True

                        has_check = False
                        for s in next_siblings[:10]:  # Check next 10 siblings
                            if s.type == "if_statement":
                                cond = s.child_by_field_name("condition")
                                if cond and "err" in cond.text.decode("utf-8").lower():
                                    has_check = True
                                    break

                        if not has_check:
                            results.append({
                                "file": file_path,
                                "line": node.start_point.row,
                                "type": "potentially_swallowed",
                                "raw": node.text.decode("utf-8")[:100],
                            })

        for child in node.children:
            self._extract_error_patterns(child, source, file_path, results)

    def _classify_error_handler(self, body_text: str) -> str:
        """Classify how an error is handled."""
        text_lower = body_text.lower()
        if "return" in text_lower:
            if "nil" in text_lower and "err" in text_lower:
                return "return_error"
            return "return_early"
        if "log" in text_lower:
            return "log_and_continue"
        if "senderror" in text_lower or "sendresp" in text_lower or "sendbad" in text_lower:
            return "http_response"
        if "panic" in text_lower:
            return "panic"
        return "unknown"

    def _build_error_chains(self, created: List, propagated: List, consumed: List) -> List[Dict]:
        """Build error flow chains by proximity analysis."""
        chains = []

        # Group by file
        by_file: Dict[str, Dict] = defaultdict(lambda: {"created": [], "propagated": [], "consumed": []})
        for item in created:
            by_file[item["file"]]["created"].append(item)
        for item in propagated:
            by_file[item["file"]]["propagated"].append(item)
        for item in consumed:
            by_file[item["file"]]["consumed"].append(item)

        for file_path, items in by_file.items():
            for creation in items["created"]:
                # Find nearest consumption after creation
                nearest_consumer = None
                min_distance = float('inf')
                for consumer in items["consumed"]:
                    distance = consumer["line"] - creation["line"]
                    if 0 < distance < min_distance:
                        min_distance = distance
                        nearest_consumer = consumer

                chain = {
                    "file": file_path,
                    "creation_line": creation["line"],
                    "creation_func": creation.get("function", ""),
                    "consumption_line": nearest_consumer["line"] if nearest_consumer else None,
                    "consumption_type": nearest_consumer.get("handler_type", "") if nearest_consumer else "none",
                    "has_handler": nearest_consumer is not None,
                    "distance_lines": min_distance if nearest_consumer else None,
                }
                chains.append(chain)

        return chains
