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


def test_rag_status_one_success_one_failure_yields_partial(monkeypatch, tmp_path):
    """
    Regression test: When 1 question succeeds and 1 fails, status must be PARTIAL,
    never COMPLETED. Attempted, success, and failed counts must be tracked accurately.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    import json
    q_file = tmp_path / "questions_two.json"
    q_file.write_text(json.dumps([
        {
            "id": "q1",
            "repo": "iniconfig",
            "question": "Where is parse defined?",
            "is_answerable": True,
            "expected_files": ["src/iniconfig/__init__.py"]
        },
        {
            "id": "q2",
            "repo": "iniconfig",
            "question": "Where is error defined?",
            "is_answerable": True,
            "expected_files": ["src/iniconfig/__init__.py"]
        }
    ]), encoding="utf-8")

    mock_session = MagicMock()
    call_count = 0

    def mock_answer(session, run_id, question, top_k):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "answer": "Defined in iniconfig [E1]",
                "citations": [{"file_path": "src/iniconfig/__init__.py", "start_line": 1, "end_line": 10}],
            }
        else:
            raise RuntimeError("Provider timeout or network error")

    with patch("rag.service.answer_repository_question", side_effect=mock_answer):
        result = evaluate_rag(
            questions_path=str(q_file),
            dry_run=False,
            output_report=None,
            db_session=mock_session,
            repo_run_map={"iniconfig": "run-test-123"},
        )

        assert result["status"] == "PARTIAL"
        assert result["total_questions"] == 2
        assert result["attempted_count"] == 2
        assert result["success_count"] == 1
        assert result["failed_count"] == 1
        assert result["skipped_count"] == 0
        assert result["execution_coverage_percent"] == 50.0
        assert result["citation_precision"] == 1.0


def test_rag_status_all_failures_yields_failed(monkeypatch, tmp_path):
    """
    Regression test: When all attempted questions fail, status must be FAILED.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    import json
    q_file = tmp_path / "questions_fail.json"
    q_file.write_text(json.dumps([
        {
            "id": "q1",
            "repo": "iniconfig",
            "question": "Where is parse defined?",
            "is_answerable": True,
            "expected_files": ["src/iniconfig/__init__.py"]
        },
        {
            "id": "q2",
            "repo": "iniconfig",
            "question": "Where is error defined?",
            "is_answerable": True,
            "expected_files": ["src/iniconfig/__init__.py"]
        }
    ]), encoding="utf-8")

    mock_session = MagicMock()

    with patch("rag.service.answer_repository_question", side_effect=RuntimeError("Provider network error")):
        result = evaluate_rag(
            questions_path=str(q_file),
            dry_run=False,
            output_report=None,
            db_session=mock_session,
            repo_run_map={"iniconfig": "run-test-123"},
        )

        assert result["status"] == "FAILED"
        assert result["total_questions"] == 2
        assert result["attempted_count"] == 2
        assert result["success_count"] == 0
        assert result["failed_count"] == 2
        assert result["execution_coverage_percent"] == 0.0
        assert result["citation_precision"] is None


def test_rag_status_full_success_yields_completed(monkeypatch, tmp_path):
    """
    Regression test: When all questions succeed, status is COMPLETED.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    import json
    q_file = tmp_path / "questions_success.json"
    q_file.write_text(json.dumps([
        {
            "id": "q1",
            "repo": "iniconfig",
            "question": "Where is parse defined?",
            "is_answerable": True,
            "expected_files": ["src/iniconfig/__init__.py"]
        },
        {
            "id": "q2",
            "repo": "iniconfig",
            "question": "Negative unanswerable probe?",
            "is_answerable": False,
            "expected_files": []
        }
    ]), encoding="utf-8")

    mock_session = MagicMock()

    def mock_answer(session, run_id, question, top_k):
        if "Negative" in question:
            return {"answer": "Not found in repository", "citations": []}
        return {
            "answer": "Defined here [E1]",
            "citations": [{"file_path": "src/iniconfig/__init__.py", "start_line": 1, "end_line": 10}],
        }

    with patch("rag.service.answer_repository_question", side_effect=mock_answer):
        result = evaluate_rag(
            questions_path=str(q_file),
            dry_run=False,
            output_report=None,
            db_session=mock_session,
            repo_run_map={"iniconfig": "run-test-123"},
        )

        assert result["status"] == "COMPLETED"
        assert result["total_questions"] == 2
        assert result["attempted_count"] == 2
        assert result["success_count"] == 2
        assert result["failed_count"] == 0
        assert result["skipped_count"] == 0
        assert result["execution_coverage_percent"] == 100.0
        assert result["citation_precision"] == 1.0
        assert result["hallucination_rate_on_unanswerable"] == 0.0
        assert result["cost_estimate_usd"] is not None
        assert result["cost_estimate_usd"] > 0.0


def test_rag_budget_exhaustion_stops_requests(monkeypatch, tmp_path):
    """
    Regression test: Enforces monetary budget cap. When budget is exhausted,
    no further requests may be sent, remaining questions must be skipped,
    and budget_exhausted flag must be True.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    import json
    q_file = tmp_path / "questions_budget.json"
    # Create 5 questions
    q_file.write_text(json.dumps([
        {"id": f"q{i}", "repo": "iniconfig", "question": f"Question {i}?", "is_answerable": True, "expected_files": []}
        for i in range(5)
    ]), encoding="utf-8")

    mock_session = MagicMock()
    call_count = 0

    def mock_answer(session, run_id, question, top_k):
        nonlocal call_count
        call_count += 1
        return {"answer": "Sample answer", "citations": []}

    with patch("rag.service.answer_repository_question", side_effect=mock_answer):
        # Very tiny budget (e.g. $0.0004) allows at most 1 call before next estimate exceeds cap
        result = evaluate_rag(
            questions_path=str(q_file),
            dry_run=False,
            output_report=None,
            db_session=mock_session,
            repo_run_map={"iniconfig": "run-test-123"},
            max_budget_usd=0.0004,
        )

        # Call count must be stopped before all 5 questions are issued
        assert call_count <= 2
        assert result["budget_exhausted"] is True
        assert result["skipped_count"] >= 3
        assert result["status"] == "PARTIAL"

