"""
FastAPI route definitions for repository analysis API (S15).
"""
from __future__ import annotations
import os
import sys
import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import clone

from api.url_validator import validate_github_url
from db.engine import get_engine, get_session_factory
from db.models import (
    AnalysisRun,
    FileRecord,
    EntityRecord,
    GraphNode,
    GraphEdge,
    Finding,
    HealthScore,
)
from db.store import (
    create_job,
    get_job_dict,
    get_active_job_for_repo,
    find_completed_run_by_sha,
    get_analysis_by_run_id,
    get_analysis_summary_db,
    get_analysis_graph_db,
    get_analysis_findings_db,
    get_analysis_files_db,
    get_latest_analysis,
    get_all_runs_for_repo,
    complete_job,
    get_source_chunks_for_run,
    resolve_source_chunk,
    retrieve_similar_chunks,
    EmbeddingMismatchError,
)
from rag.service import answer_repository_question
from rag.llm import LLMError


from worker import get_worker_queue
from api.schemas import (
    SubmitAnalysisRequest,
    JobStatusResponse,
    HealthResponse,
    GraphResponse,
    FindingsResponse,
    FilesResponse,
    FileDetailResponse,
    ChunksResponse,
    SourceChunkItem,
    RetrievalRequest,
    RetrievalResponse,
    AskRequest,
    AskResponse,
)


router = APIRouter(prefix="/api/v1", tags=["repository-analysis"])
logger = logging.getLogger(__name__)
NON_FINAL_JOB_STATUSES = ("queued", "cloning", "parsing", "analyzing", "graph-building", "scoring", "embedding")


def _max_active_jobs() -> int:
    """Parse the queue cap without making malformed deployment config fatal."""
    try:
        value = int(os.environ.get("MAX_ACTIVE_JOBS", "50"))
        if value < 0:
            raise ValueError
        return value
    except ValueError:
        logger.warning("Invalid MAX_ACTIVE_JOBS; using default 50")
        return 50


def get_db_session():
    db_url = os.environ.get("DATABASE_URL", "sqlite:///repo_analyzer.db")
    engine = get_engine(db_url)
    SessionLocal = get_session_factory(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


from util import get_cache_dir


# ---------------------------------------------------------------------------
# Health & Readiness
# ---------------------------------------------------------------------------

from version import APP_VERSION

@router.get("/health", response_model=HealthResponse)
def health_check():
    return {"status": "ok", "version": APP_VERSION, "database": "configured"}


@router.get("/readiness", response_model=HealthResponse)
def readiness_check(db: Session = Depends(get_db_session)):
    try:
        db.execute(select(1))
        db_status = "connected"
    except Exception:
        db_status = "error"
    return {"status": "ready" if db_status == "connected" else "not_ready", "version": APP_VERSION, "database": db_status}



# ---------------------------------------------------------------------------
# Submit Repository Analysis
# ---------------------------------------------------------------------------

@router.post("/analyses", status_code=status.HTTP_202_ACCEPTED)
def submit_analysis(
    req: SubmitAnalysisRequest,
    db: Session = Depends(get_db_session),
):
    # Strict server-side GitHub HTTPS-only URL validation (S22)
    valid, result = validate_github_url(req.repo_url)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result,
        )
    repo_url = result  # Use normalized URL

    # 1. Pre-clone SHA resolution via git ls-remote
    effective_sha = req.commit_sha
    if not effective_sha:
        effective_sha = clone.resolve_remote_sha(repo_url)

    # 2. Check cache hit for resolved SHA
    if effective_sha:
        cached_run = find_completed_run_by_sha(db, repo_url, effective_sha)
        if cached_run:
            # Immediate cache hit: create job, link run_id, mark completed with cache_hit=True
            job = create_job(db, repo_url, commit_sha=effective_sha)
            complete_job(db, job.id, run_id=cached_run["run_id"], status="completed", cache_hit=True)
            db.commit()
            job_data = get_job_dict(db, job.id)
            return job_data

    # 3. Check for active (queued/running) duplicate job
    active_job = get_active_job_for_repo(db, repo_url, effective_sha)
    if active_job:
        job_data = get_job_dict(db, active_job.id)
        return job_data

    # Check MAX_ACTIVE_JOBS backpressure cap
    max_active = _max_active_jobs()
    from sqlalchemy import func
    from db.models import AnalysisJob
    active_count = db.execute(
        select(func.count(AnalysisJob.id)).where(
            AnalysisJob.status.in_(NON_FINAL_JOB_STATUSES)
        )
    ).scalar() or 0
    if active_count >= max_active:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Server is at capacity ({active_count}/{max_active} active jobs). Please try again later.",
        )

    # 4. Enqueue new analysis job
    job = create_job(db, repo_url, commit_sha=effective_sha)
    db.commit()

    db_url = os.environ.get("DATABASE_URL", "sqlite:///repo_analyzer.db")
    queue = get_worker_queue()
    queue.submit_job(job.id, db_url, get_cache_dir())

    job_data = get_job_dict(db, job.id)
    return job_data


