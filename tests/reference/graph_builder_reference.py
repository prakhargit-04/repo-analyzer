"""
Reference implementation of Graph Builder (pre-refactor baseline).
Used as oracle for differential testing against pipeline.graph_builder.
"""
from __future__ import annotations
import os
from collections import defaultdict
import networkx as nx


def _normalize_path(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")


def _resolve_base_class(
    base_name: str,
    file_path: str,
    same_file_classes: dict[str, dict[str, list[str]]],
    repo_classes: dict[str, list[str]]
) -> tuple[str, str]:
    bare_name = base_name.split(".")[-1]

    same_file_ids = same_file_classes.get(file_path, {}).get(bare_name, [])
    if len(same_file_ids) == 1:
        return same_file_ids[0], "structural_certain"
    elif len(same_file_ids) > 1:
        return f"ambiguous_class::{bare_name}", "flagged"

    repo_ids = repo_classes.get(bare_name, [])
    if len(repo_ids) == 1:
        return repo_ids[0], "low_confidence"
    elif len(repo_ids) > 1:
        return f"ambiguous_class::{bare_name}", "flagged"

    return f"class_target::{base_name}", "structural_certain"


def build_graph_reference(parse_results: list, static_analysis: dict | None = None) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()

    all_functions = {}
    all_classes = {}
    class_name_index = {}
    same_file_class_index = defaultdict(lambda: defaultdict(list))
    func_name_index = {}
    file_import_names = {}
    file_set = set()
    file_module_map = {}

    for fr in parse_results:
        norm_file = _normalize_path(fr.file)
        file_set.add(norm_file)
        stem, ext = os.path.splitext(norm_file)
        dotted = stem.replace("/", ".")
        file_module_map[dotted] = norm_file
        file_module_map[stem] = norm_file
        file_module_map[os.path.basename(stem)] = norm_file

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

            if imp_str in file_set and imp_str != norm_file:
                target_file = imp_str
            else:
                dotted_path = imp_str.replace(".", "/")
                for ext in (".py", ".js", ".ts", ".jsx", ".tsx", ".java", "/index.js", "/index.ts"):
                    cand = _normalize_path(dotted_path + ext)
                    if cand in file_set and cand != norm_file:
                        target_file = cand
                        break

            if not target_file and (imp_str.startswith("./") or imp_str.startswith("../")):
                dir_name = os.path.dirname(norm_file)
                rel_base = _normalize_path(os.path.normpath(os.path.join(dir_name, imp_str)))
                for ext in ("", ".js", ".ts", ".jsx", ".tsx", "/index.js", "/index.ts"):
                    cand = _normalize_path(rel_base + ext)
                    if cand in file_set and cand != norm_file:
                        target_file = cand
                        confidence = "structural_certain"
                        break

            if not target_file:
                parts = imp_str.rsplit(".", 1)
                mod_cand = parts[0] if len(parts) > 1 else imp_str
                mapped = file_module_map.get(imp_str) or file_module_map.get(mod_cand)
                if mapped and mapped != norm_file:
                    target_file = mapped
                    confidence = "high_confidence"

            if target_file and target_file != norm_file:
                g.add_edge(norm_file, target_file, relation="depends_on", confidence=confidence,
                           imported_module=imp_str, provenance="graph_builder:module_dependency_resolver")

    file_imports_map = defaultdict(dict)
    file_depends_on_map = defaultdict(dict)

    for u, v, d in g.edges(data=True):
        if d.get("relation") == "depends_on":
            file_depends_on_map[u][d.get("imported_module", "")] = v

    for fr in parse_results:
        norm_file = _normalize_path(fr.file)
        for imp in fr.imports:
            bound_name = imp.alias or imp.imported.split(".")[-1]
            file_imports_map[norm_file][bound_name] = imp
            if imp.alias:
                file_imports_map[norm_file][imp.imported] = imp

    class_parents_map = defaultdict(list)
    for u, v, d in g.edges(data=True):
        if d.get("relation") == "inherits":
            class_parents_map[u].append(v)

    def _resolve_call_target(fn, raw_call: str) -> tuple[str, str] | None:
        call_str = raw_call.strip()
        if not call_str:
            return None

        caller_file = _normalize_path(fn.file)

        if call_str.startswith("self."):
            method_name = call_str[5:].strip()
            if fn.class_owner:
                owner_id = f"{caller_file}::{fn.class_owner}"
                target_id = f"{caller_file}::{fn.class_owner}::{method_name}"
                if target_id in all_functions:
                    return target_id, "structural_certain"
                visited = set()
                queue = list(class_parents_map.get(owner_id, []))
                while queue:
                    curr_cls_id = queue.pop(0)
                    if curr_cls_id in visited:
                        continue
                    visited.add(curr_cls_id)
                    parent_fn_id = f"{curr_cls_id}::{method_name}"
                    if parent_fn_id in all_functions:
                        return parent_fn_id, "high_confidence"
                    queue.extend(class_parents_map.get(curr_cls_id, []))

        if call_str.startswith("super()."):
            method_name = call_str[8:].strip()
            if fn.class_owner:
                owner_id = f"{caller_file}::{fn.class_owner}"
                visited = set()
                queue = list(class_parents_map.get(owner_id, []))
                while queue:
                    curr_cls_id = queue.pop(0)
                    if curr_cls_id in visited:
                        continue
                    visited.add(curr_cls_id)
                    parent_fn_id = f"{curr_cls_id}::{method_name}"
                    if parent_fn_id in all_functions:
                        return parent_fn_id, "structural_certain"
                    queue.extend(class_parents_map.get(curr_cls_id, []))

        if "." in call_str and not call_str.startswith(("self.", "super().")):
            mod_prefix, func_name = call_str.rsplit(".", 1)
            target_file = file_depends_on_map.get(caller_file, {}).get(mod_prefix)
            if target_file:
                target_id = f"{target_file}::{func_name}"
                if target_id in all_functions:
                    return target_id, "high_confidence"
                target_cls_fn = f"{target_file}::{mod_prefix}::{func_name}"
                if target_cls_fn in all_functions:
                    return target_cls_fn, "high_confidence"

        same_file_matches = [
            fid for fid in func_name_index.get(call_str, [])
            if _normalize_path(all_functions[fid].file) == caller_file
        ]
        if len(same_file_matches) == 1:
            return same_file_matches[0], "structural_certain"
        elif len(same_file_matches) > 1:
            return None

        if call_str in file_import_names.get(caller_file, set()):
            imported_matches = [
                fid for fid in func_name_index.get(call_str, [])
                if fid in all_functions
            ]
            if len(imported_matches) == 1:
                return imported_matches[0], "high_confidence"

        repo_matches = func_name_index.get(call_str, [])
        if len(repo_matches) == 1:
            return repo_matches[0], "low_confidence"

        return None

    for fn in all_functions.values():
        for raw_call in fn.calls:
            res = _resolve_call_target(fn, raw_call)
            if res:
                target_id, confidence = res
                g.add_edge(fn.id, target_id, relation="calls", confidence=confidence,
                           raw_call=raw_call, provenance="graph_builder:call_resolution_engine")

    if static_analysis:
        for finder_name in ("bandit_findings", "semgrep_findings", "gitleaks_findings", "osv_vulnerabilities"):
            result_obj = static_analysis.get(finder_name, {})
            findings_list = result_obj.get("results", []) if isinstance(result_obj, dict) else []
            for i, f in enumerate(findings_list):
                finding_id = f"finding::{finder_name}::{f.get('file', '')}::{f.get('line', 0)}::{i}"
                g.add_node(finding_id, type="finding", analyzer=finder_name,
                           severity=f.get("severity", "MEDIUM"), rule_id=f.get("rule_id", "unknown"),
                           message=f.get("message", ""), provenance=f.get("provenance", finder_name))
                file_target = _normalize_path(f.get("file", ""))
                if file_target in file_set:
                    g.add_edge(file_target, finding_id, relation="has_finding", confidence="structural_certain",
                               provenance=finder_name)

    return g
