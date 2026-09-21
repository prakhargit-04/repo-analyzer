import { components } from "@/types/api";

export type SubmitAnalysisRequest = components["schemas"]["SubmitAnalysisRequest"];
export type JobStatusResponse = components["schemas"]["JobStatusResponse"];
export type JobStageItem = components["schemas"]["JobStageItem"];
export type HealthResponse = components["schemas"]["HealthResponse"];
export type GraphResponse = components["schemas"]["GraphResponse"];
export type FindingsResponse = components["schemas"]["FindingsResponse"];
export type FilesResponse = components["schemas"]["FilesResponse"];
export type FileDetailResponse = components["schemas"]["FileDetailResponse"];

export interface JobStatusSummary {
  job_id: string;
  repo_url: string;
  commit_sha?: string | null;
  status: string;
  current_stage: string;
  progress: number;
  cache_hit: boolean;
  error_message?: string | null;
  run_id?: string | null;
}


export interface AnalysisSummaryData {
  run_id: string;
  repository: string;
  commit_sha: string;
  health_score: {
    composite_health_score?: number | null;
    status?: string;
    sub_scores?: Record<string, number>;
    component_statuses?: Record<string, string>;
  };
  knowledge_graph_summary: {
    total_nodes?: number;
    total_edges?: number;
    call_edges_total?: number;
    call_edges_resolved_pct?: number;
  };
  files_analyzed: number;
  languages: string[];
}

export interface CanonicalAnalysisPayload {
  schema_version: string;
  cache_schema_version: string;
  analyzer_version: string;
  repository: string;
  commit_sha: string;
  cache_snapshot_id: string;
  cache_key_basis: string;
  analyzed_at_utc: string;
  languages: string[];
  analysis_status: string;
  files_analyzed: number;
  parse_errors: Array<{ file: string; error: string }>;
  static_analysis: Record<string, unknown>;
  knowledge_graph_summary: {
    total_nodes: number;
    total_edges: number;
    call_edges_total: number;
    call_edges_resolved_pct: number;
  };
  knowledge_graph: {
    nodes: Array<{
      id: string;
      type?: string;
      name?: string;
      file?: string;
      start_line?: number;
      end_line?: number;
      provenance?: string;
      [key: string]: unknown;
    }>;
    edges: Array<{
      source: string;
      target: string;
      relation?: string;
      confidence?: string;
      provenance?: string;
      [key: string]: unknown;
    }>;
  };
  health_score: {
    composite_health_score: number;
    status: string;
    sub_scores: {
      complexity?: number;
      maintainability?: number;
      security?: number;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  };
  [key: string]: unknown;
}


const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = `HTTP ${res.status}: ${res.statusText}`;
    try {
      const errJson = await res.json();
      if (errJson.detail) {
        errorDetail = typeof errJson.detail === "string" ? errJson.detail : JSON.stringify(errJson.detail);
      } else if (errJson.error) {
        errorDetail = errJson.error;
      }
    } catch {
      // Use fallback errorDetail
    }
    throw new Error(errorDetail);
  }
  return res.json() as Promise<T>;
}

export async function submitAnalysis(
  payload: SubmitAnalysisRequest
): Promise<JobStatusResponse> {
  const res = await fetch(`${API_BASE_URL}/api/v1/analyses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<JobStatusResponse>(res);
}

export async function getJobStatus(jobId: string): Promise<JobStatusSummary> {
  const res = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/status`, {
    cache: "no-store",
  });
  return handleResponse<JobStatusSummary>(res);
}

export async function getJob(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}`, {
    cache: "no-store",
  });
  return handleResponse<JobStatusResponse>(res);
}

export async function getAnalysis(runId: string): Promise<CanonicalAnalysisPayload> {
  const res = await fetch(`${API_BASE_URL}/api/v1/analyses/${runId}`, {
    cache: "no-store",
  });
  return handleResponse<CanonicalAnalysisPayload>(res);
}

export async function getAnalysisSummary(runId: string): Promise<AnalysisSummaryData> {
  const res = await fetch(`${API_BASE_URL}/api/v1/analyses/${runId}/summary`, {
    cache: "no-store",
  });
  return handleResponse<AnalysisSummaryData>(res);
}

export async function getAnalysisGraph(
  runId: string,
  params?: { node_type?: string; file_path?: string; limit?: number; offset?: number }
): Promise<GraphResponse> {
  const query = new URLSearchParams();
  if (params?.node_type) query.set("node_type", params.node_type);
  if (params?.file_path) query.set("file_path", params.file_path);
  if (params?.limit) query.set("limit", params.limit.toString());
  if (params?.offset) query.set("offset", params.offset.toString());

  const res = await fetch(`${API_BASE_URL}/api/v1/analyses/${runId}/graph?${query.toString()}`, {
    cache: "no-store",
  });
  return handleResponse<GraphResponse>(res);
}

export async function getAnalysisFindings(
  runId: string,
  params?: { analyzer?: string; severity?: string; limit?: number; offset?: number }
): Promise<FindingsResponse> {
  const query = new URLSearchParams();
  if (params?.analyzer) query.set("analyzer", params.analyzer);
  if (params?.severity) query.set("severity", params.severity);
  if (params?.limit) query.set("limit", params.limit.toString());
  if (params?.offset) query.set("offset", params.offset.toString());

  const res = await fetch(`${API_BASE_URL}/api/v1/analyses/${runId}/findings?${query.toString()}`, {
    cache: "no-store",
  });
  return handleResponse<FindingsResponse>(res);
}

export async function getAnalysisFiles(
  runId: string,
  params?: { limit?: number; offset?: number }
): Promise<FilesResponse> {
  const query = new URLSearchParams();
  if (params?.limit) query.set("limit", params.limit.toString());
  if (params?.offset) query.set("offset", params.offset.toString());

  const res = await fetch(`${API_BASE_URL}/api/v1/analyses/${runId}/files?${query.toString()}`, {
    cache: "no-store",
  });
  return handleResponse<FilesResponse>(res);
}

export async function getRepositoryRuns(repoUrl: string): Promise<{
  repo_url: string;
  total_runs: number;
  runs: Array<{
    run_id: string;
    commit_sha: string;
    analysis_status: string;
    analyzer_version: string;
    schema_version: string;
    analyzed_at_utc?: string;
    files_analyzed: number;
    languages: string[];
  }>;
}> {
  const query = new URLSearchParams({ repo_url: repoUrl });
  const res = await fetch(`${API_BASE_URL}/api/v1/repositories/runs?${query.toString()}`, {
    cache: "no-store",
  });
  return handleResponse(res);
}