# ---------------------------------------------------------------------------
# Job Status Endpoints
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str, db: Session = Depends(get_db_session)):
    job_data = get_job_dict(db, job_id)
    if not job_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")
    return job_data


@router.get("/jobs/{job_id}/status")
def get_job_status_summary(job_id: str, db: Session = Depends(get_db_session)):
    job_data = get_job_dict(db, job_id)
    if not job_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")
    return {
        "job_id": job_data["job_id"],
        "repo_url": job_data["repo_url"],
        "status": job_data["status"],
        "current_stage": job_data["current_stage"],
        "progress": job_data["progress"],
        "cache_hit": job_data["cache_hit"],
        "error_message": job_data["error_message"],
        "run_id": job_data["run_id"],
    }


# ---------------------------------------------------------------------------
# Analysis Result Endpoints (S1-Canonical & S16-Ready)
# ---------------------------------------------------------------------------

@router.get("/analyses/latest")
def get_latest_repo_analysis(
    repo_url: str = Query(..., description="Repository URL"),
    db: Session = Depends(get_db_session),
):
    valid, result = validate_github_url(repo_url)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result,
        )
    repo_url = result

    analysis = get_latest_analysis(db, repo_url)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No completed analysis found for repository '{repo_url}'")
    return analysis


@router.get("/repositories/runs")
def list_repository_runs(
    repo_url: str = Query(..., description="Repository URL"),
    db: Session = Depends(get_db_session),
):
    valid, result = validate_github_url(repo_url)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result,
        )
    repo_url = result

    runs = get_all_runs_for_repo(db, repo_url)
    return {"repo_url": repo_url, "total_runs": len(runs), "runs": runs}



