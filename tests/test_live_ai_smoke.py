"""
Real-provider AI smoke test (v0.24.6). OPT-IN: excluded from the default suite by pytest.ini
(``addopts = -m "not network and not live_ai"``).

What it exercises, with NO test/mocked provider anywhere in the AI path:
  clone (pinned SHA) -> parse -> production chunking -> REAL sentence-transformers embeddings
  -> persist -> retrieval -> REAL LLM (OpenAI or Gemini) -> server-side citation validation

Run (needs internet for GitHub + model download + the LLM API, and an API key):

    pip install sentence-transformers openai          # or google-generativeai
    export EMBEDDING_PROVIDER=sentence_transformers
    export LLM_PROVIDER=openai                        # or gemini
    export OPENAI_API_KEY=...                         # or GEMINI_API_KEY / GOOGLE_API_KEY
    python -m pytest tests/test_live_ai_smoke.py -m live_ai -s -p no:cacheprovider

A missing prerequisite FAILS with an explicit "BLOCKED: ..." message. It never skips silently and
never substitutes the test provider. The sanitized evidence artifact is written to
``eval/results/live_smoke/<timestamp>.json`` (git-ignored) and must be reviewed by a human: the
automated assertions are necessary conditions (citations exist, expected facts appear, the
unanswerable question abstains), NOT proof of answer quality.

Static analyzers are stubbed as 'unavailable' on purpose: this test is about chunking, embeddings,
retrieval, the LLM and citation validation, and it keeps the run independent of Semgrep's network.
"""
from __future__ import annotations

import json
import math
import os
import platform
import re
import sys
from datetime import datetime, timezone
from importlib import metadata

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

pytestmark = [pytest.mark.live_ai, pytest.mark.network]

REPO_URL = "https://github.com/pytest-dev/iniconfig"
PINNED_SHA = "00e7d87c7353b1ffecc4cd55f19acfffedd5233e"  # same pin as eval/questions.json

ABSTAIN = "The available repository evidence is insufficient to determine this."

# (id, question, kind, substrings of which at least one must appear in the answer, files of which at
#  least one must be cited). Facts were checked against the pinned source (see eval/REVIEW_LOG.md).
QUESTIONS = [
    ("smoke-01", "Which class wraps a single named section of a parsed ini file?", "locate",
     ["SectionWrapper"], ["src/iniconfig/__init__.py"]),
    ("smoke-02", "Where is the exception raised for malformed ini input defined, and which module raises it?",
     "cross-file", ["ParseError"], ["src/iniconfig/exceptions.py", "src/iniconfig/_parse.py"]),
    ("smoke-03", "Which characters start a comment line? Cite the exact definition.", "source-evidence",
     ["#", ";"], ["src/iniconfig/_parse.py"]),
    ("smoke-04", "How does this library refresh OAuth access tokens?", "unanswerable", [], []),
]


def _need(cond: bool, msg: str) -> None:
    if not cond:
        pytest.fail(f"BLOCKED: {msg}", pytrace=False)


