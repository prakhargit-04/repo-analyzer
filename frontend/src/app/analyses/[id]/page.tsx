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
import { SemanticSearchPanel } from "@/components/dashboard/SemanticSearchPanel";
import { RepositoryAssistantPanel } from "@/components/dashboard/RepositoryAssistantPanel";
import { repoDisplayName } from "@/lib/dashboard-utils";

// ─── Types ───────────────────────────────────────────────────────────────────

type TabId = "overview" | "findings" | "files" | "search" | "assistant";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "findings", label: "Findings" },
  { id: "files", label: "Files" },
  { id: "search", label: "Semantic Search" },
  { id: "assistant", label: "AI Assistant" },
];

// ─── Full-page spinner ────────────────────────────────────────────────────────

function FullPageSpinner({ label }: { label: string }) {
  return (
    <main className="min-h-screen bg-[#070b14] text-slate-100 flex items-center justify-center">
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

  /**
   * Navigate to the Files tab with a file pre-selected (used by Assistant
   * panel when a citation is clicked to open the source evidence location).
   */
  const goToFileFromCitation = (filePath: string, line: number) => {
    void line;
    goToFile(filePath);
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
      <main className="min-h-screen bg-[#070b14] text-slate-100 p-5 sm:p-8">
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
    <main className="relative min-h-screen overflow-hidden bg-[#070b14] text-slate-100">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -right-48 top-[-10rem] h-[30rem] w-[30rem] rounded-full bg-cyan-500/[0.055] blur-3xl" />
        <div className="absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.02)_1px,transparent_1px)] bg-[size:56px_56px] [mask-image:linear-gradient(to_bottom,black,transparent_80%)]" />
      </div>
      {/* Sticky top bar */}
      <nav className="sticky top-0 z-20 border-b border-white/[0.07] bg-[#070b14]/85 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-3 sm:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <Link href="/" className="flex shrink-0 items-center gap-2.5 text-sm font-semibold text-slate-200 transition hover:text-white">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/10 text-[11px] font-bold text-cyan-200">RA</span>
              <span className="hidden sm:inline">Repo Analyzer</span>
            </Link>
            <span className="text-slate-700">/</span>
            <span
              className="text-slate-300 text-sm font-mono truncate"
              title={analysis?.repository ?? jobSummary?.repo_url ?? id}
            >
              {repoLabel}
            </span>
          </div>
          <Link href="/history" className="shrink-0 rounded-lg border border-white/[0.08] bg-white/[0.025] px-3 py-2 text-xs font-medium text-slate-400 transition hover:border-cyan-200/20 hover:text-white">
            History <span aria-hidden="true">↗</span>
          </Link>
        </div>
      </nav>

      <div className="relative z-10 mx-auto max-w-7xl space-y-6 px-5 py-7 sm:px-8 sm:py-9">
        {/* Page title */}
        <div className="flex flex-col gap-4 border-b border-white/[0.07] pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-cyan-200/65">Repository workspace</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-[-0.035em] text-white sm:text-4xl">Repository intelligence</h1>
            <p className="mt-2 text-sm leading-6 text-slate-500">Analysis overview, architecture, findings, and source-level evidence.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded-lg border border-white/[0.08] bg-white/[0.025] px-3 py-2 text-slate-400">{analysis ? `Commit ${analysis.commit_sha?.slice(0, 10) ?? "unknown"}` : "Analysis in progress"}</span>
            {jobSummary?.cache_hit && <span className="rounded-lg border border-emerald-300/15 bg-emerald-300/[0.06] px-3 py-2 text-emerald-200">Served from cache</span>}
          </div>
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
            <div className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-1.5">
              <div className="flex gap-1 overflow-x-auto">
                {TABS.map((tab) => {
                  const active = activeTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      id={`tab-${tab.id}`}
                      onClick={() => setTab(tab.id)}
                      aria-current={active ? "page" : undefined}
                      className={`rounded-lg px-4 py-2.5 text-sm font-medium transition whitespace-nowrap ${
                        active
                          ? "border border-cyan-200/15 bg-cyan-200/[0.08] text-cyan-100 shadow-sm"
                          : "border border-transparent text-slate-500 hover:bg-white/[0.035] hover:text-slate-200"
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
                  <div className="rounded-2xl border border-white/[0.08] bg-[#0c1321]/70 p-4 sm:p-5">
                    <div className="mb-5 flex items-center justify-between gap-4">
                      <div>
                        <h2 className="text-xl font-semibold tracking-tight text-white sm:text-2xl">
                          Repository architecture
                        </h2>
                        <p className="mt-1 text-sm text-slate-500">
                          File and call relationships inferred from source analysis
                        </p>
                      </div>
                      <div className="shrink-0 rounded-lg border border-white/[0.08] bg-white/[0.025] px-3 py-2 text-xs text-slate-400">
                        <span className="font-mono text-slate-200">{fileCount}</span> files
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

              {/* ── Semantic Search tab (S20) ── */}
              {activeTab === "search" && (
                <div className="space-y-4">
                  <div>
                    <h2 className="text-xl font-bold mb-1">Semantic Search</h2>
                    <p className="text-slate-400 text-sm">
                      Query this repository&apos;s source code by meaning using
                      vector similarity. Results are scoped to this exact
                      analysis run and commit SHA.{" "}
                      <span className="text-amber-400">
                        Note: With default test providers, embeddings are
                        deterministic hash-derived vectors (not semantic) —
                        results reflect plumbing only, not real semantic relevance.
                      </span>
                    </p>
                  </div>
                  <SemanticSearchPanel runId={runId} />
                </div>
              )}

              {/* ── AI Assistant tab (S21) ── */}
              {activeTab === "assistant" && (
                <div className="space-y-4">
                  <div>
                    <h2 className="text-xl font-bold mb-1">AI Assistant</h2>
                    <p className="text-slate-400 text-sm">
                      Ask questions about this repository grounded strictly in
                      retrieved source evidence. Answers include verifiable
                      citations — each citation opens the exact file location.{" "}
                      <span className="text-amber-400">
                        Note: With default test providers the assistant returns
                        deterministic placeholder text. This verifies plumbing
                        only. Real AI answers require configuring
                        LLM_PROVIDER=gemini or openai — see .env.example.
                      </span>
                    </p>
                  </div>
                  <RepositoryAssistantPanel
                    runId={runId}
                    onSelectLocation={goToFileFromCitation}
                  />
                </div>
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
