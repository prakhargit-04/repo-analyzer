"use client";

import React, { useCallback, useEffect, useState } from "react";
import { getFileDetail } from "@/lib/api";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { separateEntities, getFileLanguage } from "@/lib/dashboard-utils";

/** Entity node as returned inside the file-detail response. */
interface EntityNode {
  id: string;
  type?: string | null;
  name?: string | null;
  file?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  analyzer?: string | null;
  severity?: string | null;
  message?: string | null;
  title?: string | null;
  rule_id?: string | null;
  test_id?: string | null;
  confidence?: string | null;
  provenance?: string | null;
  [key: string]: unknown;
}

interface FileDetailPanelProps {
  runId: string;
  filePath: string;
  onClose: () => void;
  /** Navigate the parent page to the Findings tab. */
  onGoToFindings: () => void;
}

export function FileDetailPanel({
  runId,
  filePath,
  onClose,
  onGoToFindings,
}: FileDetailPanelProps) {
  const [entities, setEntities] = useState<EntityNode[]>([]);
  const [language, setLanguage] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const detail = await getFileDetail(runId, filePath);
      setEntities(detail.entities as EntityNode[]);
      setLanguage(detail.language ?? null);
      setParseError(detail.parse_error ?? null);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Failed to load file detail from backend"
      );
    } finally {
      setLoading(false);
    }
  }, [runId, filePath]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const { codeEntities, findingEntities } = separateEntities(entities);
  const fileName = filePath.split("/").pop() ?? filePath;
  const displayLanguage = getFileLanguage(filePath, language);

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 mt-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span className="text-white font-semibold text-base">
              {fileName}
            </span>
            <StatusBadge status={displayLanguage} label={displayLanguage} />
            {parseError && (
              <StatusBadge status="failed" label="Parse Error" />
            )}
          </div>
          <p className="text-slate-500 text-xs font-mono">{filePath}</p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close file detail"
          className="text-slate-500 hover:text-white text-xl leading-none flex-shrink-0 transition-colors"
        >
          ×
        </button>
      </div>

      {/* Parse error notice */}
      {parseError && (
        <div className="mb-4 p-3 bg-amber-950/40 border border-amber-800 rounded-lg text-amber-300 text-xs font-mono">
          Parse error: {parseError}
        </div>
      )}

      {loading ? (
        <LoadingSpinner label="Loading file detail…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : (
        <div className="space-y-6">
          {/* ── Code entities ── */}
          <section>
            <h4 className="text-slate-400 text-xs uppercase tracking-wider font-medium mb-3">
              Code Entities ({codeEntities.length})
            </h4>
            {codeEntities.length === 0 ? (
              <EmptyState
                title="No code entities"
                description="No functions, classes, or methods were parsed from this file."
              />
            ) : (
              <div className="space-y-1.5">
                {(codeEntities as EntityNode[]).map((e) => (
                  <div
                    key={e.id}
                    className="flex items-center gap-3 bg-slate-950/50 border border-slate-800 rounded-lg px-4 py-2.5"
                  >
                    <span className="text-xs bg-slate-800 text-slate-400 border border-slate-700 px-1.5 py-0.5 rounded capitalize font-mono flex-shrink-0">
                      {e.type ?? "entity"}
                    </span>
                    <span
                      className="text-sm text-white font-mono flex-1 truncate"
                      title={e.name ?? e.id}
                    >
                      {e.name ?? e.id}
                    </span>
                    {e.start_line != null && (
                      <span className="text-xs text-slate-500 font-mono flex-shrink-0 tabular-nums">
                        L{e.start_line}
                        {e.end_line != null && e.end_line !== e.start_line
                          ? `–${e.end_line}`
                          : ""}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* ── Related findings ── */}
          {findingEntities.length > 0 && (
            <section>
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-slate-400 text-xs uppercase tracking-wider font-medium">
                  Related Findings ({findingEntities.length})
                </h4>
                <button
                  onClick={onGoToFindings}
                  className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                >
                  Browse All Findings →
                </button>
              </div>
              <div className="space-y-2">
                {(findingEntities as EntityNode[]).map((f) => {
                  const ruleId = f.rule_id ?? f.test_id ?? null;
                  const msg = f.message ?? f.title ?? f.name ?? f.id;
                  return (
                    <div
                      key={f.id}
                      className="bg-slate-950/50 border border-slate-800 rounded-lg px-4 py-3"
                    >
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <SeverityBadge severity={f.severity} />
                        {f.analyzer && (
                          <span className="font-mono text-xs bg-slate-800 text-slate-400 border border-slate-700 px-1.5 py-0.5 rounded">
                            {f.analyzer}
                          </span>
                        )}
                        {ruleId && (
                          <span className="font-mono text-xs text-slate-500">
                            {ruleId}
                          </span>
                        )}
                        {f.start_line != null && (
                          <span className="text-xs text-slate-500 tabular-nums">
                            Line {f.start_line}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-slate-200">{msg}</p>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* ── Source code notice ── */}
          <div className="pt-4 border-t border-slate-800">
            <p className="text-slate-500 text-xs">
              Source code display is not available in S17. File content
              storage and evidence chunking are planned for a future session
              (S19).
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
