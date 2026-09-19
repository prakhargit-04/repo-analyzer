"""
Pydantic schemas for the FastAPI backend API (S15).
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SubmitAnalysisRequest(BaseModel):
    repo_url: str = Field(..., description="Git repository remote URL (HTTP/HTTPS/git)", json_schema_extra={"example": "https://github.com/pytest-dev/iniconfig"})
    commit_sha: Optional[str] = Field(None, description="Optional commit SHA to analyze", json_schema_extra={"example": "00e7d87c7353b1ffecc4cd55f19acfffedd5233e"})



class JobStageItem(BaseModel):
    stage_name: str
    status: str
    detail: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class JobStatusResponse(BaseModel):
    job_id: str
    repo_url: str
    commit_sha: Optional[str] = None
    status: str
    current_stage: str
    progress: int
    cache_hit: bool
    error_message: Optional[str] = None
    run_id: Optional[str] = None
    stages: List[JobStageItem] = []
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str


class ErrorResponse(BaseModel):
    error: str
    detail: str


class PaginationMeta(BaseModel):
    total: int
    limit: int
    offset: int


class GraphResponse(BaseModel):
    run_id: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    pagination: PaginationMeta


class FindingsResponse(BaseModel):
    run_id: str
    findings: List[Dict[str, Any]]
    pagination: PaginationMeta


class FilesResponse(BaseModel):
    run_id: str
    files: List[Dict[str, Any]]
    pagination: PaginationMeta


class FileDetailResponse(BaseModel):
    run_id: str
    file_path: str
    language: Optional[str] = None
    parse_error: Optional[str] = None
    entities: List[Dict[str, Any]] = []
