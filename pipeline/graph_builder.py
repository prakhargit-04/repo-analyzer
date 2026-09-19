"""
Builds the two-layer Repository Knowledge Graph from parse_python.py output.

Layer 1 (structural)  : file -> class -> function containment, imports.
                         Confidence = "certain" always -- this is a direct,
                         unambiguous AST fact.

Layer 2 (call graph)  : best-effort resolution of `calls` (raw text captured
                         during parsing) to an actual FunctionNode id.

                         IMPORTANT HONESTY NOTE: this resolver does real
                         name matching, not real Python scope/import
                         resolution. It cannot see local variable
                         shadowing, parameter shadowing, or `del`/rebinding.
                         The confidence labels below are named to reflect
                         that limitation truthfully rather than oversell
                         "certain" for something that is really "no
                         contradicting evidence found by a name-matching
                         heuristic". Structural edges (containment, imports)
                         ARE genuinely certain -- they are direct AST facts
                         with no matching/inference step at all. Call edges
                         never reach that bar in this version.

    "structural_certain" -> (containment/import edges only) direct,
                   unambiguous AST fact, no inference involved.
    "high_confidence"    -> (calls only) exactly one function of this name
                   is defined in the same file (two-or-more same-named
                   functions in the same file are flagged, never picked
                   between), AND no import in that file also binds that
                   same bare name (which would make it genuinely ambiguous
                   which symbol the call resolves to). Still not
                   scope-verified -- a local variable or parameter could
                   theoretically shadow it; not checked.
    "low_confidence"     -> (calls only) exactly one function of this name
                   exists ANYWHERE in the repo (cross-file name match only,
                   weaker evidence than same-file).
    "flagged"     -> 0 or >1 candidate functions, an import-name collision
                   was detected, OR the call is an attribute/method call
                   on an object whose type isn't known (e.g. `self.x.y()`,
                   DI, decorators, dynamic dispatch). Never guessed --
                   recorded as an unresolved/ambiguous edge and surfaced.
"""
from __future__ import annotations
from collections import defaultdict
import networkx as nx


def build_graph(parse_results: list) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()

    all_functions = {}   # func_id -> FunctionNode
    name_index = {}       # bare function name -> list of func_ids (repo-wide)
    file_import_names = {}  # file -> set of bare names bound by imports in that file

    # --- Layer 1: structural nodes + containment/import edges ---
    for fr in parse_results:
        if fr.parse_error:
            g.add_node(fr.file, type="file", parse_error=fr.parse_error, provenance="filesystem-walk")
            continue

        g.add_node(fr.file, type="file", provenance="filesystem-walk")
        file_import_names[fr.file] = set()

        for cls in fr.classes:
            g.add_node(cls.id, type="class", name=cls.name, file=cls.file,
                       start_line=cls.start_line, end_line=cls.end_line,
                       bases=cls.bases, provenance=cls.provenance)
            g.add_edge(fr.file, cls.id, relation="contains", confidence="structural_certain",
                       provenance="tree-sitter-python:AST-walk")

        for fn in fr.functions:
            g.add_node(fn.id, type="function", name=fn.name, file=fn.file,
                       start_line=fn.start_line, end_line=fn.end_line,
                       class_owner=fn.class_owner, provenance=fn.provenance)
            owner = None
            if fn.class_owner:
                # find matching class node id in this file
                for cls in fr.classes:
                    if cls.name == fn.class_owner:
                        owner = cls.id
                        break
            parent = owner or fr.file
            g.add_edge(parent, fn.id, relation="contains", confidence="structural_certain",
                       provenance="tree-sitter-python:AST-walk")

            all_functions[fn.id] = fn
            name_index.setdefault(fn.name, []).append(fn.id)

        for imp in fr.imports:
            import_node_id = f"import::{imp.imported}"
            g.add_node(import_node_id, type="import_target", name=imp.imported, provenance="external/unresolved")
            g.add_edge(fr.file, import_node_id, relation="imports", confidence="structural_certain",
                       line=imp.line, alias=imp.alias, provenance="tree-sitter-python:AST-walk")
            # record the bare name this import binds into the file's namespace,
            # used below to detect same-file-match vs import-name collisions
            bound_name = imp.alias or imp.imported.split(".")[-1]
            file_import_names[fr.file].add(bound_name)

    # --- Layer 2: best-effort call resolution ---
    # Per-file name -> [ids] index, built as a list (never a plain dict) so
    # that two functions sharing a name in the same file are BOTH kept
    # instead of the second silently overwriting the first. A prior version
    # used {f.name: f.id for f in ...}, which meant a call to a duplicated
    # name resolved to whichever function happened to be last in iteration
    # order and was reported "high_confidence" -- confidently wrong.
    same_file_index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for f in all_functions.values():
        same_file_index[f.file][f.name].append(f.id)

    for fn_id, fn in all_functions.items():
        for raw_call in fn.calls:
            # strip to the bare trailing identifier for name matching
            # (e.g. "self.helper" -> "helper", "module.func" -> "func")
            bare_name = raw_call.split(".")[-1]
            is_attribute_call = "." in raw_call

            same_file_matches = [fid for fid in same_file_index[fn.file].get(bare_name, []) if fid != fn_id]
            all_matches = name_index.get(bare_name, [])

            if is_attribute_call:
                # attribute/method calls on unknown-typed objects: never guess
                g.add_edge(fn_id, f"unresolved_call::{raw_call}", relation="calls",
                           confidence="flagged", reason="attribute_call_unknown_receiver_type",
                           raw_call=raw_call, provenance="graph_builder:call_resolution_heuristic")
                continue

            name_also_imported = bare_name in file_import_names.get(fn.file, set())

            if len(same_file_matches) > 1:
                # two-or-more same-named functions in this file -- genuinely
                # ambiguous which one a bare call resolves to; never pick one.
                g.add_edge(fn_id, f"ambiguous_call::{bare_name}", relation="calls",
                           confidence="flagged", reason="duplicate_same_file_candidates",
                           raw_call=raw_call, provenance="graph_builder:call_resolution_heuristic")
            elif len(same_file_matches) == 1 and not name_also_imported:
                g.add_edge(fn_id, same_file_matches[0], relation="calls", confidence="high_confidence",
                           raw_call=raw_call, provenance="graph_builder:call_resolution_heuristic")
            elif len(same_file_matches) == 1 and name_also_imported:
                # a same-file function AND an import both bind this bare name --
                # genuinely ambiguous which one a given call site means without
                # real scope resolution; do not silently pick one.
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

    return g


def graph_summary(g: nx.MultiDiGraph) -> dict:
    """Confidence breakdown of call edges -- this number belongs on the
    health-score / trust dashboard, not buried in logs."""
    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls"]
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
        "resolution_caveat": "high_confidence/low_confidence are name-matching heuristics, "
                              "not verified Python scope resolution -- see graph_builder.py docstring.",
    }
