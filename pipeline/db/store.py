"""
Persistence store functions for the repository analysis layer.

All functions take a SQLAlchemy Session as first argument and operate within
the caller's transaction. The caller is responsible for commit/rollback.

Public API:
  persist_analysis(session, result_dict)  -> run_id: str
  get_latest_analysis(session, repo_url)  -> dict | None
  get_analysis_by_run_id(session, run_id) -> dict | None
  get_all_runs_for_repo(session, repo_url) -> list[dict]

Design invariants:
  - Repository and Snapshot rows are upserted (get-or-create).
  - Each call to persist_analysis creates a *new* AnalysisRun row so
    re-analyses are always recorded without corrupting prior runs.
  - A failed/partial run is stored with status="failed"/"partial",
    not silently discarded.
  - The canonical JSON (result_dict) is fully recoverable from DB rows
    via get_analysis_by_run_id.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from .models import (
    Repository,
    Snapshot,
    AnalysisRun,
    AnalyzerResult,
    FileRecord,
    EntityRecord,
    GraphNode,
    GraphEdge,
    Finding,
    HealthScore,
    AnalysisJob,
    AnalysisJobStage,
)



# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _j(obj: Any) -> Optional[str]:
    """Safely serialize obj to JSON string, or None if obj is None."""
    return json.dumps(obj, sort_keys=True) if obj is not None else None


def _uj(s: Optional[str]) -> Any:
    """Safely deserialize JSON string to Python object, or None."""
    return json.loads(s) if s else None


def _get_or_create_repo(session: Session, repo_url: str) -> Repository:
    row = session.execute(
        select(Repository).where(Repository.repo_url == repo_url)
    ).scalar_one_or_none()
    if row is None:
        row = Repository(repo_url=repo_url)
        session.add(row)
        session.flush()  # populate .id before use
    return row


def _get_or_create_snapshot(
    session: Session,
    repository_id: str,
    snapshot_id: str,
    commit_sha: Optional[str],
    cache_key_basis: Optional[str],
) -> Snapshot:
    row = session.execute(
        select(Snapshot).where(
            Snapshot.repository_id == repository_id,
            Snapshot.snapshot_id == snapshot_id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = Snapshot(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            commit_sha=commit_sha,
            cache_key_basis=cache_key_basis,
        )
        session.add(row)
        session.flush()
    return row


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def persist_analysis(session: Session, result_dict: dict) -> str:
    """
    Persist a canonical analysis result to the database.

    Upserts the Repository and Snapshot rows, then inserts a new AnalysisRun
    plus all child rows (analyzer_results, file_records, entity_records,
    graph_nodes, graph_edges, findings, health_score).

    Returns the new analysis_runs.id (UUID string).

    The caller must commit() the session after this call succeeds, or
    rollback() on exception.
    """
    repo_url: str = result_dict.get("repository", "unknown")
    snapshot_id_val: str = result_dict.get("cache_snapshot_id", "unknown")
    commit_sha_val: Optional[str] = result_dict.get("commit_sha")
    cache_key_basis_val: Optional[str] = result_dict.get("cache_key_basis")

    # Upsert repository
    repo = _get_or_create_repo(session, repo_url)

    # Upsert snapshot
    snap = _get_or_create_snapshot(
        session,
        repository_id=repo.id,
        snapshot_id=snapshot_id_val,
        commit_sha=commit_sha_val,
        cache_key_basis=cache_key_basis_val,
    )

    # Parse analyzed_at_utc
    analyzed_at: Optional[datetime] = None
    analyzed_at_str = result_dict.get("analyzed_at_utc")
    if analyzed_at_str:
        try:
            analyzed_at = datetime.fromisoformat(analyzed_at_str)
        except ValueError:
            pass

    # Determine run status from analysis_status
    analysis_status = result_dict.get("analysis_status", "")
    run_status = {
        "complete": "complete",
        "partial": "partial",
        "failed": "failed",
    }.get(analysis_status, "partial")

    # Create analysis run
    run = AnalysisRun(
        snapshot_id=snap.id,
        status=run_status,
        schema_version=result_dict.get("schema_version", ""),
        cache_schema_version=result_dict.get("cache_schema_version", ""),
        analyzer_version=result_dict.get("analyzer_version", ""),
        languages=_j(result_dict.get("languages", [])),
        files_analyzed=result_dict.get("files_analyzed", 0),
        parse_errors_json=_j(result_dict.get("parse_errors", [])),
        analysis_status=analysis_status,
        analyzed_at_utc=analyzed_at,
    )
    session.add(run)
    session.flush()

    # --- analyzer_results ---
    static_analysis: dict = result_dict.get("static_analysis", {})
    _SKIP_KEYS = {"scope_policy", "production_files_analyzed", "test_files_excluded"}
    for tool_name, tool_data in static_analysis.items():
        if tool_name in _SKIP_KEYS or not isinstance(tool_data, dict):
            continue
        ar = AnalyzerResult(
            run_id=run.id,
            analyzer_name=tool_name,
            status=tool_data.get("status", "unknown"),
            provenance=tool_data.get("provenance", ""),
            results_json=_j(tool_data.get("results", [])),
            errors_json=_j(tool_data.get("errors", [])),
            metadata_json=_j(tool_data.get("metadata", {})),
        )
        session.add(ar)

    # --- file_records + entity_records ---
    graph_nodes_raw: List[dict] = result_dict.get("knowledge_graph", {}).get("nodes", [])
    # Build a mapping file_path -> list of function/class nodes for entities
    file_entity_map: Dict[str, List[dict]] = {}
    for node in graph_nodes_raw:
        if node.get("type") in ("function", "class", "import_target"):
            fp = node.get("file", "")
            if fp:
                file_entity_map.setdefault(fp, []).append(node)

    # Determine file language from extension
    def _lang(path: str) -> str:
        if path.endswith(".py"):
            return "python"
        elif path.endswith(".java"):
            return "java"
        elif path.endswith((".js", ".jsx")):
            return "javascript"
        elif path.endswith((".ts", ".tsx")):
            return "typescript"
        return "unknown"

    parse_errors_by_file: Dict[str, str] = {
        pe["file"]: pe["error"] for pe in result_dict.get("parse_errors", [])
    }

    file_node_ids: set = {
        n["id"] for n in graph_nodes_raw if n.get("type") == "file"
    }

    for node in graph_nodes_raw:
        if node.get("type") != "file":
            continue
        fp = node["id"]
        fr_row = FileRecord(
            run_id=run.id,
            file_path=fp,
            language=_lang(fp),
            parse_error=parse_errors_by_file.get(fp),
        )
        session.add(fr_row)
        session.flush()

        for ent in file_entity_map.get(fp, []):
            er = EntityRecord(
                file_record_id=fr_row.id,
                entity_type=ent.get("type", "unknown"),
                name=ent.get("name", ""),
                node_id=ent.get("id"),
                start_line=ent.get("start_line"),
                end_line=ent.get("end_line"),
                class_owner=ent.get("class_owner"),
                provenance=ent.get("provenance"),
                extra_json=_j({
                    k: v for k, v in ent.items()
                    if k not in ("type", "name", "id", "file", "start_line",
                                 "end_line", "class_owner", "provenance")
                }),
            )
            session.add(er)

    # --- graph_nodes ---
    for node in graph_nodes_raw:
        gn = GraphNode(
            run_id=run.id,
            node_id=node.get("id", ""),
            node_type=node.get("type", "unknown"),
            name=node.get("name"),
            file_path=node.get("file"),
            start_line=node.get("start_line"),
            end_line=node.get("end_line"),
            provenance=node.get("provenance"),
            attributes_json=_j({
                k: v for k, v in node.items()
                if k not in ("id", "type", "name", "file", "start_line", "end_line", "provenance")
            }),
        )
        session.add(gn)

    # --- graph_edges ---
    graph_edges_raw: List[dict] = result_dict.get("knowledge_graph", {}).get("edges", [])
    for edge in graph_edges_raw:
        ge = GraphEdge(
            run_id=run.id,
            source=edge.get("source", ""),
            target=edge.get("target", ""),
            relation=edge.get("relation", ""),
            confidence=edge.get("confidence"),
            provenance=edge.get("provenance"),
            attributes_json=_j({
                k: v for k, v in edge.items()
                if k not in ("source", "target", "relation", "confidence", "provenance")
            }),
        )
        session.add(ge)

    # --- findings (from graph finding nodes) ---
    for node in graph_nodes_raw:
        if node.get("type") != "finding":
            continue
        f = Finding(
            run_id=run.id,
            analyzer=node.get("analyzer", ""),
            rule_id=node.get("rule_id"),
            severity=node.get("severity"),
            file_path=node.get("file"),
            line=node.get("line"),
            message=node.get("message"),
            provenance=node.get("provenance"),
            raw_json=_j(node),
        )
        session.add(f)

    # --- health_score ---
    hs_dict: dict = result_dict.get("health_score", {})
    if hs_dict:
        hs = HealthScore(
            run_id=run.id,
            composite_health_score=hs_dict.get("composite_health_score"),
            status=hs_dict.get("status", "unknown"),
            sub_scores_json=_j(hs_dict.get("sub_scores")),
            component_statuses_json=_j(hs_dict.get("component_statuses")),
            weights_used_json=_j(hs_dict.get("weights_used")),
            weights_renormalized=bool(hs_dict.get("weights_renormalized", False)),
            missing_components_json=_j(hs_dict.get("missing_components")),
            formula=hs_dict.get("formula"),
            scope_policy=hs_dict.get("scope_policy"),
        )
        session.add(hs)

    session.flush()
    return run.id


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def _run_to_dict(session: Session, run: AnalysisRun) -> dict:
    """Reconstruct a dict approximating the canonical JSON from DB rows."""
    snap: Snapshot = run.snapshot
    repo: Repository = snap.repository

    # analyzer_results -> static_analysis shape
    static_analysis: dict = {}
    for ar in run.analyzer_results:
        static_analysis[ar.analyzer_name] = {
            "status": ar.status,
            "results": _uj(ar.results_json) or [],
            "provenance": ar.provenance,
            "errors": _uj(ar.errors_json) or [],
            "metadata": _uj(ar.metadata_json) or {},
        }

    # graph nodes + edges
    nodes = []
    for gn in run.graph_nodes:
        n: dict = {
            "id": gn.node_id,
            "type": gn.node_type,
            "provenance": gn.provenance,
        }
        if gn.name is not None:
            n["name"] = gn.name
        if gn.file_path is not None:
            n["file"] = gn.file_path
        if gn.start_line is not None:
            n["start_line"] = gn.start_line
        if gn.end_line is not None:
            n["end_line"] = gn.end_line
        extra = _uj(gn.attributes_json) or {}
        n.update(extra)
        nodes.append(n)

    edges = []
    for ge in run.graph_edges:
        e: dict = {
            "source": ge.source,
            "target": ge.target,
            "relation": ge.relation,
            "confidence": ge.confidence,
            "provenance": ge.provenance,
        }
        extra = _uj(ge.attributes_json) or {}
        e.update(extra)
        edges.append(e)

    # health score
    hs_dict: dict = {}
    if run.health_score:
        hs = run.health_score
        hs_dict = {
            "composite_health_score": hs.composite_health_score,
            "status": hs.status,
            "sub_scores": _uj(hs.sub_scores_json) or {},
            "component_statuses": _uj(hs.component_statuses_json) or {},
            "weights_used": _uj(hs.weights_used_json) or {},
            "weights_renormalized": hs.weights_renormalized,
            "missing_components": _uj(hs.missing_components_json) or [],
            "formula": hs.formula,
            "scope_policy": hs.scope_policy,
        }

    return {
        "run_id": run.id,
        "schema_version": run.schema_version,
        "cache_schema_version": run.cache_schema_version,
        "analyzer_version": run.analyzer_version,
        "repository": repo.repo_url,
        "commit_sha": snap.commit_sha,
        "cache_snapshot_id": snap.snapshot_id,
        "cache_key_basis": snap.cache_key_basis,
        "analyzed_at_utc": run.analyzed_at_utc.isoformat() if run.analyzed_at_utc else None,
        "languages": _uj(run.languages) or [],
        "analysis_status": run.analysis_status,
        "files_analyzed": run.files_analyzed,
        "parse_errors": _uj(run.parse_errors_json) or [],
        "static_analysis": static_analysis,
        "knowledge_graph": {"nodes": nodes, "edges": edges},
        "health_score": hs_dict,
    }


def get_latest_analysis(session: Session, repo_url: str) -> Optional[dict]:
    """Return the most recent complete (or partial) analysis run for a repo, or None."""
    run = session.execute(
        select(AnalysisRun)
        .join(AnalysisRun.snapshot)
        .join(Snapshot.repository)
        .where(Repository.repo_url == repo_url)
        .where(AnalysisRun.status.in_(["complete", "partial"]))
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if run is None:
        return None
    return _run_to_dict(session, run)


def get_analysis_by_run_id(session: Session, run_id: str) -> Optional[dict]:
    """Return a specific analysis run by its UUID, or None."""
    run = session.execute(
        select(AnalysisRun).where(AnalysisRun.id == run_id)
    ).scalar_one_or_none()
    if run is None:
        return None
    return _run_to_dict(session, run)


def get_all_runs_for_repo(session: Session, repo_url: str) -> List[dict]:
    """Return all analysis runs for a repo, newest first."""
    runs = session.execute(
        select(AnalysisRun)
        .join(AnalysisRun.snapshot)
        .join(Snapshot.repository)
        .where(Repository.repo_url == repo_url)
        .order_by(AnalysisRun.created_at.desc())
    ).scalars().all()
    return [_run_to_dict(session, r) for r in runs]


# ---------------------------------------------------------------------------
# Job Management (S15)
# ---------------------------------------------------------------------------

STAGE_PROGRESS_MAP = {
    "queued": 0,
    "cloning": 15,
    "parsing": 30,
    "analyzing": 50,
    "graph-building": 75,
    "scoring": 85,
    "embedding": 95,
    "completed": 100,
    "partial": 100,
    "failed": 100,
}

ALL_STAGES = [
    "cloning", "parsing", "analyzing", "graph-building", "scoring", "embedding"
]


def create_job(session: Session, repo_url: str, commit_sha: Optional[str] = None) -> AnalysisJob:
    """Create a new AnalysisJob and its stage tracking rows in 'queued' status."""
    job = AnalysisJob(
        repo_url=repo_url,
        commit_sha=commit_sha,
        status="queued",
        current_stage="queued",
        progress=0,
    )
    session.add(job)
    session.flush()

    # Pre-populate stage rows
    for stage_name in ALL_STAGES:
        st = AnalysisJobStage(
            job_id=job.id,
            stage_name=stage_name,
            status="pending",
        )
        session.add(st)
    session.flush()

    _sync_job_stages_json(session, job)
    return job


def get_job_model(session: Session, job_id: str) -> Optional[AnalysisJob]:
    """Fetch AnalysisJob ORM model instance by ID."""
    return session.execute(
        select(AnalysisJob).where(AnalysisJob.id == job_id)
    ).scalar_one_or_none()


def get_job_dict(session: Session, job_id: str) -> Optional[dict]:
    """Fetch job by ID and format as a structured dict for API responses."""
    job = get_job_model(session, job_id)
    if not job:
        return None
    return _job_to_dict(session, job)


def get_active_job_for_repo(session: Session, repo_url: str, commit_sha: Optional[str] = None) -> Optional[AnalysisJob]:
    """Return any active (queued or in-progress) job for a repo/commit if one exists."""
    stmt = (
        select(AnalysisJob)
        .where(AnalysisJob.repo_url == repo_url)
        .where(AnalysisJob.status.in_(["queued", "cloning", "parsing", "analyzing", "graph-building", "scoring", "embedding"]))
    )
    if commit_sha:
        stmt = stmt.where(AnalysisJob.commit_sha == commit_sha)
    stmt = stmt.order_by(AnalysisJob.created_at.desc())
    return session.execute(stmt).scalars().first()



def find_completed_run_by_sha(session: Session, repo_url: str, commit_sha: str) -> Optional[dict]:
    """Find a completed analysis run matching repo_url and commit_sha."""
    run = session.execute(
        select(AnalysisRun)
        .join(AnalysisRun.snapshot)
        .join(Snapshot.repository)
        .where(Repository.repo_url == repo_url)
        .where(Snapshot.commit_sha == commit_sha)
        .where(AnalysisRun.status.in_(["complete", "partial"]))
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if run is None:
        return None
    return _run_to_dict(session, run)


def update_job_stage(
    session: Session,
    job_id: str,
    stage_name: str,
    stage_status: str,  # running | completed | skipped | failed
    detail: Optional[str] = None,
    progress: Optional[int] = None,
) -> None:
    """Update job current stage and stage status row."""
    job = get_job_model(session, job_id)
    if not job:
        return

    now = datetime.now(timezone.utc)
    if job.started_at is None:
        job.started_at = now

    job.current_stage = stage_name
    if stage_status in ("running", "completed", "skipped", "failed"):
        if stage_name in ("cloning", "parsing", "analyzing", "graph-building", "scoring", "embedding"):
            job.status = stage_name

    prog = progress if progress is not None else STAGE_PROGRESS_MAP.get(stage_name, job.progress)
    job.progress = max(job.progress, prog)
    job.updated_at = now

    # Update individual stage record
    stage_row = session.execute(
        select(AnalysisJobStage).where(
            AnalysisJobStage.job_id == job_id,
            AnalysisJobStage.stage_name == stage_name,
        )
    ).scalar_one_or_none()

    if stage_row:
        stage_row.status = stage_status
        if detail is not None:
            stage_row.detail = detail
        if stage_status == "running" and stage_row.started_at is None:
            stage_row.started_at = now
        elif stage_status in ("completed", "skipped", "failed"):
            if stage_row.started_at is None:
                stage_row.started_at = now
            stage_row.completed_at = now

    _sync_job_stages_json(session, job)
    session.flush()


def complete_job(
    session: Session,
    job_id: str,
    run_id: str,
    status: str = "completed",
    cache_hit: bool = False,
) -> None:
    """Mark job as completed (or partial) linked to run_id."""
    job = get_job_model(session, job_id)
    if not job:
        return
    now = datetime.now(timezone.utc)
    job.status = status
    job.current_stage = status
    job.progress = 100
    job.run_id = run_id
    job.cache_hit = cache_hit
    job.completed_at = now
    job.updated_at = now

    # Mark remaining stages completed or skipped
    for st in job.stages:
        if st.status in ("pending", "running"):
            st.status = "completed" if not cache_hit else "completed"
            if st.started_at is None:
                st.started_at = now
            st.completed_at = now

    _sync_job_stages_json(session, job)
    session.flush()


def fail_job(session: Session, job_id: str, error_message: str) -> None:
    """Mark job as failed with error message."""
    job = get_job_model(session, job_id)
    if not job:
        return
    now = datetime.now(timezone.utc)
    job.status = "failed"
    job.error_message = error_message
    job.completed_at = now
    job.updated_at = now

    # Mark current stage failed
    if job.current_stage:
        stage_row = session.execute(
            select(AnalysisJobStage).where(
                AnalysisJobStage.job_id == job_id,
                AnalysisJobStage.stage_name == job.current_stage,
            )
        ).scalar_one_or_none()
        if stage_row:
            stage_row.status = "failed"
            stage_row.detail = error_message
            stage_row.completed_at = now

    _sync_job_stages_json(session, job)
    session.flush()


def _sync_job_stages_json(session: Session, job: AnalysisJob) -> None:
    """Serialize stages list into stages_json on the AnalysisJob model."""
    stages = session.execute(
        select(AnalysisJobStage)
        .where(AnalysisJobStage.job_id == job.id)
        .order_by(AnalysisJobStage.id)
    ).scalars().all()

    stages_list = [
        {
            "stage_name": s.stage_name,
            "status": s.status,
            "detail": s.detail,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        }
        for s in stages
    ]
    job.stages_json = json.dumps(stages_list, sort_keys=True)


def _job_to_dict(session: Session, job: AnalysisJob) -> dict:
    """Format job object to standard dictionary."""
    stages_data = _uj(job.stages_json) or []
    return {
        "job_id": job.id,
        "repo_url": job.repo_url,
        "commit_sha": job.commit_sha,
        "status": job.status,
        "current_stage": job.current_stage,
        "progress": job.progress,
        "cache_hit": job.cache_hit,
        "error_message": job.error_message,
        "run_id": job.run_id,
        "stages": stages_data,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }

