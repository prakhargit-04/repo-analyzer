"""
FastAPI route definitions for repository analysis API (S15).
"""
from __future__ import annotations
import os
import sys
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from clone import is_remote_repo_url, is_safe_repo_url, resolve_remote_sha
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
    get_latest_analysis,
    get_all_runs_for_repo,
    complete_job,
)
from worker import get_worker_queue
from api.schemas import (
    SubmitAnalysisRequest,
    JobStatusResponse,
    HealthResponse,
    GraphResponse,
    FindingsResponse,
    FilesResponse,
    FileDetailResponse,
)

router = APIRouter(prefix="/api/v1", tags=["repository-analysis"])


def get_db_session():
    db_url = os.environ.get("DATABASE_URL", "sqlite:///repo_analyzer.db")
    engine = get_engine(db_url)
    SessionLocal = get_session_factory(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_cache_dir() -> str:
    return os.environ.get(
        "CACHE_DIR",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", ".cache"),
    )


# ---------------------------------------------------------------------------
# Health & Readiness
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
def health_check():
    return {"status": "ok", "version": "0.15.0", "database": "configured"}


@router.get("/readiness", response_model=HealthResponse)
def readiness_check(db: Session = Depends(get_db_session)):
    try:
        db.execute(select(1))
        db_status = "connected"
    except Exception:
        db_status = "error"
    return {"status": "ready" if db_status == "connected" else "not_ready", "version": "0.15.0", "database": db_status}


# ---------------------------------------------------------------------------
# Submit Repository Analysis
# ---------------------------------------------------------------------------

@router.post("/analyses", status_code=status.HTTP_202_ACCEPTED)
def submit_analysis(
    req: SubmitAnalysisRequest,
    db: Session = Depends(get_db_session),
):
    repo_url = req.repo_url.strip()

    # Reject local directory paths explicitly
    if not is_remote_repo_url(repo_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Local file paths are not accepted via the API. Please provide a remote Git URL (https://, http://, git@)."
        )

    if not is_safe_repo_url(repo_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or unsafe repository URL format: '{repo_url}'"
        )

    # 1. Pre-clone SHA resolution via git ls-remote
    resolved_sha = req.commit_sha
    if not resolved_sha:
        resolved_sha = resolve_remote_sha(repo_url)

    # 2. Check cache hit for resolved SHA
    if resolved_sha:
        cached_run = find_completed_run_by_sha(db, repo_url, resolved_sha)
        if cached_run:
            # Immediate cache hit: create job, link run_id, mark completed with cache_hit=True
            job = create_job(db, repo_url, commit_sha=resolved_sha)
            complete_job(db, job.id, run_id=cached_run["run_id"], status="completed", cache_hit=True)
            db.commit()
            job_data = get_job_dict(db, job.id)
            return job_data

    # 3. Check for active (queued/running) duplicate job
    active_job = get_active_job_for_repo(db, repo_url, req.commit_sha)
    if active_job:
        job_data = get_job_dict(db, active_job.id)
        return job_data

    # 4. Enqueue new analysis job
    job = create_job(db, repo_url, commit_sha=req.commit_sha)
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
    analysis = get_latest_analysis(db, repo_url)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No completed analysis found for repository '{repo_url}'")
    return analysis


@router.get("/repositories/runs")
def list_repository_runs(
    repo_url: str = Query(..., description="Repository URL"),
    db: Session = Depends(get_db_session),
):
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
    analysis = get_analysis_by_run_id(db, run_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")
    return {
        "run_id": analysis["run_id"],
        "repository": analysis["repository"],
        "commit_sha": analysis["commit_sha"],
        "health_score": analysis.get("health_score", {}),
        "knowledge_graph_summary": analysis.get("knowledge_graph_summary", {}),
        "files_analyzed": analysis["files_analyzed"],
        "languages": analysis["languages"],
    }


@router.get("/analyses/{run_id}/graph", response_model=GraphResponse)
def get_analysis_graph(
    run_id: str,
    node_type: Optional[str] = Query(None, description="Filter nodes by type (function, class, file, finding, etc.)"),
    file_path: Optional[str] = Query(None, description="Filter nodes by file path"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
):
    analysis = get_analysis_by_run_id(db, run_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")

    all_nodes = analysis.get("knowledge_graph", {}).get("nodes", [])
    all_edges = analysis.get("knowledge_graph", {}).get("edges", [])

    filtered_nodes = all_nodes
    if node_type:
        filtered_nodes = [n for n in filtered_nodes if n.get("type") == node_type]
    if file_path:
        filtered_nodes = [n for n in filtered_nodes if n.get("file") == file_path]

    total = len(filtered_nodes)
    paginated_nodes = filtered_nodes[offset : offset + limit]

    node_ids = {n["id"] for n in paginated_nodes}
    paginated_edges = [e for e in all_edges if e.get("source") in node_ids or e.get("target") in node_ids]

    return {
        "run_id": run_id,
        "nodes": paginated_nodes,
        "edges": paginated_edges,
        "pagination": {"total": total, "limit": limit, "offset": offset},
    }


@router.get("/analyses/{run_id}/findings", response_model=FindingsResponse)
def get_analysis_findings(
    run_id: str,
    analyzer: Optional[str] = Query(None, description="Filter by analyzer tool name (bandit, semgrep, gitleaks)"),
    severity: Optional[str] = Query(None, description="Filter by severity (HIGH, MEDIUM, LOW)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
):
    analysis = get_analysis_by_run_id(db, run_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")

    nodes = analysis.get("knowledge_graph", {}).get("nodes", [])
    findings = [n for n in nodes if n.get("type") == "finding"]

    if analyzer:
        findings = [f for f in findings if f.get("analyzer") == analyzer]
    if severity:
        findings = [f for f in findings if f.get("severity") == severity]

    total = len(findings)
    paginated = findings[offset : offset + limit]

    return {
        "run_id": run_id,
        "findings": paginated,
        "pagination": {"total": total, "limit": limit, "offset": offset},
    }


@router.get("/analyses/{run_id}/files", response_model=FilesResponse)
def get_analysis_files(
    run_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
):
    analysis = get_analysis_by_run_id(db, run_id)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis run '{run_id}' not found")

    nodes = analysis.get("knowledge_graph", {}).get("nodes", [])
    file_nodes = [n for n in nodes if n.get("type") == "file"]

    total = len(file_nodes)
    paginated = file_nodes[offset : offset + limit]

    return {
        "run_id": run_id,
        "files": paginated,
        "pagination": {"total": total, "limit": limit, "offset": offset},
    }


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
