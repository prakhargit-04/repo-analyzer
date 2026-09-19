-- GitHub Project Analyzer — Tier 1 Pipeline (Python-only MVP)

This is a real, tested implementation of the pipeline described in
`10. System Architecture (Summary)` of the project plan, scoped to Python
only per the "fully support one language" recommendation. It has been run
end-to-end against a real GitHub repository (pallets/itsdangerous), not
just against synthetic examples.

## What's implemented and verified

| Stage | File | Tool(s) | Status |
|---|---|---|---|
| Clone/checkout | `pipeline/clone.py` | `git` subprocess | Verified against a real GitHub URL |
| Structural parse | `pipeline/parse_python.py` | tree-sitter | Verified: functions, classes, imports, line ranges |
| Static analysis | `pipeline/static_analysis.py` | radon, bandit | Verified, see calibration note below |
| Knowledge graph | `pipeline/graph_builder.py` | networkx | Verified: 2-layer graph with confidence-tagged call edges |
| Health score | `pipeline/health_score.py` | — | Formula fully specified, see below |
| Caching | `pipeline/main.py` | filesystem, keyed by content-hash + analyzer version | Verified: second run on same content hits cache; a version bump invalidates it |

**Not yet wired (documented, not silently dropped):**
- `lizard` is installed but not yet called from `static_analysis.py` — add as a cross-check against radon's complexity numbers.
- `semgrep` — heavier, rule-config-dependent; add once this core is stable.
- `gitleaks` — Go binary, not pip-installable; needs a separate step in the real deployment container, not this dev sandbox.
- `OSV.dev` — needs an outbound API call; wire it in the deployed environment.
- Java / JS/TS parsing — add a `parse_java.py` / `parse_js.py` alongside `parse_python.py` once this is solid; `graph_builder.py` is already language-agnostic (it consumes generic FunctionNode/ClassNode/ImportEdge objects).

## Real bugs this caught (worth keeping in your project report — this IS your evaluation methodology working)

1. **Bandit noise from test asserts.** First run gave a security sub-score
   of 0 — 57/68 bandit findings were `assert` statements inside the test
   suite (`B101`), not vulnerabilities. Fixed by giving complexity,
   maintainability, and security **one shared** test-exclusion definition
   (`util.is_test_file`) instead of three independent ones that drifted
   out of sync (an earlier fix excluded tests from bandit but forgot
   complexity/maintainability were still including them — a reviewer
   caught this).
2. **The test-exclusion rule itself was incomplete.** Validating on
   `pytest-dev/iniconfig` showed its test directory is named `testing/`
   (not `test/`/`tests/`) and its `conftest.py` doesn't match `test_*`
   naming — both slipped through undetected until run against a second
   real repo. Fixed, and the sub-score changed (82.8 → 79.4) as a direct,
   visible result.
3. **Local-path caching was silently unsound.** The cache key for
   `--local-path` used to be a hardcoded placeholder, meaning edits to a
   local checkout would never invalidate the cache. Fixed: local paths are
   now content-hashed (file paths + sizes + mtimes), not just keyed off git
   HEAD — because HEAD doesn't reflect uncommitted working-tree changes.
4. **Tool failure could look like a clean repository.** If bandit crashed,
   timed out, or returned bad output, the old code returned `[]` → security
   sub-score of 100 (a broken analysis looking spotless). Every stage now
   reports `success`/`partial`/`failed`, and the health score marks itself
   `"status": "partial"` with the failed component set to `null` and
   weights renormalized across what's actually available — verified by
   deliberately breaking bandit and confirming the score does NOT come
   back as a fake 100.
5. **Call-confidence labels were overclaiming.** A same-file function-name
   match was labeled `"certain"`, but the resolver never checks for import
   shadowing or real Python scope — it's a name-matching heuristic, not
   verified resolution. Relabeled to `"high_confidence"` / `"low_confidence"`
   (structural containment/import edges keep `"structural_certain"`, since
   those genuinely are direct AST facts), and same-file matches that also
   collide with a same-file import name are now downgraded to `"flagged"`
   rather than silently picked.
