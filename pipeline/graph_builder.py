"""
Builds the multi-layer Repository Knowledge Graph from parser results and static analysis.

Layer 1 (structural)  : file -> class -> function containment, imports, inheritance.
                         Confidence = "structural_certain" for direct AST facts,
                         or "low_confidence" / "flagged" for cross-file / ambiguous class bases.

Layer 2 (call graph)  : best-effort resolution of `calls` (raw text captured
                         during parsing) to an actual FunctionNode id.

Layer 3 (cross-module): file -> file module dependencies (`depends_on`).

Layer 4 (findings)    : file / function -> static analysis findings (`has_finding`).
"""
from __future__ import annotations
import os
from collections import defaultdict
import networkx as nx


def _normalize_path(p: str) -> str:
    """Normalize file path to forward slashes and relative path representation."""
    return p.replace("\\", "/").lstrip("./")


def _resolve_base_class(
    base_name: str,
    file_path: str,
    same_file_classes: dict[str, dict[str, list[str]]],
    repo_classes: dict[str, list[str]]
) -> tuple[str, str]:
    """
    Resolve base class name to target node ID and confidence level.
    Returns (target_node_id, confidence).
    """
    bare_name = base_name.split(".")[-1]

    # 1. Same-file match
    same_file_ids = same_file_classes.get(file_path, {}).get(bare_name, [])
    if len(same_file_ids) == 1:
        return same_file_ids[0], "structural_certain"
    elif len(same_file_ids) > 1:
        return f"ambiguous_class::{bare_name}", "flagged"

    # 2. Repo-wide match
    repo_ids = repo_classes.get(bare_name, [])
    if len(repo_ids) == 1:
        return repo_ids[0], "low_confidence"
    elif len(repo_ids) > 1:
        return f"ambiguous_class::{bare_name}", "flagged"

    # 3. External / framework base target
    return f"class_target::{base_name}", "structural_certain"


