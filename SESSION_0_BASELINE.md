# SESSION 0 BASELINE & ENVIRONMENT REPORT

**Date:** 2026-09-19  
**Analyzer Version:** `0.2.0`  
**Cache Schema Version:** `v3`  

---

## 1. Environment & Setup

- **Operating System:** Windows (Win32)
- **Python Version:** 3.12.10
- **Node.js Environment:** npm packages installed cleanly in `frontend/` (409 packages added, 0 vulnerabilities).
- **Installed Python Dependencies:**
  - `tree-sitter` (0.21.3)
  - `tree-sitter-languages` (1.10.2)
  - `radon` (6.0.1)
  - `bandit` (1.9.4)
  - `lizard` (1.24.0)
  - `networkx` (3.6.1)
  - `pytest` (9.1.1)

---

## 2. Test Suite Result

- **Test Command:** `python -m pytest tests/ -v`
- **Result:** `35 passed, 1 warning in 11.77s`
- **Warning:** `FutureWarning: Language(path, name) is deprecated` from `tree_sitter` (library warning, non-fatal).

---

## 3. Analyzer Baseline Runs

### A. Local Repository Run
- **Command:** `python pipeline/main.py --local-path . --out local_output.json`
- **Status:** Success
- **Cache Basis:** `content_hash (local path -- git HEAD alone is not trusted because working tree may have uncommitted changes)`
- **Files Analyzed:** 9 total files (7 production Python files analyzed, 2 test files excluded per single policy)
- **Health Score:** Composite `78.38` (Status: `complete`)
  - Complexity: `91.04` (Radon CC)
  - Maintainability: `69.46` (Radon MI)
  - Security: `74.00` (Bandit)
- **Knowledge Graph Summary:**
  - Nodes: 59
  - Edges: 89
  - Call Edges: 48 (Resolved: 2.1%)

### B. Real Public GitHub Repository Run
- **Target Repository:** `https://github.com/pytest-dev/iniconfig`
- **Command:** `python pipeline/main.py --repo-url https://github.com/pytest-dev/iniconfig --out iniconfig_output.json`
- **Status:** Success (Commit SHA: `00e7d87c7353b1ffecc4cd55f19acfffedd5233e`)
- **Cache Basis:** `git_sha (fresh clone, trusted)`
- **Files Analyzed:** 5 total files (3 production files analyzed, 2 test files excluded)
- **Health Score:** Composite `79.42` (Status: `complete`)
  - Complexity: `81.25`
  - Maintainability: `61.67`
  - Security: `98.00`
- **Knowledge Graph Summary:**
  - Nodes: 23
  - Edges: 42
  - Call Edges: 27
- **Cache Verification:** Second run returned `[cache hit]` from `.cache/iniconfig@...json` instantaneously.

---

## 4. Frontend Baseline Result

- **Frontend Stack:** Next.js 16.3.5 (App Router, Turbopack, Tailwind CSS v4, ReactFlow 11.11.4).
- **Setup & Build:**
  - `npm install` succeeded cleanly.
  - `npm run build` compiled TypeScript and generated static pages cleanly.
  - `npm run dev -- -p 3000` starts server at `http://localhost:3000`.
- **Display Capability:** Serves `/output.json` statically to render health scores, sub-score cards, graph metrics, and an interactive ReactFlow node graph.

---

## 5. Docker Status

- **Status:** No `Dockerfile` or `docker-compose.yml` present in existing codebase.
- **Classification:** Environment/Project scope item (not required for Python/Next.js baseline execution).

---

## 6. Known Issues & Limitations

1. **Unwired Tools:** `lizard` is installed in python environment but not yet invoked in `static_analysis.py`. `semgrep`, `gitleaks`, and `OSV.dev` are not wired.
2. **Language Scope:** Analyzer currently supports Python files only (`parse_python.py`); parsers for Java, JS, TS are not present.
3. **Frontend Integration:** Next.js frontend fetches static `/output.json` instead of connecting to a dynamic backend API server.
4. **Subagent Headful Browser Limitation:** Headful browser automated runner failed to download Playwright drivers (404 on Playwright CDN zip download), though local Next.js dev server and HTTP rendering verified clean.

---

## 7. Blockers

- **None.** Session 0 setup and baseline verification completed successfully with zero application blockers.
