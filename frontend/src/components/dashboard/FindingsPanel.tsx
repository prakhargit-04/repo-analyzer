"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { getAnalysisFindings } from "@/lib/api";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import {
  FindingDetailPanel,
  FindingNode,
} from "@/components/dashboard/FindingDetailPanel";

const PAGE_SIZE = 25;
const SEVERITIES = ["ALL", "HIGH", "MEDIUM", "LOW"];
// Well-known analyzer names; page-local analyzer names are appended dynamically.
const BASE_ANALYZERS = ["bandit", "semgrep", "gitleaks", "lizard", "osv"];

interface FindingsPanelProps {
  runId: string;
  /** Navigate to the Files tab with a specific file pre-selected. */
  onGoToFile: (filePath: string) => void;
}

export function FindingsPanel({ runId, onGoToFile }: FindingsPanelProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const severity = searchParams.get("severity") ?? "";
  const analyzer = searchParams.get("analyzer") ?? "";
  const offsetRaw = searchParams.get("offset_f");
  const offset = offsetRaw ? parseInt(offsetRaw, 10) : 0;
  const selectedFindingId = searchParams.get("finding") ?? null;

  const [findings, setFindings] = useState<FindingNode[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /** Push URL param updates without losing unrelated params. */
  const navigate = useCallback(
    (updates: Record<string, string | null>) => {
      const params = new URLSearchParams(searchParams.toString());
      Object.entries(updates).forEach(([k, v]) => {
        if (v === null || v === "") {
          params.delete(k);
        } else {
          params.set(k, v);
        }
      });
      router.push(`/analyses/${runId}?${params.toString()}`);
    },
    [router, runId, searchParams]
  );

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await getAnalysisFindings(runId, {
        severity: severity || undefined,
        analyzer: analyzer || undefined,
        limit: PAGE_SIZE,
        offset,
      });
      setFindings(result.findings as FindingNode[]);
      setTotal(result.pagination.total);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to load findings from backend"
      );
    } finally {
      setLoading(false);
    }
  }, [runId, severity, analyzer, offset]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  const selectedFinding = selectedFindingId
    ? findings.find((f) => f.id === selectedFindingId) ?? null
    : null;

  // Collect unique analyzers present on the current page to supplement the dropdown
  const pageAnalyzers = [
    ...new Set(findings.map((f) => f.analyzer).filter(Boolean)),
  ] as string[];
  const allAnalyzers = [
    ...new Set([...BASE_ANALYZERS, ...pageAnalyzers]),
  ].sort();

  return (
    <div>
      {/* ── Filter bar ── */}
      <div className="flex flex-wrap gap-3 mb-4 items-center">
        {/* Severity pill buttons */}
        <div className="flex items-center gap-1 bg-slate-900 border border-slate-800 rounded-lg p-1">
          {SEVERITIES.map((s) => {
            const active = s === "ALL" ? !severity : severity === s;
            return (
              <button
                key={s}
                id={`severity-filter-${s.toLowerCase()}`}
                onClick={() =>
                  navigate({
                    severity: s === "ALL" ? null : s,
                    offset_f: null,
                    finding: null,
                  })
                }
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  active
                    ? "bg-slate-700 text-white"
                    : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`}
              >
                {s}
              </button>
            );
          })}
        </div>

        {/* Analyzer dropdown */}
        <select
          id="analyzer-filter"
          value={analyzer}
          onChange={(e) =>
            navigate({
              analyzer: e.target.value || null,
              offset_f: null,
              finding: null,
            })
          }
          className="bg-slate-900 border border-slate-800 text-slate-300 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
        >
          <option value="">All Analyzers</option>
          {allAnalyzers.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>

        {/* Clear-filters button */}
        {(severity || analyzer) && (
          <button
            id="clear-filters"
            onClick={() =>
              navigate({
                severity: null,
                analyzer: null,
                offset_f: null,
                finding: null,
              })
            }
            className="text-xs text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 px-3 py-1.5 rounded-lg transition-colors"
          >
            Clear filters ×
          </button>
        )}
      </div>

      {/* ── Results header ── */}
      <div className="flex items-center justify-between mb-3">
        <p className="text-slate-400 text-sm">
          {loading
            ? "Loading…"
            : `${total} finding${total !== 1 ? "s" : ""}${
                severity || analyzer ? " (filtered)" : ""
              }`}
        </p>
        {!loading && totalPages > 1 && (
          <p className="text-slate-500 text-xs">
            Page {currentPage} of {totalPages}
          </p>
        )}
      </div>

      {/* ── Content ── */}
      {loading ? (
        <LoadingSpinner label="Loading findings…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : findings.length === 0 ? (
        <EmptyState
          title="No findings"
          description={
            severity || analyzer
              ? "No findings match the current filters. Try adjusting the severity or analyzer selection."
              : "This analysis produced no findings."
          }
        />
      ) : (
        <>
          {/* Findings table */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-x-auto">
            <table className="w-full text-left text-sm min-w-[640px]">
              <thead className="bg-slate-950 text-xs text-slate-400 uppercase border-b border-slate-800">
                <tr>
                  <th className="px-4 py-3">Severity</th>
                  <th className="px-4 py-3">Analyzer</th>
                  <th className="px-4 py-3">Rule / ID</th>
                  <th className="px-4 py-3 w-80">Message</th>
                  <th className="px-4 py-3">File</th>
                  <th className="px-4 py-3">Line</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {findings.map((f) => {
                  const isSelected = f.id === selectedFindingId;
                  const ruleId = f.rule_id ?? f.test_id ?? "—";
                  const msg = f.message ?? f.title ?? f.name ?? "—";
                  const filePath = f.file ?? null;
                  const fileName = filePath
                    ? filePath.split("/").pop()
                    : null;
                  return (
                    <tr
                      key={f.id}
                      id={`finding-row-${f.id}`}
                      onClick={() =>
                        navigate({ finding: isSelected ? null : f.id })
                      }
                      className={`cursor-pointer transition-colors ${
                        isSelected
                          ? "bg-blue-950/30 border-l-2 border-l-blue-600"
                          : "hover:bg-slate-800/50"
                      }`}
                    >
                      <td className="px-4 py-3">
                        <SeverityBadge severity={f.severity} />
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-300">
                        {f.analyzer ?? "—"}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400 max-w-[120px] truncate">
                        <span title={ruleId}>{ruleId}</span>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-200 max-w-xs">
                        <span
                          className="line-clamp-2"
                          title={msg !== "—" ? msg : undefined}
                        >
                          {msg}
                        </span>
                      </td>
                      <td
                        className="px-4 py-3 font-mono text-xs text-slate-400 max-w-[160px] truncate"
                        title={filePath ?? undefined}
                      >
                        {fileName ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-400 tabular-nums">
                        {f.line != null ? f.line : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Finding detail panel (inline, below the table) */}
          {selectedFinding && (
            <FindingDetailPanel
              finding={selectedFinding}
              onClose={() => navigate({ finding: null })}
              onGoToFile={onGoToFile}
            />
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <button
                id="findings-prev"
                disabled={offset === 0}
                onClick={() =>
                  navigate({
                    offset_f: String(Math.max(0, offset - PAGE_SIZE)),
                    finding: null,
                  })
                }
                className="px-4 py-2 text-sm bg-slate-900 border border-slate-800 rounded-lg text-slate-300 hover:text-white hover:border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                ← Previous
              </button>
              <span className="text-xs text-slate-400">
                Page {currentPage} of {totalPages}
              </span>
              <button
                id="findings-next"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() =>
                  navigate({
                    offset_f: String(offset + PAGE_SIZE),
                    finding: null,
                  })
                }
                className="px-4 py-2 text-sm bg-slate-900 border border-slate-800 rounded-lg text-slate-300 hover:text-white hover:border-slate-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
