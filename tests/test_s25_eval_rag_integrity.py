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


def test_rag_actual_cost_exceeds_budget_halts_subsequent_requests(monkeypatch, tmp_path):
    """
    Regression test: When a query's actual provider token usage exceeds the remaining budget,
    all subsequent requests are stopped immediately, remaining questions are skipped,
    and both budget_exceeded and budget_exhausted are marked True.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")
    monkeypatch.setenv("OPENAI_MODEL_NAME", "gpt-4o-mini")

    import json
    q_file = tmp_path / "questions_overbudget.json"
    q_file.write_text(json.dumps([
        {"id": f"q{i}", "repo": "iniconfig", "question": f"Question {i}?", "is_answerable": True, "expected_files": []}
        for i in range(3)
    ]), encoding="utf-8")

    mock_session = MagicMock()
    call_count = 0

    def mock_answer(session, run_id, question, top_k):
        nonlocal call_count
        call_count += 1
        # 150k prompt tokens ($0.0225) + 50k completion tokens ($0.030) = $0.0525
        return {
            "answer": "Detailed answer from pipeline",
            "citations": [],
            "llm_model": "gpt-4o-mini",
            "usage": {"prompt_tokens": 150000, "completion_tokens": 50000},
        }

    with patch("rag.service.answer_repository_question", side_effect=mock_answer):
        # Budget cap is $0.05: after 1st question ($0.0525), budget is exceeded
        result = evaluate_rag(
            questions_path=str(q_file),
            dry_run=False,
            output_report=None,
            db_session=mock_session,
            repo_run_map={"iniconfig": "run-test-123"},
            max_budget_usd=0.05,
        )

        assert call_count == 1  # stopped immediately, question 2 and 3 not called
        assert result["budget_exceeded"] is True
        assert result["budget_exhausted"] is True
        assert result["attempted_count"] == 1
        assert result["success_count"] == 1
        assert result["skipped_count"] == 2
        assert result["status"] == "PARTIAL"
        assert result["cost_basis"] == "actual"
        assert result["budget_verified"] is False
        assert result["cost_usd"] >= 0.05


def test_rag_unavailable_token_usage_metadata_marked_estimated(monkeypatch, tmp_path):
    """
    Regression test: When provider usage metadata is unavailable, cost_basis must be
    'estimated' and budget_verified must be False (never claimed True).
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    import json
    q_file = tmp_path / "questions_no_usage.json"
    q_file.write_text(json.dumps([
        {"id": "q1", "repo": "iniconfig", "question": "Question 1?", "is_answerable": True, "expected_files": []}
    ]), encoding="utf-8")

    mock_session = MagicMock()

    # Response has no usage metadata
    def mock_answer(session, run_id, question, top_k):
        return {"answer": "Answer without usage tokens", "citations": []}

    with patch("rag.service.answer_repository_question", side_effect=mock_answer):
        result = evaluate_rag(
            questions_path=str(q_file),
            dry_run=False,
            output_report=None,
            db_session=mock_session,
            repo_run_map={"iniconfig": "run-test-123"},
        )

        assert result["status"] == "COMPLETED"
        assert result["cost_basis"] == "estimated"
        assert result["budget_verified"] is False
        assert result["actual_usage_queries_count"] == 0
        assert result["estimated_usage_queries_count"] == 1
        assert result["cost_usd"] is not None
        assert result["cost_usd"] > 0.0


