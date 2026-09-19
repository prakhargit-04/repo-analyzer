# Canonical Analysis Output Schema Specification

**Schema Version:** `1.0.0`  
**Cache Schema Version:** `v4`  
**Analyzer Version:** `0.2.0`  

This document defines the frozen, canonical analysis output schema for GitHub Project Analyzer. Any future analyzer additions (e.g., Lizard, Semgrep, Gitleaks, OSV, Java/JS/TS parsers) MUST emit data adhering strictly to this schema contract.

---

## 1. Top-Level Structure

A valid analysis output document is a JSON object containing the following key sections:

```json
{
  "schema_version": "1.0.0",
  "cache_schema_version": "v4",
  "analyzer_version": "0.2.0",
  "repository": "https://github.com/owner/repo",
  "commit_sha": "00e7d87c7353b1ffecc4cd55f19acfffedd5233e",
  "cache_snapshot_id": "00e7d87c7353b1ffecc4cd55f19acfffedd5233e",
  "cache_key_basis": "git_sha (fresh clone, trusted)",
  "analyzed_at_utc": "2026-09-19T10:18:10.402639+00:00",
  "languages": ["python"],
  "analysis_status": "complete",
  "files_analyzed": 5,
  "parse_errors": [],
  "static_analysis": { ... },
  "knowledge_graph_summary": { ... },
  "knowledge_graph": { ... },
  "health_score": { ... }
}
```

### Field Definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | String | Yes | Canonical schema contract version (`"1.0.0"`). |
| `cache_schema_version` | String | Yes | Cache invalidation schema key version (`"v4"`). |
| `analyzer_version` | String | Yes | Analyzer engine version (`"0.2.0"`). |
| `repository` | String | Yes | Git repository URL or local file path analyzed. |
| `commit_sha` | String | Yes | Git commit SHA or `"not-a-git-repo"`. |
| `cache_snapshot_id` | String | Yes | Git SHA or content-sha256 snapshot identifier. |
| `cache_key_basis` | String | Yes | Provenance label of snapshot key derivation. |
| `analyzed_at_utc` | String | Yes | ISO 8601 UTC timestamp of analysis run. |
| `languages` | List[String] | Yes | List of programming languages present/analyzed (e.g. `["python"]`). |
| `analysis_status` | String | Yes | Overall status: `"complete"`, `"partial"`, or `"failed"`. |
| `files_analyzed` | Integer | Yes | Count of all source files parsed. |
| `parse_errors` | List[Object] | Yes | List of parse errors: `[{"file": string, "error": string}]`. |
| `static_analysis` | Object | Yes | Static analysis tool execution results & findings. |
| `knowledge_graph_summary` | Object | Yes | Structural and call graph resolution summary metrics. |
| `knowledge_graph` | Object | Yes | Multi-layer knowledge graph nodes and edges. |
| `health_score` | Object | Yes | Composite health score formula, sub-scores, and component statuses. |

---

## 2. Tool Analysis Status Contract

Every tool component within `static_analysis` (`complexity`, `maintainability`, `security`, etc.) MUST report a valid `status` string.

### Status Enum Values

1. `"success"`: Tool completed cleanly and output is complete.
2. `"partial"`: Tool completed partially (e.g., some individual files failed/timed out, but available results were collected).
3. `"failed"`: Tool crashed, timed out, returned non-zero error exit code, or produced unparsable stdout.
4. `"unsupported"`: Language or repository structure is not supported by this tool in the current version.
5. `"unavailable"`: Tool is documented/configured but disabled or binary is not installed in environment.

### Status Derivation Rules

- Overall `analysis_status` is `"complete"` **only if every active tool component is `"success"`**.
- Overall `analysis_status` is `"failed"` **only if all components failed or produced zero data**.
- Overall `analysis_status` is `"partial"` for any intermediate state.

---

## 3. Static Analysis Schema (`static_analysis`)

