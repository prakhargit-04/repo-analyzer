# S24 CI, Test Reliability, Evaluation Dataset, and UI Patch Report

## Baseline and delivery status

- **Source baseline:** project ZIP supplied in this conversation; reported Git base `bad3aef8bea697083ca4037eb057b7c756464b58`.
- **Delivery:** patched source tree, not a Git commit. The uploaded ZIP does not include `.git`, and this sandbox could not reach the network, so this patch was **not pushed to GitHub**.
- **Important:** the prior GitHub-green result belongs to the user's existing commit, not to these new local changes. GitHub CI must run on the applied patch before treating it as release-ready.

## Changes made

### Backend/test reliability

- Changed the local Git test fixture to create two commits with fixed author/committer timestamps and expose both the initial and current SHAs.
- Added a regression test that clones the fixture at the older SHA and proves the later-only file is absent, then verifies the default clone uses the current commit.
- Improved the SHA propagation test to capture jobs submitted to the queue, run each through the real worker entry point with controlled pipeline results, and assert the exact SHA passed to `run_pipeline()` for both resolved and explicit revisions.
- Replaced an analyzer wrapper that called the real analyzers in the determinism test with fully controlled analyzer output. Real CLI behavior should be covered separately by analyzer integration/contract tests.
- Used controlled analyzer output in S18 worker/cache lifecycle tests so those tests do not depend on Semgrep/Bandit execution timing.
- Moved the `time` import out of the cache retry loop; the unique temp-file naming and bounded retry behavior remain unchanged.

### Frontend and CI

- Redesigned the home page and history page with a consistent dark/cyan/indigo product system, clearer hierarchy, accessible labels, loading/error/empty states, and responsive layouts.
- Updated the analysis page's outer navigation/header/surface styling to match the refreshed visual system without changing its data flow or product features.
- Added `.nvmrc` for Node 24.
- Added recursive discovery of frontend `.test.ts`/`.test.tsx` files so tests are not silently omitted from a manually maintained command list.
- Added frontend `typecheck` and kept lint/build commands explicit.
- Updated CI to use `ubuntu-24.04`, explicit Python/Node versions, `npm ci`, test/typecheck/lint/build steps, and a Windows cache/worker regression job.
- Moved the live analyzer baseline to a manually triggered workflow so normal PR checks do not depend on external analyzer/ruleset network availability.

### Evaluation dataset and transparency

- Reviewed all 20 questions against the pinned source revisions and corrected four answerable-question labels/wordings to create a more balanced paraphrase vs identifier group.
- Reframed `qs-08` as a genuinely out-of-scope OAuth token-refresh question.
- Changed `ini-08` to ask specifically whether an asynchronous parsing API is exposed.
- Marked questions as `status: "reviewed"` with `reviewed_by: "assistant-source-review"` only after this source-level review, at the user's request.
- Added `eval/REVIEW_LOG.md` with question-by-question sources, decisions, counts, and limitations.
- Updated `eval/README.md` and generated-summary warning text to disclose that this is assistant source review, not an independent second-reviewer gold set.
- Kept the evaluation runner's production parser/chunker/retrieval behavior unchanged; no retrieval-quality run or result files were generated.

## Verification actually performed here

| Check | Result | Notes |
|---|---|---|
| `python -m pytest tests/test_eval_metrics.py -q` | **35 passed** | Full output obtained in this sandbox. |
| `tests/test_api.py::test_commit_sha_propagation_and_resolution` | **1 passed** | Executed with import-only stubs for unavailable parser/analyzer dependencies; tested code path uses controlled pipeline output. |
| Older-SHA checkout regression | **1 passed** | Executed with import-only stubs; local Git clone/check-out logic was exercised. |
| Atomic-cache unit tests (save/corruption, concurrent write, transient retry, persistent-failure cleanup) | **4 passed** | Import-only stubs were configured to raise if actually invoked; cache tests did not invoke them. |
| Concurrent atomic-cache stress test | **10/10 passed** | Ten separate Linux sandbox runs; does not substitute for Windows CI. |
| Python source syntax (`py_compile`) | **PASS** | All changed Python files listed in the verification command compiled. |
| `node --check frontend/scripts/run-tests.mjs` | **PASS** | JavaScript syntax check only. |
| TypeScript/TSX syntax transpilation | **PASS** | Home, history, and analysis pages parsed/transpiled with the global TypeScript compiler; this is not a full typecheck. |
| CI workflow YAML parse | **PASS** | Parsed successfully; expected four jobs found. |
| `python -m eval.run_retrieval_eval --smoke` | **BLOCKED** | Import failed because `tree_sitter_languages` is unavailable in this sandbox. It is declared in project requirements. |
| Full backend suite | **NOT RUN** | Required parser/analyzer dependencies are unavailable; package installation was blocked by network/DNS constraints. |
| Frontend `npm test`, typecheck, lint, Next build | **NOT RUN successfully** | `npm ci` could not complete due network/DNS access; partial `node_modules` lacked `tsx`. The partial dependency tree was removed from the deliverables. |
| Full retrieval evaluation / SentenceTransformers | **NOT RUN** | Network clone and embedding-model dependencies are unavailable here; no quality numbers were fabricated. |
| GitHub CI for this patch | **NOT RUN** | The patch has not been pushed; prior CI green does not certify these changes. |

## Dataset snapshot

- Total questions: 20
- Answerable: 17
- Answerable paraphrases: 11
- Answerable non-paraphrases: 6
- Unanswerable: 3 (`ini-08`, `qs-08`, `qs-10`)
- Reviewer field: `assistant-source-review`

The data is source-reviewed but not independently reviewed by a second person. This small benchmark should be treated as exploratory, not a publication-grade gold set.

## Remaining work not safely completed in this sandbox

1. Apply the patch to the actual Git repository and run GitHub CI on the resulting commit.
2. Let CI install dependencies and validate the frontend typecheck, lint, and Next production build.
3. Run the Windows cache/worker regression job on the actual changed commit.
4. Run the smoke test and full backend suite in a fully provisioned environment.
5. Run S24 Part 2 only when pinned repositories can be cloned and a real embedding model is available. Test-provider results are non-semantic and must not be used as evidence of semantic quality.
6. Operational concerns such as authentication/rate limiting and synchronous remote SHA resolution remain deployment-hardening work; they were not changed speculatively here.
