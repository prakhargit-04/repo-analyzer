"""
Regression tests for RAG evaluation integrity (Session 25.2).

Verifies:
1. Setting an API key alone CANNOT produce a false 'COMPLETED' evaluation status
   when the production pipeline / indexed runs are unavailable. It must return 'BLOCKED'.
2. Accuracy metrics (citation precision, recall, hallucination rate) are None when blocked.
3. Running with dry_run=True returns 'NOT RUN (DRY RUN / MOCK ONLY)' with accuracy metrics set to None.
4. Running without an API key returns 'NOT RUN' with accuracy metrics set to None.
"""
from unittest.mock import MagicMock, patch

from eval.rag.eval_rag import evaluate_rag


def test_api_key_without_runs_yields_blocked_not_completed(monkeypatch):
    """
    Regression test: Setting an API key without indexed database runs must return BLOCKED,
    never COMPLETED, and accuracy metrics must be None.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-mock-key-12345")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # Mock database session that returns no AnalysisRun
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    mock_query.join.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.first.return_value = None

    result = evaluate_rag(
        questions_path="eval/questions.json",
        dry_run=False,
        output_report=None,
        db_session=mock_session,
        repo_run_map={},  # empty run map forces resolution
    )

    assert result["status"] == "BLOCKED"
    assert "No indexed production analysis run found" in result["reason"]
    assert result["citation_precision"] is None
    assert result["citation_recall"] is None
    assert result["hallucination_rate_on_unanswerable"] is None
    assert result["questions_evaluated"] == 0


def test_dry_run_reports_mock_only_with_none_accuracy_metrics(monkeypatch):
    """
    Regression test: Dry run must explicitly state mock-only status and keep accuracy metrics None.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = evaluate_rag(
        questions_path="eval/questions.json",
        dry_run=True,
        output_report=None,
    )

    assert "MOCK ONLY" in result["status"]
    assert result["citation_precision"] is None
    assert result["citation_recall"] is None
    assert result["hallucination_rate_on_unanswerable"] is None
    assert result["questions_evaluated"] > 0
    # Latencies should be recorded for plumbing validation
    assert "latency_p50_ms" in result
    assert "cost_estimate_usd" in result


def test_no_api_key_returns_not_run_with_none_metrics(monkeypatch):
    """
    Regression test: Without API key and dry_run=False, returns NOT RUN with None metrics.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = evaluate_rag(
        questions_path="eval/questions.json",
        dry_run=False,
        output_report=None,
    )

    assert result["status"] == "NOT RUN"
    assert result["citation_precision"] is None
    assert result["citation_recall"] is None
    assert result["hallucination_rate_on_unanswerable"] is None
    assert result["questions_evaluated"] == 0


def test_database_connection_failure_yields_blocked_not_completed(monkeypatch):
    """
    Regression test: When API key is provided but database connection fails,
    returns BLOCKED, not COMPLETED.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    with patch("db.engine.get_engine", side_effect=Exception("Database unreachable")):
        result = evaluate_rag(
            questions_path="eval/questions.json",
            dry_run=False,
            output_report=None,
            db_session=None,
        )

        assert result["status"] == "BLOCKED"
        assert "Production database connection failed" in result["reason"]
        assert result["citation_precision"] is None
        assert result["citation_recall"] is None
        assert result["hallucination_rate_on_unanswerable"] is None