```json
{
  "scope_policy": "production_code_only",
  "production_files_analyzed": 3,
  "test_files_excluded": 2,
  "complexity": {
    "status": "success",
    "results": [
      {
        "file": "src/iniconfig/_parse.py",
        "function": "parse_ini_data",
        "line": 16,
        "cyclomatic_complexity": 7,
        "rank": "B",
        "provenance": "radon:6.0.1:cc_visit"
      }
    ]
  },
  "maintainability": {
    "status": "success",
    "results": [
      {
        "file": "src/iniconfig/exceptions.py",
        "maintainability_index": 69.2,
        "provenance": "radon:6.0.1:mi_visit"
      }
    ]
  },
  "security": {
    "status": "success",
    "results": [
      {
        "file": "src/iniconfig/_parse.py",
        "line": 42,
        "issue_text": "Possible hardcoded password",
        "severity": "HIGH",
        "confidence": "MEDIUM",
        "test_id": "B105",
        "provenance": "bandit:1.9.4"
      }
    ]
  }
}
```

---

## 4. Knowledge Graph Schema (`knowledge_graph`)

### Nodes (`knowledge_graph.nodes`)

Every node carries `id`, `type`, and `provenance`:

- **File Node:** `{"id": "rel/path.py", "type": "file", "provenance": "filesystem-walk"}`
- **Class Node:** `{"id": "rel/path.py::ClassName:line", "type": "class", "name": "ClassName", "file": "rel/path.py", "start_line": int, "end_line": int, "bases": list[str], "provenance": "tree-sitter-python:AST-walk"}`
- **Function Node:** `{"id": "rel/path.py::func:line", "type": "function", "name": "func", "file": "rel/path.py", "start_line": int, "end_line": int, "class_owner": str|null, "provenance": "tree-sitter-python:AST-walk"}`
- **Import Target Node:** `{"id": "import::module.name", "type": "import_target", "name": "module.name", "provenance": "external/unresolved"}`

### Edges (`knowledge_graph.edges`)

Every edge carries `source`, `target`, `relation`, `confidence`, and `provenance`:

- **Containment Edge:** `{"source": "rel/path.py", "target": "rel/path.py::func:10", "relation": "contains", "confidence": "structural_certain", "provenance": "tree-sitter-python:AST-walk"}`
- **Import Edge:** `{"source": "rel/path.py", "target": "import::os.path", "relation": "imports", "confidence": "structural_certain", "line": 1, "alias": null, "provenance": "tree-sitter-python:AST-walk"}`
- **Call Edge:** `{"source": "func_a_id", "target": "func_b_id", "relation": "calls", "confidence": "high_confidence"|"low_confidence"|"flagged", "raw_call": "func_b", "provenance": "graph_builder:call_resolution_heuristic"}`

---

## 5. Health Score Schema (`health_score`)

```json
{
  "composite_health_score": 79.42,
  "status": "complete",
  "sub_scores": {
    "complexity": 81.25,
    "maintainability": 61.67,
    "security": 98.0
  },
  "component_statuses": {
    "complexity": "success",
    "maintainability": "success",
    "security": "success"
  },
  "missing_components": [],
  "weights_used": {
    "complexity": 0.35,
    "maintainability": 0.35,
    "security": 0.3
  },
  "weights_renormalized": false,
  "formula": "weighted average of available sub-scores; weights renormalized to sum to 1 if any component is missing (never treated as 0 or 100)",
  "scope_policy": "production_code_only",
  "note": "..."
}
```

---

## 6. Deterministic Serialization & Ordering Rules

To guarantee reproducible serialization:
1. `parse_results` sorted alphabetically by file path.
2. `parse_errors` sorted by file path.
3. `knowledge_graph.nodes` sorted by node `id`.
4. `knowledge_graph.edges` sorted by `(source, target, relation, raw_call)`.
5. Final JSON formatted via `json.dumps(..., indent=2, sort_keys=True)`.

---

## 7. Versioning & Compatibility Rules

- **SemVer Versioning:** Major version changes (e.g. `2.0.0`) indicate breaking schema structure changes. Minor version changes (e.g. `1.1.0`) indicate additive, non-breaking fields. Patch version changes (e.g. `1.0.1`) indicate non-schema analyzer updates.
- **Cache Invalidation:** Any bump to `CACHE_SCHEMA_VERSION` (currently `"v4"`) invalidates all `.cache/` entries automatically.
