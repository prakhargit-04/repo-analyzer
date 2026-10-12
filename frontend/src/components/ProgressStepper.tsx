"use client";

import React from "react";

export interface StageInfo {
  stage_name: string;
  status: string; // pending | running | completed | skipped | failed
  detail?: string | null;
}

interface ProgressStepperProps {
  status: string;
  currentStage: string;
  progress: number;
  cacheHit?: boolean;
  errorMessage?: string | null;
  stages?: StageInfo[];
}

const DISPLAY_STAGES = [
  { key: "cloning", label: "Clone" },
  { key: "parsing", label: "Parsing" },
  { key: "analyzing", label: "Static Analysis" },
  { key: "graph-building", label: "Graph" },
  { key: "scoring", label: "Health Score" },
  { key: "embedding", label: "Embeddings" },
  { key: "completed", label: "Complete" },
];

export const ProgressStepper: React.FC<ProgressStepperProps> = ({
  status,
  currentStage,
  progress,
  cacheHit = false,
  errorMessage,
  stages = [],
}) => {
  const getStageState = (stageKey: string) => {
    if (cacheHit && status === "completed") {
      return stageKey === "embedding" ? "skipped" : "completed";
    }

    if (stageKey === "embedding") {
      return "skipped";
    }

    if (stageKey === "completed") {
      if (status === "completed") return "completed";
      if (status === "partial") return "partial";
      if (status === "failed") return "failed";
      return "pending";
    }

    const matchedStage = stages.find((s) => s.stage_name === stageKey);
    if (matchedStage) {
      return matchedStage.status;
    }

    if (status === "failed" && currentStage === stageKey) {
      return "failed";
    }

    if (currentStage === stageKey) {
      return "running";
    }

    const order = ["cloning", "parsing", "analyzing", "graph-building", "scoring", "embedding", "completed"];
    const currentIndex = order.indexOf(currentStage);
    const stageIndex = order.indexOf(stageKey);

    if (currentIndex > stageIndex) {
      return "completed";
    }

    return "pending";
  };

  const renderBadge = (state: string) => {

    switch (state) {
      case "completed":
      case "success":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-900/60 text-emerald-300 border border-emerald-700">
            Completed
          </span>
        );
      case "running":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-900/60 text-blue-300 border border-blue-700 animate-pulse">
            Running...
          </span>
        );
      case "skipped":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700">
            Skipped (S20)
          </span>
        );
      case "partial":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-900/60 text-amber-300 border border-amber-700">
            Partial
          </span>
        );
      case "failed":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-900/60 text-rose-300 border border-rose-700">
            Failed
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-900 text-slate-500 border border-slate-800">
            Queued
          </span>
        );
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div>
          <h3 className="text-xl font-bold text-white flex items-center gap-3">
            Analysis Execution
            {cacheHit && (
              <span className="bg-cyan-950 text-cyan-300 border border-cyan-700 text-xs px-2.5 py-1 rounded-full font-semibold">
                Served from cache
              </span>
            )}
          </h3>
          <p className="text-sm text-slate-400 mt-1">
            Current Stage: <span className="font-semibold text-slate-200 capitalize">{currentStage}</span>
          </p>
        </div>

        <div className="text-right">
          <div className="text-2xl font-bold text-white">{progress}%</div>
          <div className="text-xs text-slate-400 capitalize">{status}</div>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="w-full bg-slate-800 h-2.5 rounded-full overflow-hidden mb-6">
        <div
          className={`h-full transition-all duration-500 ${
            status === "failed"
              ? "bg-rose-500"
              : status === "partial"
              ? "bg-amber-500"
              : status === "completed"
              ? "bg-emerald-500"
              : "bg-blue-500"
          }`}
          style={{ width: `${Math.min(Math.max(progress, 0), 100)}%` }}
        />
      </div>

      {/* Stage Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        {DISPLAY_STAGES.map((s) => {
          const state = getStageState(s.key);
          const matched = stages.find((st) => st.stage_name === s.key);
          return (
            <div
              key={s.key}
              className={`p-3 rounded-lg border flex flex-col justify-between ${
                state === "running"
                  ? "bg-blue-950/40 border-blue-800"
                  : state === "completed"
                  ? "bg-slate-900 border-slate-800"
                  : state === "failed"
                  ? "bg-rose-950/40 border-rose-800"
                  : state === "partial"
                  ? "bg-amber-950/40 border-amber-800"
                  : "bg-slate-950/50 border-slate-900"
              }`}
            >
              <div>
                <div className="text-xs text-slate-400 mb-1">{s.label}</div>
                {renderBadge(state)}

              </div>
              {matched?.detail && (
                <div className="text-[10px] text-slate-500 mt-2 truncate" title={matched.detail}>
                  {matched.detail}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Failure Error Alert */}
      {status === "failed" && errorMessage && (
        <div className="mt-6 p-4 rounded-lg bg-rose-950/60 border border-rose-800 text-rose-200">
          <div className="font-semibold text-sm mb-1">Analysis Failed</div>
          <div className="text-xs text-rose-300 font-mono">{errorMessage}</div>
        </div>
      )}

      {/* Partial Warning Alert */}
      {status === "partial" && (
        <div className="mt-6 p-4 rounded-lg bg-amber-950/60 border border-amber-800 text-amber-200">
          <div className="font-semibold text-sm mb-1">Partial Analysis Completed</div>
          <div className="text-xs text-amber-300">
            One or more static analysis tools failed or were skipped, but graph structure and available metrics were generated.
          </div>
        </div>
      )}
    </div>
  );
};
