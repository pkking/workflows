"""Database schema analysis: ER relationships, API schemas, and database schemas.

Extracts:
- Entity relationships (one-to-many, references, composition) from Go struct fields
- API request/response schemas from controller request structs + Swagger annotations
- MongoDB collection schemas from Go structs with bson tags
- PostgreSQL table schemas from Go structs with gorm tags
- SQL CREATE TABLE statements
"""

import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import OrderedDict


class SchemaAnalyzer:
    """Analyzes data models for relationships, API schemas, and database schemas."""

    # Patterns to identify MongoDB-related code
    MONGO_PATTERNS = [
        re.compile(r'mongodb.*Collection|Collection.*mongodb', re.IGNORECASE),
        re.compile(r'go\.mongodb\.org/mongo-driver', re.IGNORECASE),
        re.compile(r'mongodblib', re.IGNORECASE),
    ]

    # Patterns to identify PostgreSQL/GORM-related code
    GORM_PATTERNS = [
        re.compile(r'gorm\.io', re.IGNORECASE),
        re.compile(r'gorm:.*column:', re.IGNORECASE),
        re.compile(r'AutoMigrate', re.IGNORECASE),
    ]

    def analyze(self, repo_path: Path, ast_data: List[Dict]) -> Dict:
        """Run full schema analysis."""
        return {
            "er_diagram": self._build_er_diagram(ast_data),
            "api_schemas": self._build_api_schemas(ast_data),
            "mongodb_collections": self._extract_mongodb_schemas(ast_data),
            "postgresql_tables": self._extract_postgresql_schemas(ast_data),
            "summary": {
                "total_entities": 0,
                "total_relationships": 0,
                "total_api_schemas": 0,
            },
        }

    # ─── ER Diagram ───────────────────────────────────────────────────────

    def _build_er_diagram(self, ast_data: List[Dict]) -> Dict:
        """Build entity-relationship diagram from struct field analysis."""
        # Phase 1: Collect all named structs
        structs: Dict[str, Dict] = {}
        for f in ast_data:
            for m in f.get("models", []):
                if m.get("type") == "struct" and m.get("name"):
                    name = m["name"]
                    if name not in structs:
                        structs[name] = {
                            "name": name,
                            "fields": m.get("fields", []),
                            "file": f.get("path", ""),
                            "relationships": [],
                        }
                    elif not structs[name]["fields"]:
                        structs[name]["fields"] = m.get("fields", [])
                        if not structs[name]["file"]:
                            structs[name]["file"] = f.get("path", "")

        # Phase 2: Analyze relationships
        struct_names = set(structs.keys())
        for name, entity in structs.items():
            for field in entity["fields"]:
                field_names = field.get("names", [])
                field_type = field.get("type", "")

                # One-to-many: slice of another struct type
                slice_match = re.match(r'\[\]\s*(\w+)$', field_type)
                if slice_match:
                    ref_type = slice_match.group(1)
                    if ref_type in struct_names:
                        entity["relationships"].append({
                            "type": "one_to_many",
                            "field": field_names[0] if field_names else "",
                            "target": ref_type,
                        })

                # Reference/foreign key: field type matches another struct
                if field_type in struct_names and field_type != name:
                    entity["relationships"].append({
                        "type": "reference",
                        "field": field_names[0] if field_names else "",
                        "target": field_type,
                    })

                # Foreign key by naming convention: XxxId, xxx_id → Xxx
                if field_names:
                    fk_match = re.match(r'(\w+?)[Ii]d$', field_names[0])
                    if fk_match:
                        ref_type = fk_match.group(1)
                        if ref_type in struct_names:
                            entity["relationships"].append({
                                "type": "foreign_key",
                                "field": field_names[0],
                                "target": ref_type,
                            })

        # Build relationship list
        relationships = []
        for name, entity in structs.items():
            for rel in entity["relationships"]:
                relationships.append({
                    "source": name,
                    "field": rel["field"],
                    "target": rel["target"],
                    "relation_type": rel["type"],
                })

        entity_list = []
        for name, entity in structs.items():
            entity_list.append({
                "name": name,
                "field_count": len(entity["fields"]),
                "relationship_count": len(entity["relationships"]),
                "file": entity["file"],
                "fields_preview": [
                    {"name": f["names"][0] if f.get("names") else "", "type": f.get("type", "")}
                    for f in entity["fields"][:5]
                ],
                "relationships": entity["relationships"],
            })

        return {
            "entities": entity_list,
            "relationships": relationships,
            "total_entities": len(entity_list),
            "total_relationships": len(relationships),
        }

    # ─── API Schemas ──────────────────────────────────────────────────────

    def _build_api_schemas(self, ast_data: List[Dict]) -> Dict:
        """Build API request/response schemas from controller structs + Swagger."""
        schemas = []
        for f in ast_data:
            file_path = f.get("path", "")
            if "controller" not in file_path.lower():
                continue
            for api in f.get("apis", []):
                if api.get("method") in ("GROUP",):
                    continue
                swagger = api.get("swagger", {})
                schema = {
                    "method": api["method"],
                    "path": api.get("path", ""),
                    "handler": api.get("handler", ""),
                    "summary": swagger.get("summary", ""),
                    "tags": swagger.get("tags", []),
                    "file": file_path,
                    "params": [],
                    "responses": {},
                }
                for param_str in swagger.get("params", []):
                    param = self._parse_swagger_param(param_str)
                    if param:
                        schema["params"].append(param)
                responses = swagger.get("responses", {})
                if "success" in responses:
                    schema["responses"]["success"] = responses["success"]
                if "failure" in responses:
                    schema["responses"]["failure"] = responses["failure"]
                if schema["params"] or schema["responses"]:
                    schemas.append(schema)
        return {"schemas": schemas, "total_schemas": len(schemas)}

    def _parse_swagger_param(self, param_str: str) -> Optional[Dict]:
        parts = param_str.split()
        if len(parts) < 4:
            return None
        param = {
            "name": parts[0],
            "param_type": parts[1],
            "data_type": parts[2],
            "required": parts[3].lower() == "true",
            "description": " ".join(parts[4:]).strip('"') if len(parts) > 4 else "",
        }
        return param

    # ─── MongoDB Schema Extraction ────────────────────────────────────────

    def _extract_mongodb_schemas(self, ast_data: List[Dict]) -> List[Dict]:
        """Extract MongoDB collection schemas from Go structs with bson tags.

        Identifies:
        - Structs with bson tags (MongoDB document models)
        - Collection name constants
        - Nested/embedded documents
        - Array fields
        - Field requirements from `required:"true"` tags
        """
        # Phase 1: Build a map of all struct definitions with their fields
        struct_map: Dict[str, Dict] = {}
        for f in ast_data:
            file_path = f.get("path", "")
            # Focus on infrastructure/adapter files where MongoDB models live
            for m in f.get("models", []):
                if m.get("type") == "struct" and m.get("name"):
                    name = m["name"]
                    fields = m.get("fields", [])
                    # Check if any field has bson tags
                    has_bson = any(f.get("tags", {}).get("bson") for f in fields)
                    if has_bson or name.endswith("DO"):
                        struct_map[name] = {
                            "name": name,
                            "fields": fields,
                            "file": file_path,
                            "has_bson": has_bson,
                        }

        # Phase 2: Find collection name constants
        collection_names = {}
        for f in ast_data:
            for const in f.get("constants", []):
                name = const.get("name", "")
                value = const.get("value", "")
                # Look for collection name patterns
                if "collection" in name.lower() or name.endswith("s"):
                    collection_names[name] = value

        # Phase 3: Find root document structs (usually referenced in InsertDoc/FindDoc calls)
        # Heuristic: structs that have many nested references are root documents
        root_candidates = []
        for name, struct in struct_map.items():
            # Root documents typically have:
            # 1. Many fields
            # 2. Array fields of nested docs
            # 3. Are referenced in repository/adapter code
            if len(struct["fields"]) >= 5 and struct["has_bson"]:
                root_candidates.append(name)

        # Phase 4: Build collection schemas
        collections = []
        processed = set()

        def process_struct(name: str, depth: int = 0, parent_collection: str = "") -> Optional[Dict]:
            """Recursively process a struct into a schema field definition."""
            if depth > 5 or name in processed:
                return None

            struct = struct_map.get(name)
            if not struct:
                return None

            fields = []
            for field in struct["fields"]:
                field_info = self._extract_field_info(field, struct_map, depth)
                if field_info:
                    fields.append(field_info)

            result = {
                "name": name,
                "type": "object" if depth > 0 else "collection",
                "fields": fields,
                "file": struct["file"],
            }

            if depth == 0:
                # Find collection name from constants or struct name
                coll_name = self._find_collection_name(name, collection_names, struct["file"])
                result["collection_name"] = coll_name
                result["field_count"] = len(fields)

            return result

        # Process root candidates
        for name in root_candidates:
            schema = process_struct(name)
            if schema:
                processed.add(name)
                collections.append(schema)

        return collections

    def _find_collection_name(self, struct_name: str, collection_names: Dict, file_path: str) -> str:
        """Find the MongoDB collection name for a struct."""
        # Check if there's a matching constant
        for const_name, const_value in collection_names.items():
            if const_value and struct_name.lower().replace("do", "") in const_name.lower():
                return const_value

        # Heuristic: remove DO suffix and convert to snake_case
        name = struct_name
        if name.endswith("DO"):
            name = name[:-2]

        # Convert CamelCase to snake_case
        snake = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
        return snake

    def _extract_field_info(self, field: Dict, struct_map: Dict, depth: int) -> Optional[Dict]:
        """Extract database field information from a struct field."""
        field_names = field.get("names", [])
        field_type = field.get("type", "")
        tags = field.get("tags", {})

        if not field_names:
            return None

        bson_key = tags.get("bson", "")
        json_key = tags.get("json", "")
        required = tags.get("required", "").lower() == "true"

        # Determine the database column/field name
        db_name = ""
        if bson_key:
            # bson:"field_name" or bson:"field_name,omitempty"
            db_name = bson_key.split(",")[0]
        elif field_names:
            db_name = field_names[0]

        if not db_name or db_name == "-":
            return None

        # Determine Go type and DB type
        go_type = field_type
        db_type = self._go_type_to_db_type(go_type)
        is_array = go_type.startswith("[]")

        # Check if this is a nested struct reference
        base_type = go_type.lstrip("[]")
        is_nested = base_type in struct_map

        field_info = {
            "db_name": db_name,
            "go_name": field_names[0],
            "go_type": go_type,
            "db_type": db_type,
            "required": required,
            "is_array": is_array,
            "is_nested": is_nested,
        }

        # Recursively process nested structs
        if is_nested and depth < 3:
            nested_schema = self._extract_nested_schema(base_type, struct_map, depth + 1)
            if nested_schema:
                field_info["nested_schema"] = nested_schema

        return field_info

    def _extract_nested_schema(self, struct_name: str, struct_map: Dict, depth: int) -> Optional[Dict]:
        """Extract schema for a nested struct."""
        struct = struct_map.get(struct_name)
        if not struct:
            return None

        fields = []
        for field in struct["fields"]:
            field_info = self._extract_field_info(field, struct_map, depth)
            if field_info:
                fields.append(field_info)

        return {
            "name": struct_name,
            "fields": fields,
        }

    def _go_type_to_db_type(self, go_type: str) -> str:
        """Map Go types to database types."""
        # Remove pointer and slice prefixes
        base = go_type.lstrip("*").lstrip("[]")

        type_map = {
            "string": "string",
            "int": "int64",
            "int64": "int64",
            "int32": "int32",
            "bool": "boolean",
            "float64": "double",
            "float32": "float",
            "time.Time": "datetime",
            "primitive.ObjectID": "ObjectId",
            "uuid.UUID": "uuid",
        }

        return type_map.get(base, base)

    def _generate_mongodb_ddl(self, collections: List[Dict]) -> str:
        """Generate MongoDB collection documentation from schema data."""
        lines = []
        for coll in collections:
            coll_name = coll.get("collection_name", coll["name"])
            lines.append(f"=== Collection: {coll_name} ===")
            lines.append(f"File: {coll.get('file', '')}")
            lines.append("")
            self._format_fields_recursive(coll["fields"], lines, indent=0)
            lines.append("")
        return "\n".join(lines)

    def _format_fields_recursive(self, fields: List[Dict], lines: List[str], indent: int = 0):
        """Format fields recursively with indentation."""
        prefix = "  " * indent
        for f in fields:
            req = " **required**" if f.get("required") else ""
            arr = "[]" if f.get("is_array") else ""
            db_name = f["db_name"]
            db_type = f["db_type"]
            go_name = f.get("go_name", "")
            comment = f"  // Go: {go_name}" if go_name and go_name != db_name else ""

            lines.append(f"{prefix}{db_name}: {arr}{db_type}{req}{comment}")

            # Nested schema
            if f.get("nested_schema"):
                nested = f["nested_schema"]
                lines.append(f"{prefix}  {{  // embedded {nested.get('name', '')}")
                self._format_fields_recursive(nested.get("fields", []), lines, indent + 2)
                lines.append(f"{prefix}  }}")

    # ─── PostgreSQL Schema Extraction ─────────────────────────────────────

    def _extract_postgresql_schemas(self, ast_data: List[Dict]) -> List[Dict]:
        """Extract PostgreSQL table schemas from Go structs with gorm tags.

        Identifies:
        - Structs with gorm tags (GORM models)
        - Table names from gorm:"table:xxx" or TableName() method
        - Column names from gorm:"column:xxx"
        - Types from gorm:"type:xxx"
        """
        # Phase 1: Find structs with gorm tags
        gorm_models = []
        for f in ast_data:
            file_path = f.get("path", "")
            for m in f.get("models", []):
                if m.get("type") == "struct" and m.get("name"):
                    name = m["name"]
                    fields = m.get("fields", [])
                    has_gorm = any(
                        "gorm" in f.get("tags", {})
                        for f in fields
                    )
                    if has_gorm:
                        gorm_models.append({
                            "name": name,
                            "fields": fields,
                            "file": file_path,
                        })

        # Phase 2: Extract table schemas
        tables = []
        for model in gorm_models:
            table_schema = self._extract_table_schema(model)
            if table_schema:
                tables.append(table_schema)

        return tables

    def _extract_table_schema(self, model: Dict) -> Optional[Dict]:
        """Extract a PostgreSQL table schema from a GORM model struct."""
        model_name = model["name"]
        fields = model["fields"]
        columns = []

        for field in fields:
            field_names = field.get("names", [])
            gorm_tag = field.get("tags", {}).get("gorm", "")
            go_type = field.get("type", "")

            if not field_names or not gorm_tag:
                continue

            # Parse gorm tag
            col_info = self._parse_gorm_tag(gorm_tag, field_names[0], go_type)
            columns.append(col_info)

        if not columns:
            return None

        # Determine table name
        table_name = self._infer_table_name(model_name, columns)

        return {
            "table_name": table_name,
            "model_name": model_name,
            "model_file": model["file"],
            "columns": columns,
            "column_count": len(columns),
        }

    def _parse_gorm_tag(self, gorm_tag: str, go_name: str, go_type: str) -> Dict:
        """Parse a GORM tag into column information.

        Examples:
          gorm:"column:uuid;type:uuid" → {name: "uuid", type: "uuid", ...}
          gorm:"column:software_pkg_id" → {name: "software_pkg_id", type: "varchar", ...}
          gorm:"column:created_at" → {name: "created_at", type: "bigint", ...}
        """
        parts = gorm_tag.split(";")
        col_info = {
            "go_name": go_name,
            "column_name": go_name,
            "db_type": self._go_type_to_sql_type(go_type),
            "primary_key": False,
            "not_null": False,
            "unique": False,
            "default": None,
        }

        for part in parts:
            part = part.strip()
            if part.startswith("column:"):
                col_info["column_name"] = part[7:]
            elif part.startswith("type:"):
                col_info["db_type"] = part[5:]
            elif part.lower() == "primarykey" or part.lower() == "primary_key":
                col_info["primary_key"] = True
            elif part.lower() == "notnull" or part.lower() == "not_null":
                col_info["not_null"] = True
            elif part.lower() == "unique":
                col_info["unique"] = True
            elif part.startswith("default:"):
                col_info["default"] = part[8:]
            elif part.lower() == "autoincrement":
                col_info["auto_increment"] = True

        # Special case: if column name is "uuid" and type is uuid, it's a PK
        if col_info["column_name"] == "uuid" and col_info["db_type"] == "uuid":
            col_info["primary_key"] = True

        return col_info

    def _go_type_to_sql_type(self, go_type: str) -> str:
        """Map Go types to PostgreSQL types."""
        base = go_type.lstrip("*").lstrip("[]")

        type_map = {
            "string": "varchar(255)",
            "int": "integer",
            "int8": "smallint",
            "int16": "smallint",
            "int32": "integer",
            "int64": "bigint",
            "uint": "integer",
            "uint32": "integer",
            "uint64": "bigint",
            "bool": "boolean",
            "float32": "real",
            "float64": "double precision",
            "time.Time": "timestamp",
            "uuid.UUID": "uuid",
        }

        return type_map.get(base, "text")

    def _infer_table_name(self, model_name: str, columns: List[Dict]) -> str:
        """Infer the table name from the model or columns."""
        # Check if any column is explicitly the table name
        # GORM convention: TableName() method or gorm:"table:xxx"
        # Heuristic: remove DO suffix and convert to snake_case
        name = model_name
        if name.endswith("DO"):
            name = name[:-2]

        # Convert CamelCase to snake_case
        snake = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
        return snake

    def _generate_postgresql_ddl(self, tables: List[Dict]) -> str:
        """Generate SQL CREATE TABLE statements from schema data."""
        lines = []
        for table in tables:
            table_name = table["table_name"]
            columns = table["columns"]

            lines.append(f"-- Table: {table_name}")
            lines.append(f"-- Model: {table['model_name']} ({table['model_file']})")
            lines.append(f"CREATE TABLE IF NOT EXISTS {table_name} (")

            col_lines = []
            pk_cols = []
            for col in columns:
                col_def = f"    {col['column_name']} {col['db_type']}"
                if col.get("not_null"):
                    col_def += " NOT NULL"
                if col.get("default") is not None:
                    col_def += f" DEFAULT {col['default']}"
                if col.get("unique"):
                    col_def += " UNIQUE"
                if col.get("auto_increment"):
                    col_def += " AUTO_INCREMENT"
                if col.get("primary_key"):
                    pk_cols.append(col["column_name"])

                col_lines.append(col_def)

            # Add primary key constraint
            if pk_cols:
                col_lines.append(f"    PRIMARY KEY ({', '.join(pk_cols)})")

            lines.append(",\n".join(col_lines))
            lines.append(");\n")

        return "\n".join(lines)

    def _generate_full_schema_report(self, collections: List[Dict], tables: List[Dict]) -> str:
        """Generate a complete database schema report."""
        lines = ["# Database Schema Report\n"]

        # MongoDB section
        if collections:
            lines.append("## MongoDB Collections\n")
            for coll in collections:
                coll_name = coll.get("collection_name", coll["name"])
                lines.append(f"### `{coll_name}`\n")
                lines.append(f"Source: `{coll.get('file', '')}`\n")
                lines.append("```")
                self._format_fields_recursive(coll["fields"], lines, indent=0)
                lines.append("```\n")

        # PostgreSQL section
        if tables:
            lines.append("## PostgreSQL Tables\n")
            lines.append("```sql")
            lines.append(self._generate_postgresql_ddl(tables))
            lines.append("```\n")

        return "\n".join(lines)
