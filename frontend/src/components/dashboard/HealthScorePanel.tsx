"use client";

import React from "react";
import { HealthScoreData } from "@/lib/api";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatScore, getScoreLevel } from "@/lib/dashboard-utils";

interface HealthScorePanelProps {
  healthScore?: HealthScoreData | null;
  /** Called when the user clicks any "Browse Findings" button. Tab navigation is owned by the parent. */
  onViewFindings: () => void;
}

function scoreColorClass(level: ReturnType<typeof getScoreLevel>): string {
  switch (level) {
    case "good":
      return "text-emerald-400";
    case "warning":
      return "text-amber-400";
    case "poor":
      return "text-rose-400";
    default:
      return "text-slate-400";
  }
}

function barColorClass(level: ReturnType<typeof getScoreLevel>): string {
  switch (level) {
    case "good":
      return "bg-emerald-500";
    case "warning":
      return "bg-amber-500";
    case "poor":
      return "bg-rose-500";
    default:
      return "bg-slate-600";
  }
}

export function HealthScorePanel({
  healthScore,
  onViewFindings,
}: HealthScorePanelProps) {
  if (!healthScore) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-xl font-bold text-white mb-2">Health Score</h2>
        <p className="text-slate-500 text-sm">
          No health score data is available for this analysis run.
        </p>
      </div>
    );
  }

  const compositeScore = healthScore.composite_health_score;
  const compositeLevel = getScoreLevel(compositeScore);
  const subScores = healthScore.sub_scores ?? {};
  const componentStatuses = healthScore.component_statuses ?? {};
  const weightsUsed = healthScore.weights_used ?? {};
  const missingComponents = healthScore.missing_components ?? [];
  const componentEntries = Object.entries(subScores);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
        <div>
          <h2 className="text-xl font-bold text-white">Health Score</h2>
          <p className="text-slate-400 text-xs mt-1">
            Calculated by the analysis pipeline — not computed client-side.
          </p>
        </div>
        <div className="text-right">
          <p
            className={`text-5xl font-bold tabular-nums ${scoreColorClass(
              compositeLevel
            )}`}
          >
            {formatScore(compositeScore)}
          </p>
          <div className="mt-2 flex items-center justify-end gap-2">
            {healthScore.status && (
              <StatusBadge status={healthScore.status} />
            )}
          </div>
        </div>
      </div>

      {/* Composite progress bar */}
      {compositeScore != null && (
        <div className="h-3 w-full bg-slate-800 rounded-full overflow-hidden mb-5">
          <div
            className={`h-full rounded-full transition-all duration-500 ${barColorClass(
              compositeLevel
            )}`}
            style={{
              width: `${Math.min(Math.max(compositeScore, 0), 100)}%`,
            }}
          />
        </div>
      )}

      {/* Missing-component notice */}
      {missingComponents.length > 0 && (
        <div className="mb-4 p-3 bg-amber-950/40 border border-amber-800 rounded-lg text-amber-300 text-xs">
          Missing components (excluded from score):{" "}
          <span className="font-mono">{missingComponents.join(", ")}</span>
          {healthScore.weights_renormalized && (
            <span className="ml-1">— weights renormalized.</span>
          )}
        </div>
      )}

      {/* Per-component rows */}
      {componentEntries.length > 0 && (
        <div className="space-y-4">
          {componentEntries.map(([component, score]) => {
            const status = componentStatuses[component];
            const weight = weightsUsed[component];
            const isMissing = missingComponents.includes(component);
            const level = getScoreLevel(score);

            return (
              <div key={component} className="group">
                <div className="flex items-center justify-between mb-1.5 gap-2">
                  <div className="flex flex-wrap items-center gap-2 min-w-0">
                    <span className="text-slate-200 text-sm font-medium capitalize">
                      {component}
                    </span>
                    {status && <StatusBadge status={status} />}
                    {isMissing && (
                      <span className="text-xs text-slate-500 italic">
                        (missing)
                      </span>
                    )}
                    {weight != null && (
                      <span className="text-xs text-slate-500">
                        weight: {(weight * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <span
                      className={`text-lg font-bold tabular-nums ${scoreColorClass(
                        level
                      )}`}
                    >
                      {formatScore(score)}
                    </span>
                    {/* Navigate to Findings without assuming analyzer = component name */}
                    <button
                      onClick={onViewFindings}
                      title="Browse all findings — use the analyzer filter in the Findings tab to narrow further"
                      className="text-xs text-slate-500 hover:text-blue-400 transition-colors opacity-0 group-hover:opacity-100 whitespace-nowrap"
                    >
                      View Findings →
                    </button>
                  </div>
                </div>
                <div className="h-2 w-full bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${barColorClass(
                      level
                    )}`}
                    style={{
                      width:
                        score != null
                          ? `${Math.min(Math.max(score, 0), 100)}%`
                          : "0%",
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Footer */}
      <div className="mt-6 pt-4 border-t border-slate-800 flex flex-wrap items-start justify-between gap-3">
        <button
          onClick={onViewFindings}
          className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
        >
          Browse All Findings →
        </button>
        {healthScore.formula && (
          <p
            className="text-xs text-slate-500 text-right max-w-sm leading-relaxed"
            title={healthScore.formula}
          >
            {healthScore.formula.length > 100
              ? healthScore.formula.slice(0, 100) + "…"
              : healthScore.formula}
          </p>
        )}
      </div>

      {/* Pipeline note */}
      {healthScore.note && (
        <p className="mt-3 text-xs text-slate-500 border-t border-slate-800 pt-3 leading-relaxed">
          {healthScore.note}
        </p>
      )}
    </div>
  );
}