6. **Provenance claimed exact tool versions but didn't capture them.**
   Fixed — `radon:6.0.1:cc_visit`, `bandit:<version>` are now real,
   captured via `radon.__version__` / `importlib.metadata`, not asserted.

Validated end-to-end on three structurally different real repos
(`pallets/itsdangerous`, `benjaminp/six`, `pytest-dev/iniconfig`) — sample
outputs for all three are included alongside this code.

### Round 2 review — 4 more real bugs, now all covered by regression tests

A second review pass (after the fixes above) found four more real bugs.
All four are fixed and each now has a permanent regression test in
`tests/test_regression.py` so none of them can silently reappear:

7. **`weights_used` reported raw weights, not renormalized ones.** When a
   sub-score was missing and weights were renormalized to sum to 1.0 for
   the actual composite calculation, the reported `weights_used` field
   still echoed the raw, un-renormalized `WEIGHTS` constant — a
   documentation-vs-reality mismatch in the output itself. Fixed:
   `weights_used` now reports `WEIGHTS[k] / weight_sum`, which always sums
   to 1.0. Caught by writing the regression suite, which is exactly why
   the suite exists.
8. **Duplicate same-file function names silently collided.** Call
   resolution built its same-file candidate set as
   `{f.name: f.id for f in ...}` — a plain dict, so two functions sharing a
   name in one file meant the second silently overwrote the first, and a
   call to that name was confidently labeled `high_confidence` pointing at
   whichever definition happened to survive. Fixed: candidates are now
   collected as a list per (file, name); two-or-more matches are flagged
   as `duplicate_same_file_candidates` instead of guessed.
9. **Bandit non-zero-but-not-crash exit codes weren't distinguished from
   real crashes** in earlier drafts — confirmed fixed and covered: a
   missing bandit executable, a timeout, and unparsable JSON stdout all
   correctly produce `status: "failed"`, never a false-clean `[]`.
10. **Documentation drift** — the confidence-label names and cache-key
    description in this README had fallen out of sync with the actual
    code (`certain`/`heuristic` vs. the real `structural_certain` /
    `high_confidence` / `low_confidence` / `flagged`, and a stale
    `<repo>@<commit-sha>` cache-key description that predated snapshot
    hashing). Fixed above.

### Round 3 review — 3 more real bugs, now all covered by regression tests

A third review pass found three more real bugs, all now fixed with
permanent regression tests:

11. **Local-path snapshot hashing wasn't actually a content hash.** It
    hashed relative-path + file-size + mtime, not the file's actual bytes.
    Two different edits that happen to preserve file size, or that land
    within the same filesystem mtime resolution window, could fail to
    invalidate the cache — this is not a content hash, it's a metadata
    hash that usually correlates with content changing. Fixed:
    `resolve_snapshot_id` now streams and hashes the real bytes of every
    included file. `test_content_hash_ignores_size_and_mtime_collisions`
    pins the file's original mtime back after a same-size edit specifically
    to prove the old implementation would have missed it.
12. **The cache key didn't account for the analyzer's own version.** A
    cached result would be served forever for unchanged repo content, even
    across a bugfix to this codebase's scoring formula, parser, or
    resolution logic — silently serving a pre-fix (wrong) result as if it
    were current. Fixed: `build_cache_key()` folds `CACHE_SCHEMA_VERSION`
    and `ANALYZER_VERSION` into the actual cache key alongside the content
    snapshot, so bumping `ANALYZER_VERSION` (done here, to `0.2.0`) forces
    every existing cache entry to be recomputed.
