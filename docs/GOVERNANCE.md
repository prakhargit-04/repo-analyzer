# Project Governance, Engineering Rules & Definition of Done

## 1. Status Vocabulary
The only permitted status indicators across all task tracking and progress reports are:
- **`DONE`**: The work item has been fully implemented, verified with actual command execution, and supported by concrete terminal output stored under `docs/s25_evidence/`. Simulated results are strictly prohibited.
- **`NOT DONE`**: The work item has not yet been started or completed.
- **`NOT RUN`**: The item or test could not be executed due to environmental constraints (e.g., missing API keys, absent local Docker daemon, or unconfigured live providers).
- **`BLOCKED`**: The item cannot proceed due to external or structural dependencies.
- Any historical sessions or decisions without verifiable evidence are categorized as **`not recorded`**.

---

## 2. Core Engineering Discipline & Rules

### Rule 1: Evidence Integrity
Every `DONE` status claim must be accompanied by the exact command line executed and its untruncated/verifiable output stored in `docs/s25_evidence/`. Results must never be assumed, simulated, or faked.

### Rule 2: Token Discipline & Scoped Verification
During active development (Parts A to F), agents and engineers must **not** run the full backend or frontend test suite. Only run the specific targeted test file(s) covering the immediate code change. The full test suite verification is executed once in Part G.

### Rule 3: Test & Formula Protection
- Never edit or delete a test simply to make it pass. Fix the underlying implementation.
- Never alter health-score weights, penalty arithmetic, or scoring thresholds directly.
- If a formula defect is discovered, it must be formally submitted as an approval request in `docs/S25_FORMULA_APPROVAL_REQUEST.md` detailing before/after impact across at least three repositories without being applied unilaterally.

### Rule 4: Determinism & AI Integrity
- Test mode must remain strictly deterministic.
- Never present test-mode embeddings or placeholder responses as real AI results.
- Never auto-fill human evaluation labels, ratings, or question approvals.

### Rule 5: Commit & Versioning Discipline
- Maintain atomic commits: one commit per completed logical task with a clear, descriptive message.
- No force-pushes or rewritten public history.
- Version bumps occur only when the external API or persisted schema contract changes.

### Rule 6: Checkpointing
After every major phase or part, update `docs/PROGRESS.md` with an honest checkpoint recording the part name, status, evidence path, and any open items.

### Rule 7: Scope Containment
Out-of-scope discoveries or tangential bugs must be logged under the "Found, not fixed" section of `REPORT.md` rather than haphazardly edited.

---

## 3. Definition of Done (DoD)
A feature, bugfix, or milestone is considered **DONE** when and only when:
1. **Failing Test First**: A regression test demonstrating the bug or verifying the requirement is written and observed failing.
2. **Implementation Cleanliness**: The fix is applied with minimal blast radius and zero collateral regression.
3. **Targeted Verification**: The specific test file passes cleanly.
4. **Schema & Documentation Parity**: Any API changes are mirrored across `openapi.json`, `SCHEMA.md`, and `CHANGELOG.md`.
5. **Real Evidence Saved**: Concrete command output is saved in `docs/s25_evidence/`.
6. **Progress Updated**: `docs/PROGRESS.md` reflects the verified status.