@router.get("/analyses/{run_id}")
def get_full_analysis(run_id: str, db: Session = Depends(get_db_session)):
    analysis = get_analysis_by_run_id(db, run_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")
    return analysis


@router.get("/analyses/{run_id}/status")
def get_analysis_run_status(run_id: str, db: Session = Depends(get_db_session)):
    analysis = get_analysis_by_run_id(db, run_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")
    return {
        "run_id": analysis["run_id"],
        "repository": analysis["repository"],
        "commit_sha": analysis["commit_sha"],
        "analysis_status": analysis["analysis_status"],
        "analyzer_version": analysis["analyzer_version"],
        "schema_version": analysis["schema_version"],
        "analyzed_at_utc": analysis["analyzed_at_utc"],
        "files_analyzed": analysis["files_analyzed"],
        "languages": analysis["languages"],
    }


@router.get("/analyses/{run_id}/summary")
def get_analysis_summary(run_id: str, db: Session = Depends(get_db_session)):
    summary = get_analysis_summary_db(db, run_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")
    return summary


@router.get("/analyses/{run_id}/graph", response_model=GraphResponse)
def get_analysis_graph(
    run_id: str,
    node_type: Optional[str] = Query(None, description="Filter nodes by type (function, class, file, finding, etc.)"),
    file_path: Optional[str] = Query(None, description="Filter nodes by file path"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
):
    graph = get_analysis_graph_db(db, run_id, node_type=node_type, file_path=file_path, limit=limit, offset=offset)
    if graph is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")
    return graph


@router.get("/analyses/{run_id}/findings", response_model=FindingsResponse)
def get_analysis_findings(
    run_id: str,
    analyzer: Optional[str] = Query(None, description="Filter by analyzer tool name (bandit, semgrep, gitleaks)"),
    severity: Optional[str] = Query(None, description="Filter by severity (HIGH, MEDIUM, LOW)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
):
    findings_data = get_analysis_findings_db(db, run_id, analyzer=analyzer, severity=severity, limit=limit, offset=offset)
    if findings_data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")
    return findings_data


@router.get("/analyses/{run_id}/files", response_model=FilesResponse)
def get_analysis_files(
    run_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
):
    files_data = get_analysis_files_db(db, run_id, limit=limit, offset=offset)
    if files_data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")
    return files_data


@router.get("/analyses/{run_id}/files/{file_path:path}", response_model=FileDetailResponse)
def get_file_detail(
    run_id: str,
    file_path: str,
    db: Session = Depends(get_db_session),
):
    analysis = get_analysis_by_run_id(db, run_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")

    nodes = analysis.get("knowledge_graph", {}).get("nodes", [])
    entities = [n for n in nodes if n.get("file") == file_path]

    parse_errors = [pe.get("error") for pe in analysis.get("parse_errors", []) if pe.get("file") == file_path]
    parse_err = parse_errors[0] if parse_errors else None

    # Determine file language
    lang = "unknown"
    if file_path.endswith(".py"):
        lang = "python"
    elif file_path.endswith(".java"):
        lang = "java"
    elif file_path.endswith((".js", ".jsx")):
        lang = "javascript"
    elif file_path.endswith((".ts", ".tsx")):
        lang = "typescript"

    return {
        "run_id": run_id,
        "file_path": file_path,
        "language": lang,
        "parse_error": parse_err,
        "entities": entities,
    }


# ---------------------------------------------------------------------------
# Source Chunks Endpoints (S19)
# ---------------------------------------------------------------------------

@router.get("/analyses/{run_id}/chunks", response_model=ChunksResponse)
def get_analysis_chunks(
    run_id: str,
    file_path: Optional[str] = Query(None, description="Filter chunks by file path"),
    start_line: Optional[int] = Query(None, description="Filter chunks overlapping start line"),
    end_line: Optional[int] = Query(None, description="Filter chunks overlapping end line"),
    entity_name: Optional[str] = Query(None, description="Filter chunks by entity name"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
):
    run_exists = db.execute(select(AnalysisRun.id).where(AnalysisRun.id == run_id)).scalar_one_or_none()
    if not run_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")

    return get_source_chunks_for_run(
        db,
        run_id=run_id,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        entity_name=entity_name,
        limit=limit,
        offset=offset,
    )


@router.get("/analyses/{run_id}/chunks/resolve", response_model=SourceChunkItem)
def resolve_chunk_for_location(
    run_id: str,
    file_path: str = Query(..., description="File path relative to repository root"),
    line: int = Query(..., ge=1, description="Line number to resolve"),
    db: Session = Depends(get_db_session),
):
    run_exists = db.execute(select(AnalysisRun.id).where(AnalysisRun.id == run_id)).scalar_one_or_none()
    if not run_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")

    chunk = resolve_source_chunk(db, run_id=run_id, file_path=file_path, line=line)
    if not chunk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No matching source chunk found for file '{file_path}' at line {line}",
        )
    return chunk


# ---------------------------------------------------------------------------
# Vector Retrieval Endpoints (S20)
# ---------------------------------------------------------------------------

@router.post("/analyses/{run_id}/retrieve", response_model=RetrievalResponse)
def retrieve_source_evidence_post(
    run_id: str,
    req: RetrievalRequest,
    db: Session = Depends(get_db_session),
):
    analysis = get_analysis_by_run_id(db, run_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")

    try:
        return retrieve_similar_chunks(db, run_id=run_id, query_text=req.query, top_k=req.top_k)
    except EmbeddingMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/analyses/{run_id}/retrieve", response_model=RetrievalResponse)
def retrieve_source_evidence_get(
    run_id: str,
    query: str = Query(..., description="Natural language search query for source code evidence retrieval"),
    top_k: int = Query(5, ge=1, le=50, description="Maximum number of top matching source chunks to return"),
    db: Session = Depends(get_db_session),
):
    analysis = get_analysis_by_run_id(db, run_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")

    try:
        return retrieve_similar_chunks(db, run_id=run_id, query_text=query, top_k=top_k)
    except EmbeddingMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ---------------------------------------------------------------------------
# AI Provider Status Endpoint (S23 Item 4)
# ---------------------------------------------------------------------------

@router.get("/ai/status")
def get_ai_status():
    """
    Returns active AI provider status (Session 23 Item 4).
    Derives state from active cached provider instances. Never returns 500.
    """
    from embeddings import get_embedding_provider
    from rag.llm import get_llm_provider

    message = None
    configured = True
    emb_info = {"provider": "unknown", "model": "unknown", "dimension": 0}
    llm_info = {"provider": "unknown", "model": "unknown"}

    try:
        emb_prov = get_embedding_provider()
        emb_info = {
            "provider": getattr(emb_prov, "provider_id", getattr(emb_prov, "name", "unknown")),
            "model": getattr(emb_prov, "model_name", getattr(emb_prov, "name", "unknown")),
            "dimension": getattr(emb_prov, "dimension", 0),
        }
    except Exception as exc:
        configured = False
        message = str(exc)

    try:
        llm_prov = get_llm_provider()
        llm_info = {
            "provider": getattr(llm_prov, "provider_id", getattr(llm_prov, "name", "unknown")),
            "model": getattr(llm_prov, "model_name", "unknown"),
        }
    except Exception as exc:
        configured = False
        if not message:
            message = str(exc)

    _TEST_EMBEDDING_IDS = frozenset({"test", "test-deterministic"})
    _TEST_LLM_IDS = frozenset({"test", "test-llm"})
    emb_is_test = emb_info["provider"] in _TEST_EMBEDDING_IDS
    llm_is_test = llm_info["provider"] in _TEST_LLM_IDS

    if not configured:
        mode = "error"
    elif emb_is_test and llm_is_test:
        mode = "test"
    elif not emb_is_test and not llm_is_test:
        mode = "real"
    else:
        # Exactly one side is a test provider — mixed configuration
        mode = "mixed"

    resp = {
        "mode": mode,
        "embedding": emb_info,
        "llm": llm_info,
        "configured": configured,
    }
    if message:
        sanitized = message.split("\n")[0]
        if "API_KEY" in sanitized:
            sanitized = sanitized.split(":")[0] + ": environment variable is missing or invalid."
        resp["message"] = sanitized

    return resp


# ---------------------------------------------------------------------------
# RAG Evidence-Grounded Question Answering Endpoint (S21)
# ---------------------------------------------------------------------------

@router.post("/analyses/{run_id}/ask", response_model=AskResponse)
def ask_repository_question_route(
    run_id: str,
    req: AskRequest,
    db: Session = Depends(get_db_session),
):
    analysis = get_analysis_by_run_id(db, run_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")

    try:
        return answer_repository_question(db, run_id=run_id, question=req.question, top_k=req.top_k)
    except EmbeddingMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except LLMError as err:
        raise HTTPException(status_code=err.status_code, detail=err.detail)
    except (ValueError, RuntimeError) as err:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="LLM provider is not configured.")