13. **Bandit's exit code was never checked.** The subprocess call only
    handled `TimeoutExpired`/`FileNotFoundError`; any other non-zero exit
    (bandit's internal-error code, a killed process) fell through and
    whatever happened to be in `stdout` got parsed as if the scan had
    completed cleanly. Fixed: only exit codes `0` (clean) and `1` (issues
    found) — bandit's own documented contract for a completed scan — are
    accepted; anything else is `status: "failed"`.
14. **A `"partial"` component status didn't actually make the overall
    result `"partial"` if it still produced a number.** `_complexity_subscore`
    etc. return a real score for `status: "partial"` (computed from
    whatever results came back before the partial failure) — but the old
    `compute_health_score` derived `"complete"` vs `"partial"` purely from
    whether every sub-score was non-`None`. A partial-but-numeric result
    was therefore reported as a full, trustworthy `"complete"` analysis.
    Fixed: overall status is now derived from the actual component
    statuses (`"complete"` iff every component is `"success"`), reported
    alongside the scores as a new `component_statuses` field so a partial
    component's presence is visible even when it still contributed a
    number. `test_partial_component_can_contribute_score_but_not_complete_status`
    is the test that pins this down.

## Regression tests

```bash
pip install pytest
python -m pytest tests/ -v
```

35 tests, one (or a parametrized group) per real bug found across all three
review rounds, plus a small number of complementary sanity checks so a
test can't trivially always pass (e.g. confirming `status: "complete"`
really is reachable, not just `"partial"`, and that an unknown component
status raises rather than being silently treated as some default). Do not
add a new tool or feature until these pass — that's the whole point of
writing them before moving on to `lizard`.

## The deterministic-vs-AI boundary, concretely

Every node/edge in the graph carries a `provenance` field naming the exact
tool or heuristic that produced it. Structural edges (containment, imports)
carry `confidence: structural_certain` — direct AST facts, no inference.
Call edges carry `high_confidence` / `low_confidence` / `flagged` (see the
docstring in `graph_builder.py` for the exact resolution rules — this is a
name-matching heuristic, not real Python scope resolution, and is labeled
accordingly rather than overclaiming "certain"). Nothing here is an LLM
guess — the LLM layer (not yet built) would only ever narrate over this
already-computed, already-labeled graph, and every claim it makes must
trace back to one of these node/edge IDs.

## Running it

```bash
pip install -r requirements.txt
python pipeline/main.py --repo-url https://github.com/owner/repo
# or
python pipeline/main.py --local-path /path/to/already/cloned/repo
```

Output is a single JSON document: static analysis results, knowledge graph
summary (including the confidence breakdown), and the health score with
its full formula, sub-scores, and `component_statuses`.

**Analysis status contract** — every stage (`complexity`, `maintainability`,
`security`) reports one of:

| Status | Meaning |
|---|---|
| `success` | Tool completed and output is complete |
| `partial` | Some analysis/output is incomplete (score may still be computed from what's available) |
| `failed` | Tool result unavailable; no clean result is inferred |

The overall `health_score.status` is `"complete"` **only if every component
is `"success"`** — a `"partial"` component can still contribute a real
number to the composite, but that does not make the overall result
`"complete"`. `"failed"` means no component produced anything usable.
`"partial"` covers everything else.

**Caching** — cached under `.cache/`, keyed by `<repo>@<versioned-key>`,
where `versioned-key = sha256(CACHE_SCHEMA_VERSION + ANALYZER_VERSION +
snapshot_id)`. A fresh clone's `snapshot_id` is its git SHA (trusted, since
nothing can have modified the checkout since cloning); a `--local-path`
`snapshot_id` is a real byte-level SHA-256 of every included file's
relative path and content (git HEAD alone is not trusted for local paths,
since a dirty working tree changes actual content without changing HEAD —
and path+size+mtime is not a content hash, since a same-size edit or an
mtime collision could go undetected). Folding `ANALYZER_VERSION` into the
key means a bugfix to this codebase invalidates old cache entries even
when the analyzed repository's content hasn't changed at all.

## Next concrete steps (in order)

1. ~~Write regression tests for every bug found~~ — done (`tests/test_regression.py`, 35 passing across 3 review rounds).
2. Run against 5–10 more real repos of varying size/quality; each new repo is a chance to find another `iniconfig`-style edge case in the test-exclusion rule before it's load-bearing for a score someone trusts.
3. Wire `lizard` into `static_analysis.py` as a cross-check on radon's complexity numbers (flag functions where the two tools disagree sharply).
4. Only then: start the pgvector embedding + evidence-linked chat layer — second major build, not built in parallel with Tier 1 hardening.