def test_rag_malformed_and_empty_responses_treated_as_failures(monkeypatch, tmp_path):
    """
    Regression test: Pipeline returning non-dict, missing answer, or empty/whitespace answer
    must be treated as failure, incrementing failed_count and yielding PARTIAL or FAILED.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    import json
    q_file = tmp_path / "questions_malformed.json"
    q_file.write_text(json.dumps([
        {"id": "q1", "repo": "iniconfig", "question": "Q1?", "is_answerable": True, "expected_files": []},
        {"id": "q2", "repo": "iniconfig", "question": "Q2?", "is_answerable": True, "expected_files": []},
        {"id": "q3", "repo": "iniconfig", "question": "Q3?", "is_answerable": True, "expected_files": []},
    ]), encoding="utf-8")

    mock_session = MagicMock()
    call_idx = 0

    def mock_answer(session, run_id, question, top_k):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            return "not-a-dict-string"  # Malformed: non-dict
        elif call_idx == 2:
            return {"answer": "   ", "citations": []}  # Malformed: whitespace only
        else:
            return {"answer": "Valid non-empty answer", "citations": []}  # Valid

    with patch("rag.service.answer_repository_question", side_effect=mock_answer):
        result = evaluate_rag(
            questions_path=str(q_file),
            dry_run=False,
            output_report=None,
            db_session=mock_session,
            repo_run_map={"iniconfig": "run-test-123"},
        )

        assert result["attempted_count"] == 3
        assert result["failed_count"] == 2
        assert result["success_count"] == 1
        assert result["status"] == "PARTIAL"
        assert result["execution_coverage_percent"] == 33.3


def test_rag_all_malformed_responses_yields_failed(monkeypatch, tmp_path):
    """
    Regression test: When all responses from pipeline are malformed or empty,
    status must be FAILED with 0% coverage.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    import json
    q_file = tmp_path / "questions_all_malformed.json"
    q_file.write_text(json.dumps([
        {"id": "q1", "repo": "iniconfig", "question": "Q1?", "is_answerable": True, "expected_files": []},
        {"id": "q2", "repo": "iniconfig", "question": "Q2?", "is_answerable": True, "expected_files": []},
    ]), encoding="utf-8")

    mock_session = MagicMock()

    # Returns dict missing answer
    def mock_answer(session, run_id, question, top_k):
        return {"citations": []}

    with patch("rag.service.answer_repository_question", side_effect=mock_answer):
        result = evaluate_rag(
            questions_path=str(q_file),
            dry_run=False,
            output_report=None,
            db_session=mock_session,
            repo_run_map={"iniconfig": "run-test-123"},
        )

        assert result["attempted_count"] == 2
        assert result["failed_count"] == 2
        assert result["success_count"] == 0
        assert result["status"] == "FAILED"
        assert result["execution_coverage_percent"] == 0.0


def test_validate_usage_tokens_safe_validation():
    """
    Session 25.5 Regression test:
    Directly validates that validate_usage_tokens accepts valid non-negative integers
    and rejects booleans, negative numbers, floats/fractional values, NaN, infinity,
    missing required fields, and non-dict objects.
    """
    from eval.rag.eval_rag import validate_usage_tokens

    # Valid non-negative integers
    assert validate_usage_tokens({"prompt_tokens": 100, "completion_tokens": 50}) == (100, 50)
    assert validate_usage_tokens({"prompt_tokens": 0, "completion_tokens": 0}) == (0, 0)
    assert validate_usage_tokens({"prompt_tokens": 1000, "completion_tokens": 0, "total_tokens": 1000}) == (1000, 0)

    # Reject booleans (bool is a subclass of int in Python)
    assert validate_usage_tokens({"prompt_tokens": True, "completion_tokens": 50}) is None
    assert validate_usage_tokens({"prompt_tokens": 100, "completion_tokens": False}) is None
    assert validate_usage_tokens({"prompt_tokens": True, "completion_tokens": False}) is None

    # Reject negative integers
    assert validate_usage_tokens({"prompt_tokens": -1, "completion_tokens": 50}) is None
    assert validate_usage_tokens({"prompt_tokens": 100, "completion_tokens": -5}) is None

    # Reject fractional and float values
    assert validate_usage_tokens({"prompt_tokens": 10.5, "completion_tokens": 50}) is None
    assert validate_usage_tokens({"prompt_tokens": 100, "completion_tokens": 20.0}) is None

    # Reject NaN and infinity
    assert validate_usage_tokens({"prompt_tokens": float("nan"), "completion_tokens": 50}) is None
    assert validate_usage_tokens({"prompt_tokens": 100, "completion_tokens": float("inf")}) is None
    assert validate_usage_tokens({"prompt_tokens": float("-inf"), "completion_tokens": 50}) is None

    # Reject missing fields
    assert validate_usage_tokens({"prompt_tokens": 100}) is None
    assert validate_usage_tokens({"completion_tokens": 50}) is None
    assert validate_usage_tokens({}) is None

    # Reject malformed objects / non-dicts
    assert validate_usage_tokens(None) is None
    assert validate_usage_tokens("usage") is None
    assert validate_usage_tokens([100, 50]) is None
    assert validate_usage_tokens(42) is None


