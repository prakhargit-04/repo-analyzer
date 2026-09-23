"use client";

import { use, useEffect, useRef, useState, Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
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
import { RepositoryMeta } from "@/components/dashboard/RepositoryMeta";
import { StatsGrid } from "@/components/dashboard/StatsGrid";
import { HealthScorePanel } from "@/components/dashboard/HealthScorePanel";
import { FindingsPanel } from "@/components/dashboard/FindingsPanel";
import { FilesPanel } from "@/components/dashboard/FilesPanel";
import { repoDisplayName } from "@/lib/dashboard-utils";

// ─── Types ───────────────────────────────────────────────────────────────────

type TabId = "overview" | "findings" | "files";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "findings", label: "Findings" },
  { id: "files", label: "Files" },
];

// ─── Full-page spinner ────────────────────────────────────────────────────────

function FullPageSpinner({ label }: { label: string }) {
  return (
    <main className="min-h-screen bg-slate-950 text-white flex items-center justify-center">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-slate-400 text-sm">{label}</p>
      </div>
    </main>
  );
}

// ─── Inner dashboard (needs useSearchParams → inside Suspense) ────────────────

function AnalysisDashboard({ id }: { id: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = (searchParams.get("tab") as TabId) ?? "overview";

  // ── Core analysis state (preserved from S16) ──────────────────────────────
  const [jobSummary, setJobSummary] = useState<JobStatusSummary | null>(null);
  const [detailedJob, setDetailedJob] = useState<JobStatusResponse | null>(
    null
  );
  const [analysis, setAnalysis] = useState<CanonicalAnalysisPayload | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pollingTimerRef = useRef<NodeJS.Timeout | null>(null);

  const stopPolling = () => {
    if (pollingTimerRef.current) {
      clearInterval(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }
  };

  // ── Tab / cross-navigation helpers ──────────────────────────────────────────

  /**
   * Switch to a tab, clearing tab-specific URL params so the new tab starts
   * clean (no stale finding selection, filter, or pagination).
   */
  const setTab = (tab: TabId) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", tab);
    params.delete("finding");
    params.delete("file");
    params.delete("severity");
    params.delete("analyzer");
    params.delete("offset_f");
    params.delete("offset_fl");
    router.push(`/analyses/${id}?${params.toString()}`);
  };

  /** Navigate to the Files tab with a specific file pre-selected. */
  const goToFile = (filePath: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", "files");
    params.set("file", filePath);
    params.delete("finding");
    params.delete("offset_fl");
    router.push(`/analyses/${id}?${params.toString()}`);
  };

  /** Navigate to the Findings tab (no pre-applied filter). */
  const goToFindings = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", "findings");
    params.delete("file");
    params.delete("offset_f");
    router.push(`/analyses/${id}?${params.toString()}`);
  };

  // ── Initial load + polling (preserved from S16) ───────────────────────────
  useEffect(() => {
    let isMounted = true;

    async function loadInitial() {
      try {
        setLoading(true);
        setError(null);

        // 1. Try reading job status first
        try {
          const jSummary = await getJobStatus(id);
          if (!isMounted) return;
          setJobSummary(jSummary);

          const jDetail = await getJob(id);
          if (!isMounted) return;
          setDetailedJob(jDetail);

          // Already completed — load analysis result
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
          // 2. Job fetch failed — try treating `id` directly as a run_id
          try {
            const result = await getAnalysis(id);
            if (!isMounted) return;
            setAnalysis(result);
            setJobSummary({
              job_id: id,
              repo_url: result.repository,
              status: result.analysis_status ?? "completed",
              current_stage: result.analysis_status ?? "completed",
              progress: 100,
              cache_hit: false,
              run_id: id,
            });
            setLoading(false);
            return;
          } catch (err: unknown) {
            if (!isMounted) return;
            const msg =
              err instanceof Error
                ? err.message
                : `Failed to fetch job or analysis for ID '${id}'`;
            setError(msg);
            setLoading(false);
            return;
          }
        }

        setLoading(false);

        // 3. Start polling for in-progress jobs
        pollingTimerRef.current = setInterval(async () => {
          try {
            const latestSummary = await getJobStatus(id);
            if (!isMounted) return;
            setJobSummary(latestSummary);

            const latestDetail = await getJob(id);
            if (!isMounted) return;
            setDetailedJob(latestDetail);

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
            console.warn("Polling error:", pollErr);
          }
        }, 1500);
      } catch (err: unknown) {
        if (!isMounted) return;
        const msg =
          err instanceof Error ? err.message : "An unexpected error occurred";
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

  // ── Derived values ─────────────────────────────────────────────────────────
  const runId = jobSummary?.run_id ?? id;
  const repoLabel =
    repoDisplayName(analysis?.repository ?? jobSummary?.repo_url) ?? id;
  const isComplete =
    !!analysis ||
    jobSummary?.status === "completed" ||
    jobSummary?.status === "partial";

  const findingCount = analysis
    ? analysis.knowledge_graph?.nodes?.filter((n) => n.type === "finding")
        .length
    : 0;
  const fileCount = analysis
    ? analysis.knowledge_graph?.nodes?.filter((n) => n.type === "file").length
    : 0;

  // ── Render: loading / error (initial) ─────────────────────────────────────
  if (loading && !jobSummary && !analysis) {
    return <FullPageSpinner label="Loading analysis data from backend…" />;
  }

  if (error && !jobSummary && !analysis) {
    return (
      <main className="min-h-screen bg-slate-950 text-white p-8">
        <div className="max-w-4xl mx-auto">
          <Link
            href="/"
            className="text-slate-400 hover:text-white text-sm mb-6 inline-block"
          >
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

  // ── Main render ────────────────────────────────────────────────────────────
  return (
    <main className="min-h-screen bg-slate-950 text-white">
      {/* Sticky top bar */}
      <nav className="border-b border-slate-800 bg-slate-950/80 backdrop-blur-sm sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <Link
              href="/"
              className="text-slate-400 hover:text-white text-sm flex-shrink-0"
            >
              ← Home
            </Link>
            <span className="text-slate-700 flex-shrink-0">/</span>
            <span
              className="text-slate-300 text-sm font-mono truncate"
              title={analysis?.repository ?? jobSummary?.repo_url ?? id}
            >
              {repoLabel}
            </span>
          </div>
          <Link
            href="/history"
            className="text-slate-400 hover:text-white text-sm flex-shrink-0"
          >
            History →
          </Link>
        </div>
      </nav>

      <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        {/* Page title */}
        <div>
          <h1 className="text-3xl font-bold">Repository Intelligence</h1>
          <p className="text-slate-400 text-sm mt-1">
            Analysis Dashboard &amp; Evidence Drilldown
          </p>
        </div>

        {/* Repository metadata card */}
        <RepositoryMeta analysis={analysis} jobSummary={jobSummary} />

        {/* Job progress stepper (always shown while job/stage info is available) */}
        {(detailedJob ?? jobSummary) && (
          <ProgressStepper
            status={
              jobSummary?.status ?? analysis?.analysis_status ?? "queued"
            }
            currentStage={jobSummary?.current_stage ?? "queued"}
            progress={
              jobSummary?.progress ?? (analysis ? 100 : 0)
            }
            cacheHit={jobSummary?.cache_hit}
            errorMessage={jobSummary?.error_message}
            stages={detailedJob?.stages}
          />
        )}

        {/* Non-fatal error banner (partial load) */}
        {error && (
          <div className="bg-rose-950/60 border border-rose-800 rounded-xl p-4 text-rose-200">
            <p className="font-semibold text-sm">Error</p>
            <p className="text-xs mt-1 font-mono">{error}</p>
          </div>
        )}

        {/* Dashboard tabs — only rendered once analysis data is available */}
        {isComplete && analysis && (
          <>
            {/* Tab bar */}
            <div className="border-b border-slate-800">
              <div className="flex gap-0">
                {TABS.map((tab) => {
                  const active = activeTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      id={`tab-${tab.id}`}
                      onClick={() => setTab(tab.id)}
                      className={`px-5 py-3 text-sm font-medium transition-colors border-b-2 -mb-px ${
                        active
                          ? "border-blue-500 text-white"
                          : "border-transparent text-slate-400 hover:text-white hover:border-slate-600"
                      }`}
                    >
                      {tab.label}
                      {tab.id === "findings" && findingCount > 0 && (
                        <span className="ml-1.5 text-xs bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded-full">
                          {findingCount}
                        </span>
                      )}
                      {tab.id === "files" && fileCount > 0 && (
                        <span className="ml-1.5 text-xs bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded-full">
                          {fileCount}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Tab content */}
            <div>
              {/* ── Overview tab ── */}
              {activeTab === "overview" && (
                <div className="space-y-6">
                  <StatsGrid analysis={analysis} />

                  {analysis.health_score && (
                    <HealthScorePanel
                      healthScore={analysis.health_score}
                      onViewFindings={goToFindings}
                    />
                  )}

                  {/* Repository architecture graph (existing S16 component, unchanged) */}
                  <div>
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <h2 className="text-2xl font-bold">
                          Repository Architecture
                        </h2>
                        <p className="text-slate-400 text-sm mt-1">
                          Call &amp; file graph relationships from API
                        </p>
                      </div>
                      <div className="text-sm text-slate-400">
                        {fileCount} file{fileCount !== 1 ? "s" : ""}
                      </div>
                    </div>
                    <GraphView
                      nodes={analysis.knowledge_graph?.nodes ?? []}
                      edges={analysis.knowledge_graph?.edges ?? []}
                    />
                  </div>
                </div>
              )}

              {/* ── Findings tab ── */}
              {activeTab === "findings" && (
                <FindingsPanel runId={runId} onGoToFile={goToFile} />
              )}

              {/* ── Files tab ── */}
              {activeTab === "files" && (
                <FilesPanel runId={runId} onGoToFindings={goToFindings} />
              )}
            </div>
          </>
        )}
      </div>
    </main>
  );
}

// ─── Outer page wrapper (Suspense boundary for useSearchParams) ───────────────

export default function AnalysisDetailsPage({
  params: paramsPromise,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(paramsPromise);

  return (
    <Suspense fallback={<FullPageSpinner label="Loading…" />}>
      <AnalysisDashboard id={id} />
    </Suspense>
  );
}