def _redact(text: str) -> str:
    for name, val in os.environ.items():
        if val and len(val) >= 8 and any(t in name.upper() for t in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            text = text.replace(val, "***REDACTED***")
    return re.sub(r"(sk-|AIza)[A-Za-z0-9_\-]{12,}", "***REDACTED***", text)


def _version(pkg: str) -> str:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return "not installed"


def test_real_provider_rag_smoke(monkeypatch, tmp_path):
    # ---- prerequisites: fail loudly, never skip, never substitute ---------------------------
    emb = os.environ.get("EMBEDDING_PROVIDER", "").strip().lower()
    llm = os.environ.get("LLM_PROVIDER", "").strip().lower()
    _need(emb == "sentence_transformers", "set EMBEDDING_PROVIDER=sentence_transformers (the test provider is not accepted here)")
    _need(llm in ("openai", "gemini", "google"), "set LLM_PROVIDER to openai or gemini (the test LLM is not accepted here)")
    key_vars = ["OPENAI_API_KEY"] if llm == "openai" else ["GEMINI_API_KEY", "GOOGLE_API_KEY"]
    _need(any(os.environ.get(k) for k in key_vars), f"set one of {key_vars}")
    _need(_version("sentence-transformers") != "not installed", "pip install sentence-transformers")
    _need(_version("openai" if llm == "openai" else "google-generativeai") != "not installed",
          "pip install openai" if llm == "openai" else "pip install google-generativeai")

    import clone as clone_mod
    import main as pipeline_main
    import static_analysis
    from db.engine import create_all_tables, get_engine, get_session_factory
    from db.store import persist_analysis
    from embeddings import get_embedding_provider, reset_embedding_provider_cache
    from rag.llm import get_llm_provider, reset_llm_provider_cache
    from rag.service import answer_repository_question

    reset_embedding_provider_cache()
    reset_llm_provider_cache()

    # ---- provider initialisation must succeed with the REAL implementations ------------------
    ep = get_embedding_provider()
    lp = get_llm_provider()
    assert ep.name == "sentence_transformers", ep.name
    assert lp.model_name and lp.__class__.__name__ in ("OpenAILLMProvider", "GeminiLLMProvider")

    # Analyzers stubbed as honestly 'unavailable' (see module docstring).
    def _unavailable(repo_root, parsed_files_rel=None, **kw):
        blk = {"status": "unavailable", "results": []}
        return {"scope_policy": "production_code_only", "complexity": dict(blk), "maintainability": dict(blk),
                "security": dict(blk), "semgrep_findings": dict(blk), "gitleaks_findings": dict(blk),
                "osv_vulnerabilities": dict(blk)}

    monkeypatch.setattr(static_analysis, "analyze_repository", _unavailable)

    result = pipeline_main.run_pipeline(
        repo_url=REPO_URL, local_path=None, commit_sha=PINNED_SHA,
        cache_dir=str(tmp_path / "cache"), persist_to_db=False,
    )

    # ---- embeddings: real, correct dimension, finite, tied to the pinned commit ---------------
    assert result["commit_sha"] == PINNED_SHA
    assert result["embedding_status"]["status"] == "completed", result["embedding_status"]
    chunks, embs = result["source_chunks"], result["source_embeddings"]
    assert chunks and len(embs) == len(chunks)
    dim = embs[0]["dimension"]
    assert dim == ep.dimension and dim > 0
    for e in embs:
        assert e["model_name"] == "sentence_transformers"
        assert len(e["vector"]) == dim and all(math.isfinite(x) for x in e["vector"])
    assert all(c["commit_sha"] == PINNED_SHA for c in chunks)

    # ---- persist and ask ------------------------------------------------------------------------
    db_url = f"sqlite:///{tmp_path / 'smoke.db'}"
    engine = get_engine(db_url)
    create_all_tables(engine)
    Session = get_session_factory(engine)
    with Session() as s:
        run_id = persist_analysis(s, result)
        s.commit()

    # checkout used to validate citation line ranges against REAL file contents
    checkout = tmp_path / "checkout"
    assert clone_mod.clone_repository(REPO_URL, str(checkout), PINNED_SHA) == PINNED_SHA

    records = []
    for qid, question, kind, expect_text, expect_files in QUESTIONS:
        with Session() as s:
            ans = answer_repository_question(s, run_id=run_id, question=question, top_k=5)  # real providers
        rec = {"id": qid, "kind": kind, "question": question, "answer": ans["answer"],
               "llm_model": ans["llm_model"], "retrieved_chunks_count": ans["retrieved_chunks_count"],
               "citations": [{k: c.get(k) for k in ("citation_id", "file_path", "start_line", "end_line")}
                             for c in ans["citations"]], "automatic_checks": {}}
        checks = rec["automatic_checks"]
        # citations point at real files and valid ranges of the pinned checkout
        for c in ans["citations"]:
            f = checkout / c["file_path"]
            assert f.is_file(), f"{qid}: cited file does not exist at the pinned commit: {c['file_path']}"
            n = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
            assert 1 <= c["start_line"] <= c["end_line"] <= n, f"{qid}: invalid range {c}"
        checks["citations_valid"] = True
        if kind == "unanswerable":
            checks["abstained"] = ans["answer"] == ABSTAIN and not ans["citations"]
            assert checks["abstained"], f"{qid}: expected an honest abstention, got: {ans['answer'][:200]!r}"
        else:
            cited_files = {c["file_path"] for c in ans["citations"]}
            checks["has_citations"] = bool(cited_files)
            checks["expected_text_in_answer"] = any(t in ans["answer"] for t in expect_text)
            checks["expected_file_cited"] = bool(cited_files & set(expect_files))
            assert checks["has_citations"], f"{qid}: answer has no validated citation"
            assert checks["expected_text_in_answer"], f"{qid}: expected one of {expect_text} in {ans['answer'][:300]!r}"
            assert checks["expected_file_cited"], f"{qid}: none of {expect_files} cited; got {sorted(cited_files)}"
        records.append(rec)

    artifact = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "repository": REPO_URL, "commit_sha": PINNED_SHA,
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "sentence-transformers": _version("sentence-transformers"),
                        "openai": _version("openai"), "google-generativeai": _version("google-generativeai")},
        "embedding": {"provider": ep.name, "model": ep.model_name, "dimension": dim, "chunks": len(chunks)},
        "llm": {"provider": llm, "model": lp.model_name},
        "records": records,
        "manual_review_required": "Check each answer's claims against its cited source ranges; "
                                  "automatic checks are necessary, not sufficient.",
    }
    out_dir = os.path.join(os.path.dirname(__file__), "..", "eval", "results", "live_smoke")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_redact(json.dumps(artifact, indent=2)))
    print(f"\n[live-smoke] sanitized evidence artifact: {os.path.abspath(path)}")