def build_graph(parse_results: list, static_analysis: dict | None = None) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()

    all_functions = {}        # func_id -> FunctionNode
    all_classes = {}          # cls_id -> ClassNode
    class_name_index = {}     # bare class name -> list of cls_ids (repo-wide)
    same_file_class_index = defaultdict(lambda: defaultdict(list)) # file -> bare class name -> list of cls_ids
    func_name_index = {}      # bare function name -> list of func_ids (repo-wide)
    file_import_names = {}   # file -> set of bare names bound by imports in that file
    file_set = set()          # set of all parsed file relative paths
    file_module_map = {}      # module key -> file_path

    # Track files in repo for module dependency resolution
    for fr in parse_results:
        norm_file = _normalize_path(fr.file)
        file_set.add(norm_file)
        stem, ext = os.path.splitext(norm_file)
        dotted = stem.replace("/", ".")
        file_module_map[dotted] = norm_file
        file_module_map[stem] = norm_file
        file_module_map[os.path.basename(stem)] = norm_file

    # --- Layer 1: structural nodes + containment/import edges ---
    for fr in parse_results:
        norm_file = _normalize_path(fr.file)
        if fr.parse_error:
            g.add_node(norm_file, type="file", parse_error=fr.parse_error, provenance="filesystem-walk")
            continue

        g.add_node(norm_file, type="file", provenance="filesystem-walk")
        file_import_names[norm_file] = set()

        for cls in fr.classes:
            g.add_node(cls.id, type="class", name=cls.name, file=cls.file,
                       start_line=cls.start_line, end_line=cls.end_line,
                       bases=cls.bases, provenance=cls.provenance)
            g.add_edge(norm_file, cls.id, relation="contains", confidence="structural_certain",
                       provenance=cls.provenance)
            all_classes[cls.id] = cls
            class_name_index.setdefault(cls.name, []).append(cls.id)
            same_file_class_index[norm_file][cls.name].append(cls.id)

        for fn in fr.functions:
            g.add_node(fn.id, type="function", name=fn.name, file=fn.file,
                       start_line=fn.start_line, end_line=fn.end_line,
                       class_owner=fn.class_owner, provenance=fn.provenance)
            owner = None
            if fn.class_owner:
                for cls in fr.classes:
                    if cls.name == fn.class_owner:
                        owner = cls.id
                        break
            parent = owner or norm_file
            g.add_edge(parent, fn.id, relation="contains", confidence="structural_certain",
                       provenance=fn.provenance)

            all_functions[fn.id] = fn
            func_name_index.setdefault(fn.name, []).append(fn.id)

        for imp in fr.imports:
            import_node_id = f"import::{imp.imported}"
            g.add_node(import_node_id, type="import_target", name=imp.imported, provenance="external/unresolved")
            g.add_edge(norm_file, import_node_id, relation="imports", confidence="structural_certain",
                       line=imp.line, alias=imp.alias, provenance=imp.provenance)
            bound_name = imp.alias or imp.imported.split(".")[-1]
            file_import_names[norm_file].add(bound_name)

    # --- Layer 1b: Inheritance Edges ---
    for cls in all_classes.values():
        norm_file = _normalize_path(cls.file)
        for base in cls.bases:
            if not base:
                continue
            target_id, confidence = _resolve_base_class(base, norm_file, same_file_class_index, class_name_index)
            if target_id.startswith("class_target::") and not g.has_node(target_id):
                g.add_node(target_id, type="class_target", name=base, provenance="external/unresolved")
            g.add_edge(cls.id, target_id, relation="inherits", confidence=confidence,
                       base_name=base, provenance=cls.provenance)

    # --- Layer 2: Cross-File Module Dependencies (depends_on) ---
    for fr in parse_results:
        norm_file = _normalize_path(fr.file)
        if fr.parse_error:
            continue

        for imp in fr.imports:
            imp_str = imp.imported.strip()
            if not imp_str:
                continue

            target_file = None
            confidence = "structural_certain"

            # 1. Exact path match or dotted match
            if imp_str in file_set and imp_str != norm_file:
                target_file = imp_str
            else:
                dotted_path = imp_str.replace(".", "/")
                for ext in (".py", ".js", ".ts", ".jsx", ".tsx", ".java", "/index.js", "/index.ts"):
                    cand = _normalize_path(dotted_path + ext)
                    if cand in file_set and cand != norm_file:
                        target_file = cand
                        break

            # 2. Relative JS/TS import match (e.g. "./utils")
            if not target_file and (imp_str.startswith("./") or imp_str.startswith("../")):
                dir_name = os.path.dirname(norm_file)
                rel_base = _normalize_path(os.path.normpath(os.path.join(dir_name, imp_str)))
                for ext in ("", ".js", ".ts", ".jsx", ".tsx", "/index.js", "/index.ts"):
                    cand = _normalize_path(rel_base + ext)
                    if cand in file_set and cand != norm_file:
                        target_file = cand
                        confidence = "structural_certain"
                        break

            # 3. Dotted module map or bare name lookup
            if not target_file:
                mapped = file_module_map.get(imp_str)
                if mapped and mapped != norm_file:
                    target_file = mapped
                    confidence = "high_confidence"

            if target_file and target_file != norm_file:
                g.add_edge(norm_file, target_file, relation="depends_on", confidence=confidence,
                           imported_module=imp_str, provenance="graph_builder:module_dependency_resolver")

    # --- Layer 3: Best-effort call resolution ---
    same_file_func_index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for f in all_functions.values():
        same_file_func_index[_normalize_path(f.file)][f.name].append(f.id)

    for fn_id, fn in all_functions.items():
        norm_file = _normalize_path(fn.file)
        for raw_call in fn.calls:
            bare_name = raw_call.split(".")[-1]
            is_attribute_call = "." in raw_call

            same_file_matches = [fid for fid in same_file_func_index[norm_file].get(bare_name, []) if fid != fn_id]
            all_matches = func_name_index.get(bare_name, [])

            if is_attribute_call:
                g.add_edge(fn_id, f"unresolved_call::{raw_call}", relation="calls",
                           confidence="flagged", reason="attribute_call_unknown_receiver_type",
                           raw_call=raw_call, provenance="graph_builder:call_resolution_heuristic")
                continue

            name_also_imported = bare_name in file_import_names.get(norm_file, set())

            if len(same_file_matches) > 1:
                g.add_edge(fn_id, f"ambiguous_call::{bare_name}", relation="calls",
                           confidence="flagged", reason="duplicate_same_file_candidates",
                           raw_call=raw_call, provenance="graph_builder:call_resolution_heuristic")
            elif len(same_file_matches) == 1 and not name_also_imported:
                g.add_edge(fn_id, same_file_matches[0], relation="calls", confidence="high_confidence",
                           raw_call=raw_call, provenance="graph_builder:call_resolution_heuristic")
            elif len(same_file_matches) == 1 and name_also_imported:
                g.add_edge(fn_id, f"ambiguous_call::{bare_name}", relation="calls",
                           confidence="flagged", reason="name_collides_with_local_import",
                           raw_call=raw_call, provenance="graph_builder:call_resolution_heuristic")
            elif len(all_matches) == 1 and all_matches[0] != fn_id:
                g.add_edge(fn_id, all_matches[0], relation="calls", confidence="low_confidence",
                           raw_call=raw_call, provenance="graph_builder:call_resolution_heuristic")
            elif len(all_matches) > 1:
                g.add_edge(fn_id, f"ambiguous_call::{bare_name}", relation="calls",
                           confidence="flagged", reason=f"{len(all_matches)}_candidate_definitions",
                           raw_call=raw_call, provenance="graph_builder:call_resolution_heuristic")
            else:
                g.add_edge(fn_id, f"unresolved_call::{raw_call}", relation="calls",
                           confidence="flagged", reason="no_matching_definition_found",
                           raw_call=raw_call, provenance="graph_builder:call_resolution_heuristic")

    # --- Layer 4: Static Analysis Finding Edges (has_finding) ---
    if static_analysis:
        findings_to_process = []

        # 1. Bandit security findings
        sec_results = static_analysis.get("security", {}).get("results", [])
        if isinstance(sec_results, list):
            for item in sec_results:
                if isinstance(item, dict):
                    findings_to_process.append({
                        "analyzer": "bandit",
                        "file": item.get("filename") or item.get("file", ""),
                        "line": item.get("line_number") or item.get("line", 0),
                        "rule_id": item.get("test_id") or item.get("rule_id", "security_finding"),
                        "severity": item.get("issue_severity") or item.get("severity", "MEDIUM"),
                        "message": item.get("issue_text") or item.get("message", ""),
                    })

        # 2. Semgrep findings
        semgrep_res = static_analysis.get("semgrep_findings", {}).get("results", [])
        if isinstance(semgrep_res, list):
            for item in semgrep_res:
                if isinstance(item, dict):
                    findings_to_process.append({
                        "analyzer": "semgrep",
                        "file": item.get("file", ""),
                        "line": item.get("line", 0),
                        "rule_id": item.get("rule_id", "semgrep_rule"),
                        "severity": item.get("severity", "WARNING"),
                        "message": item.get("message", ""),
                    })

        # 3. Gitleaks findings
        gitleaks_res = static_analysis.get("gitleaks_findings", {}).get("results", [])
        if isinstance(gitleaks_res, list):
            for item in gitleaks_res:
                if isinstance(item, dict):
                    findings_to_process.append({
                        "analyzer": "gitleaks",
                        "file": item.get("file", ""),
                        "line": item.get("line", 0),
                        "rule_id": item.get("rule_id", "secret_leak"),
                        "severity": item.get("severity", "HIGH"),
                        "message": item.get("message", ""),
                    })

        # 4. OSV vulnerabilities
        osv_res = static_analysis.get("osv_vulnerabilities", {}).get("results", [])
        if isinstance(osv_res, list):
            for item in osv_res:
                if isinstance(item, dict):
                    findings_to_process.append({
                        "analyzer": "osv",
                        "file": item.get("file", "requirements.txt"),
                        "line": item.get("line", 0),
                        "rule_id": item.get("cve") or item.get("package", "vulnerability"),
                        "severity": item.get("severity", "CRITICAL"),
                        "message": f"Vulnerability in {item.get('package', '')} version {item.get('version', '')}",
                    })

        for idx, f in enumerate(findings_to_process):
            file_rel = _normalize_path(f["file"])
            if not file_rel:
                continue

            finding_id = f"finding::{f['analyzer']}::{f['rule_id']}::{file_rel}:{f['line']}::{idx}"
            g.add_node(
                finding_id,
                type="finding",
                analyzer=f["analyzer"],
                rule_id=f["rule_id"],
                severity=f["severity"],
                message=f["message"],
                file=file_rel,
                line=f["line"],
                provenance=f["analyzer"]
            )

            if not g.has_node(file_rel):
                g.add_node(file_rel, type="file", provenance="filesystem-walk")
            g.add_edge(file_rel, finding_id, relation="has_finding", confidence="structural_certain",
                       provenance=f["analyzer"])

            f_line = f["line"]
            if f_line > 0:
                for fn in all_functions.values():
                    if _normalize_path(fn.file) == file_rel and fn.start_line <= f_line <= fn.end_line:
                        g.add_edge(fn.id, finding_id, relation="has_finding", confidence="structural_certain",
                                   provenance=f["analyzer"])

    return g


