"use client";

import { use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  getJob,
  getJobStatus,
  getAnalysis,
  CanonicalAnalysisPayload,
  JobStatusResponse,
  JobStatusSummary,
} from "@/lib/api";
import { ProgressStepper } from "@/components/ProgressStepper";
import { GraphView } from "@/components/GraphView";

export default function AnalysisDetailsPage({
  params: paramsPromise,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(paramsPromise);

  const [jobSummary, setJobSummary] = useState<JobStatusSummary | null>(null);
  const [detailedJob, setDetailedJob] = useState<JobStatusResponse | null>(null);
  const [analysis, setAnalysis] = useState<CanonicalAnalysisPayload | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const pollingTimerRef = useRef<NodeJS.Timeout | null>(null);

  const stopPolling = () => {
    if (pollingTimerRef.current) {
      clearInterval(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }
  };

  useEffect(() => {
    let isMounted = true;

    async function loadInitial() {
      try {
        setLoading(true);
        setError(null);

        // Try reading job status first
        try {
          const jSummary = await getJobStatus(id);
          if (!isMounted) return;
          setJobSummary(jSummary);

          const jDetail = await getJob(id);
          if (!isMounted) return;
          setDetailedJob(jDetail);

          // If job is already completed or partial and has a run_id
          if (
            (jSummary.status === "completed" || jSummary.status === "partial") &&
            jSummary.run_id
          ) {
            const result = await getAnalysis(jSummary.run_id);
            if (!isMounted) return;
            setAnalysis(result);
            setLoading(false);
            return;
          }

          if (jSummary.status === "failed") {
            setLoading(false);
            return;
          }
        } catch {
          // If job fetch failed, attempt direct analysis run_id fetch
          try {
            const result = await getAnalysis(id);
            if (!isMounted) return;
            setAnalysis(result);
            setJobSummary({
              job_id: id,
              repo_url: result.repository,
              status: result.analysis_status || "completed",
              current_stage: result.analysis_status || "completed",
              progress: 100,
              cache_hit: false,
              run_id: id,
            });
            setLoading(false);
            return;
          } catch (err: unknown) {
            if (!isMounted) return;
            const msg = err instanceof Error ? err.message : `Failed to fetch job or analysis for ID '${id}'`;
            setError(msg);
            setLoading(false);
            return;
          }
        }

        setLoading(false);

        // Start polling loop for in-progress jobs
        pollingTimerRef.current = setInterval(async () => {
          try {
            const latestSummary = await getJobStatus(id);
            if (!isMounted) return;
            setJobSummary(latestSummary);

            const latestDetail = await getJob(id);
            if (!isMounted) return;
            setDetailedJob(latestDetail);

            // Terminal state checks -> stop polling
            if (
              latestSummary.status === "completed" ||
              latestSummary.status === "partial"
            ) {
              stopPolling();
              if (latestSummary.run_id) {
                const result = await getAnalysis(latestSummary.run_id);
                if (isMounted) setAnalysis(result);
              }
            } else if (latestSummary.status === "failed") {
              stopPolling();
            }
          } catch (pollErr: unknown) {
            // Temporary network error during polling
            console.warn("Polling error:", pollErr);
          }
        }, 1500);
      } catch (err: unknown) {
        if (!isMounted) return;
        const msg = err instanceof Error ? err.message : "An unexpected error occurred";
        setError(msg);
        setLoading(false);
      }

    }

    loadInitial();

    return () => {
      isMounted = false;
      stopPolling();
    };
  }, [id]);

  if (loading && !jobSummary && !analysis) {
    return (
      <main className="min-h-screen bg-slate-950 text-white p-8 flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-400">Loading analysis data from backend...</p>
        </div>
      </main>
    );
  }

  if (error && !jobSummary && !analysis) {
    return (
      <main className="min-h-screen bg-slate-950 text-white p-8">
        <div className="max-w-4xl mx-auto">
          <Link href="/" className="text-slate-400 hover:text-white text-sm mb-6 inline-block">
            ← Back to Home
          </Link>

          <div className="bg-rose-950/60 border border-rose-800 rounded-xl p-6 text-rose-200">
            <h2 className="text-xl font-bold mb-2">API Error</h2>
            <p className="text-sm">{error}</p>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 text-white p-8">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <Link href="/" className="text-slate-400 hover:text-white text-sm">
            ← Back to Home
          </Link>

          <Link href="/history" className="text-slate-400 hover:text-white text-sm">
            Analysis History →
          </Link>
        </div>

        <h1 className="text-4xl font-bold">Repository Intelligence</h1>
        <p className="text-slate-400 mt-1">Live Backend Analysis & Knowledge Graph</p>

        {/* Repository info header */}
        <div className="mt-6 bg-slate-900 border border-slate-800 rounded-xl p-6">
          <p className="text-slate-400 text-sm">Repository</p>
          <p className="text-lg mt-1 font-medium">{jobSummary?.repo_url || analysis?.repository || "Unknown"}</p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 text-sm">
            <div>
              <span className="text-slate-400">Commit SHA: </span>
              <span className="font-mono text-slate-200">
                {jobSummary?.commit_sha || analysis?.commit_sha || "HEAD"}
              </span>
            </div>
            <div>
              <span className="text-slate-400">Job ID: </span>
              <span className="font-mono text-slate-200">{id}</span>
            </div>
          </div>
        </div>

        {/* Real stage progress stepper */}
        <div className="mt-6">
          <ProgressStepper
            status={jobSummary?.status || analysis?.analysis_status || "queued"}
            currentStage={jobSummary?.current_stage || "queued"}
            progress={jobSummary?.progress || 0}
            cacheHit={jobSummary?.cache_hit}
            errorMessage={jobSummary?.error_message}
            stages={detailedJob?.stages}
          />
        </div>

        {/* Analysis Results View */}
        {analysis && (
          <div className="mt-8 space-y-8">
            {/* Top metrics grid */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <p className="text-slate-400 text-sm">Health Score</p>
                <p className="text-4xl font-bold mt-2">
                  {analysis.health_score?.composite_health_score ?? "N/A"}
                </p>
                <p className="text-sm text-slate-400 mt-2 capitalize">
                  {analysis.health_score?.status || analysis.analysis_status}
                </p>
              </div>

              <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <p className="text-slate-400 text-sm">Files Analyzed</p>
                <p className="text-4xl font-bold mt-2">{analysis.files_analyzed}</p>
              </div>

              <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <p className="text-slate-400 text-sm">Graph Nodes</p>
                <p className="text-4xl font-bold mt-2">
                  {analysis.knowledge_graph_summary?.total_nodes || analysis.knowledge_graph?.nodes?.length || 0}
                </p>
              </div>

              <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <p className="text-slate-400 text-sm">Graph Edges</p>
                <p className="text-4xl font-bold mt-2">
                  {analysis.knowledge_graph_summary?.total_edges || analysis.knowledge_graph?.edges?.length || 0}
                </p>
              </div>
            </div>

            {/* Health Breakdown */}
            {analysis.health_score?.sub_scores && (
              <div>
                <h2 className="text-2xl font-bold mb-4">Health Breakdown</h2>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                  <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                    <p className="text-slate-400 text-sm">Complexity</p>
                    <p className="text-3xl font-bold mt-2">
                      {analysis.health_score.sub_scores.complexity ?? "N/A"}
                    </p>
                  </div>

                  <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                    <p className="text-slate-400 text-sm">Maintainability</p>
                    <p className="text-3xl font-bold mt-2">
                      {analysis.health_score.sub_scores.maintainability ?? "N/A"}
                    </p>
                  </div>

                  <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                    <p className="text-slate-400 text-sm">Security</p>
                    <p className="text-3xl font-bold mt-2">
                      {analysis.health_score.sub_scores.security ?? "N/A"}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Knowledge Graph Summary */}
            {analysis.knowledge_graph_summary && (
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <h2 className="text-2xl font-bold">Knowledge Graph Metrics</h2>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-5 mt-5">
                  <div>
                    <p className="text-slate-400 text-sm">Total Nodes</p>
                    <p className="text-2xl font-bold">{analysis.knowledge_graph_summary.total_nodes}</p>
                  </div>
                  <div>
                    <p className="text-slate-400 text-sm">Total Edges</p>
                    <p className="text-2xl font-bold">{analysis.knowledge_graph_summary.total_edges}</p>
                  </div>
                  <div>
                    <p className="text-slate-400 text-sm">Call Edges</p>
                    <p className="text-2xl font-bold">{analysis.knowledge_graph_summary.call_edges_total}</p>
                  </div>
                  <div>
                    <p className="text-slate-400 text-sm">Resolved</p>
                    <p className="text-2xl font-bold">{analysis.knowledge_graph_summary.call_edges_resolved_pct}%</p>
                  </div>
                </div>
              </div>
            )}

            {/* ReactFlow Architecture Graph */}
            <div>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-2xl font-bold">Repository Architecture</h2>
                  <p className="text-slate-400 text-sm mt-1">
                    Live call & file graph relationships from API
                  </p>
                </div>
                <div className="text-sm text-slate-400">
                  {analysis.knowledge_graph?.nodes?.filter((n) => n.type === "file").length || 0} files
                </div>
              </div>

              <GraphView
                nodes={analysis.knowledge_graph?.nodes || []}
                edges={analysis.knowledge_graph?.edges || []}
              />
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
