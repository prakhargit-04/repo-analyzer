"use client";

import React from "react";
import { CanonicalAnalysisPayload, JobStatusSummary } from "@/lib/api";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { truncateSha, repoDisplayName } from "@/lib/dashboard-utils";

interface RepositoryMetaProps {
  analysis?: CanonicalAnalysisPayload | null;
  jobSummary?: JobStatusSummary | null;
}

export function RepositoryMeta({ analysis, jobSummary }: RepositoryMetaProps) {
  const repoUrl = analysis?.repository || jobSummary?.repo_url || null;
  const displayName = repoDisplayName(repoUrl);
  const commitSha = analysis?.commit_sha || jobSummary?.commit_sha || null;
  const analysisStatus = analysis?.analysis_status || null;
  const jobStatus = jobSummary?.status || null;
  const cacheHit = jobSummary?.cache_hit ?? false;
  const analyzerVersion = analysis?.analyzer_version ?? null;
  const analyzedAt = analysis?.analyzed_at_utc ?? null;
  const languages = analysis?.languages ?? [];
  const schemaVersion = analysis?.schema_version ?? null;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
      {/* Top row: repo name + status badges */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-slate-400 text-xs font-medium uppercase tracking-wider mb-1">
            Repository
          </p>
          <p className="text-xl font-bold text-white truncate">{displayName}</p>
          {repoUrl && (
            <p className="text-slate-500 text-xs font-mono mt-1 truncate max-w-lg">
              {repoUrl}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2 items-center flex-shrink-0">
          {analysisStatus && (
            <StatusBadge status={analysisStatus} label={analysisStatus} />
          )}
          {jobStatus && jobStatus !== analysisStatus && (
            <StatusBadge status={jobStatus} label={`job: ${jobStatus}`} />
          )}
          {cacheHit && (
            <span className="bg-cyan-950 text-cyan-300 border border-cyan-700 text-xs px-2.5 py-0.5 rounded-full font-semibold">
              Cache Hit
            </span>
          )}
        </div>
      </div>

      {/* Detail grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-4 mt-5 pt-5 border-t border-slate-800">
        <div>
          <p className="text-slate-400 text-xs mb-1">Commit SHA</p>
          <p
            className="font-mono text-slate-200 text-xs truncate"
            title={commitSha ?? undefined}
          >
            {truncateSha(commitSha)}
          </p>
        </div>

        <div>
          <p className="text-slate-400 text-xs mb-1">Analyzer Version</p>
          <p className="font-mono text-slate-200 text-xs">
            {analyzerVersion ?? "—"}
          </p>
        </div>

        <div>
          <p className="text-slate-400 text-xs mb-1">Analyzed At</p>
          <p className="text-slate-200 text-xs">
            {analyzedAt
              ? new Date(analyzedAt).toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })
              : "—"}
          </p>
        </div>

        <div>
          <p className="text-slate-400 text-xs mb-1">Schema Version</p>
          <p className="font-mono text-slate-200 text-xs">
            {schemaVersion ?? "—"}
          </p>
        </div>

        <div className="col-span-2">
          <p className="text-slate-400 text-xs mb-1.5">Languages</p>
          <div className="flex flex-wrap gap-1.5">
            {languages.length > 0 ? (
              languages.map((l) => (
                <span
                  key={l}
                  className="bg-slate-800 text-slate-300 border border-slate-700 text-xs px-2 py-0.5 rounded font-mono"
                >
                  {l}
                </span>
              ))
            ) : (
              <span className="text-slate-500 text-xs">—</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
