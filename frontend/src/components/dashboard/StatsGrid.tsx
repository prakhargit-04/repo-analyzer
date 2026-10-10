"use client";

import React from "react";
import { CanonicalAnalysisPayload } from "@/lib/api";

interface StatCardProps {
  label: string;
  value: string | number | null | undefined;
  sub?: string;
}

function StatCard({ label, value, sub }: StatCardProps) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <p className="text-slate-400 text-xs uppercase tracking-wider mb-2">
        {label}
      </p>
      <p className="text-3xl font-bold text-white">
        {value ?? "—"}
      </p>
      {sub && <p className="text-slate-500 text-xs mt-1">{sub}</p>}
    </div>
  );
}

interface StatsGridProps {
  analysis: CanonicalAnalysisPayload;
}

export function StatsGrid({ analysis }: StatsGridProps) {
  const nodes = analysis.knowledge_graph?.nodes ?? [];
  const summary = analysis.knowledge_graph_summary;

  const classCount = nodes.filter((n) => n.type === "class").length;
  const functionCount = nodes.filter((n) => n.type === "function").length;
  const findingCount = nodes.filter((n) => n.type === "finding").length;
  const fileCount = nodes.filter((n) => n.type === "file").length;

  const resolvedPct = summary?.call_edges_resolved_pct;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <StatCard label="Files Analyzed" value={analysis.files_analyzed} />
      <StatCard
        label="Findings"
        value={findingCount > 0 ? findingCount : "—"}
        sub={findingCount === 0 ? "no findings detected" : undefined}
      />
      <StatCard
        label="Graph Nodes"
        value={summary?.total_nodes ?? nodes.length}
      />
      <StatCard
        label="Graph Edges"
        value={
          summary?.total_edges ??
          analysis.knowledge_graph?.edges?.length ??
          "—"
        }
      />
      <StatCard
        label="Functions"
        value={functionCount > 0 ? functionCount : "—"}
      />
      <StatCard
        label="Classes"
        value={classCount > 0 ? classCount : "—"}
      />
      <StatCard
        label="Call Edges"
        value={summary?.call_edges_total ?? "—"}
      />
      <StatCard
        label="Call Resolved"
        value={resolvedPct != null ? `${resolvedPct}%` : "—"}
        sub={
          fileCount > 0
            ? `${fileCount} parsed file${fileCount !== 1 ? "s" : ""}`
            : undefined
        }
      />
    </div>
  );
}