def graph_summary(g: nx.MultiDiGraph) -> dict:
    """Confidence breakdown of call edges and summary of expanded graph relations."""
    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls"]
    inherits_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "inherits"]
    depends_on_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "depends_on"]
    finding_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "has_finding"]
    finding_nodes = [n for n, d in g.nodes(data=True) if d.get("type") == "finding"]

    breakdown = {"high_confidence": 0, "low_confidence": 0, "flagged": 0}
    for _, _, d in call_edges:
        breakdown[d.get("confidence", "flagged")] += 1
    total = len(call_edges) or 1
    return {
        "total_nodes": g.number_of_nodes(),
        "total_edges": g.number_of_edges(),
        "call_edges_total": len(call_edges),
        "call_edges_by_confidence": breakdown,
        "call_edges_resolved_pct": round(100 * (breakdown["high_confidence"] + breakdown["low_confidence"]) / total, 1),
        "inherits_edges_total": len(inherits_edges),
        "depends_on_edges_total": len(depends_on_edges),
        "has_finding_edges_total": len(finding_edges),
        "finding_nodes_total": len(finding_nodes),
        "resolution_caveat": "high_confidence/low_confidence are name-matching heuristics, "
                              "not verified Python scope resolution -- see graph_builder.py docstring.",
    }