def test_malformed_response_with_valid_usage_contributes_to_cost(monkeypatch, tmp_path):
    """
    Session 25.5 Regression test:
    A malformed or empty response with valid usage metadata still contributes to recorded cost,
    is classified as a failure, and preserves coverage semantics.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    import json
    q_file = tmp_path / "questions_empty_ans.json"
    q_file.write_text(json.dumps([
        {"id": "q1", "repo": "iniconfig", "question": "Question 1?", "is_answerable": True, "expected_files": []}
    ]), encoding="utf-8")

    mock_session = MagicMock()

    # Empty answer text but valid provider usage metadata
    def mock_answer(session, run_id, question, top_k):
        return {
            "answer": "   ",  # whitespace only -> malformed / invalid answer
            "citations": [],
            "llm_model": "gpt-4o-mini",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }

    with patch("rag.service.answer_repository_question", side_effect=mock_answer):
        result = evaluate_rag(
            questions_path=str(q_file),
            dry_run=False,
            output_report=None,
            db_session=mock_session,
            repo_run_map={"iniconfig": "run-test-123"},
        )

        assert result["attempted_count"] == 1
        assert result["failed_count"] == 1
        assert result["success_count"] == 0
        assert result["status"] == "FAILED"
        assert result["execution_coverage_percent"] == 0.0

        # Cost was recorded before answer validation failed
        assert result["actual_usage_queries_count"] == 1
        assert result["estimated_usage_queries_count"] == 0
        assert result["has_unaccounted_cost"] is False
        assert result["cost_basis"] == "actual"
        assert result["cost_usd"] is not None
        # 1000 * $0.00015/1k + 500 * $0.0006/1k = 0.00015 + 0.0003 = 0.00045
        assert round(result["cost_usd"], 6) == 0.00045
        # Actual cost was recorded and well within budget ($0.00045 <= $1.00)
        assert result["budget_verified"] is True
        assert result["budget_exceeded"] is False


def test_usage_not_double_counted(monkeypatch, tmp_path):
    """
    Session 25.5 Regression test:
    Ensures provider usage is counted exactly once per query and never double-counted.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    import json
    q_file = tmp_path / "questions_single.json"
    q_file.write_text(json.dumps([
        {"id": "q1", "repo": "iniconfig", "question": "Question 1?", "is_answerable": True, "expected_files": []}
    ]), encoding="utf-8")

    mock_session = MagicMock()

    def mock_answer(session, run_id, question, top_k):
        return {
            "answer": "Valid complete answer with sufficient length to verify estimation would differ.",
            "citations": [],
            "llm_model": "gpt-4o-mini",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
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
        assert result["actual_usage_queries_count"] == 1
        assert result["estimated_usage_queries_count"] == 0
        # Exactly 0.00045, not double (0.0009) or mixed with text estimate
        assert round(result["cost_usd"], 6) == 0.00045
        assert result["budget_verified"] is True
        assert result["budget_exceeded"] is False


def test_invalid_usage_metadata_rejected_and_falls_back_to_estimated(monkeypatch, tmp_path):
    """
    Session 25.5 Regression test:
    When usage contains booleans or invalid types, it is rejected as actual usage,
    falls back to estimated accounting, and cannot produce budget_verified=True.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    import json
    q_file = tmp_path / "questions_invalid_usage.json"
    q_file.write_text(json.dumps([
        {"id": "q1", "repo": "iniconfig", "question": "Question 1?", "is_answerable": True, "expected_files": []}
    ]), encoding="utf-8")

    mock_session = MagicMock()

    # Returns boolean prompt_tokens
    def mock_answer(session, run_id, question, top_k):
        return {
            "answer": "Valid answer text",
            "citations": [],
            "llm_model": "gpt-4o-mini",
            "usage": {"prompt_tokens": True, "completion_tokens": 50},
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
        assert result["actual_usage_queries_count"] == 0
        assert result["estimated_usage_queries_count"] == 1
        assert result["cost_basis"] == "estimated"
        assert result["budget_verified"] is False


def test_failed_request_without_usage_tracks_unaccounted_cost(monkeypatch, tmp_path):
    """
    Session 25.5 Regression test:
    When a request fails without usable usage metadata, has_unaccounted_cost is True,
    and budget_verified is False.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    import json
    q_file = tmp_path / "questions_fail_no_usage.json"
    q_file.write_text(json.dumps([
        {"id": "q1", "repo": "iniconfig", "question": "Q1?", "is_answerable": True, "expected_files": []},
        {"id": "q2", "repo": "iniconfig", "question": "Q2?", "is_answerable": True, "expected_files": []},
    ]), encoding="utf-8")

    mock_session = MagicMock()
    call_idx = 0

    def mock_answer(session, run_id, question, top_k):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            return {
                "answer": "Valid answer 1",
                "citations": [],
                "llm_model": "gpt-4o-mini",
                "usage": {"prompt_tokens": 500, "completion_tokens": 100},
            }
        else:
            raise RuntimeError("Provider connection reset without response")

    with patch("rag.service.answer_repository_question", side_effect=mock_answer):
        result = evaluate_rag(
            questions_path=str(q_file),
            dry_run=False,
            output_report=None,
            db_session=mock_session,
            repo_run_map={"iniconfig": "run-test-123"},
        )

        assert result["attempted_count"] == 2
        assert result["success_count"] == 1
        assert result["failed_count"] == 1
        assert result["status"] == "PARTIAL"
        assert result["has_unaccounted_cost"] is True
        assert result["budget_verified"] is False


def test_pre_request_budget_exhaustion_halts_requests(monkeypatch, tmp_path):
    """
    Session 25.5 Regression test:
    When the configured budget is smaller than the conservative pre-request estimate,
    the pre-request budget check halts execution immediately before launching queries.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")

    import json
    q_file = tmp_path / "questions_prereq.json"
    q_file.write_text(json.dumps([
        {"id": "q1", "repo": "iniconfig", "question": "Q1?", "is_answerable": True, "expected_files": []},
        {"id": "q2", "repo": "iniconfig", "question": "Q2?", "is_answerable": True, "expected_files": []},
    ]), encoding="utf-8")

    mock_session = MagicMock()
    call_count = 0

    def mock_answer(session, run_id, question, top_k):
        nonlocal call_count
        call_count += 1
        return {"answer": "A", "citations": []}

    with patch("rag.service.answer_repository_question", side_effect=mock_answer):
        # max_budget_usd is $0.00001, far below conservative single_query_est_cost (~$0.0003)
        result = evaluate_rag(
            questions_path=str(q_file),
            dry_run=False,
            output_report=None,
            db_session=mock_session,
            repo_run_map={"iniconfig": "run-test-123"},
            max_budget_usd=0.00001,
        )

        assert call_count == 0  # Pre-request gate prevented any calls
        assert result["attempted_count"] == 0
        assert result["skipped_count"] == 2
        assert result["budget_exhausted"] is True
        assert result["budget_verified"] is False
        assert result["status"] == "BLOCKED"
