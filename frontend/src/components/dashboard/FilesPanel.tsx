"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { getAnalysisFiles } from "@/lib/api";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { FileDetailPanel } from "@/components/dashboard/FileDetailPanel";
import { getFileLanguage } from "@/lib/dashboard-utils";

const PAGE_SIZE = 25;

interface FileNode {
  id: string;
  type?: string;
  name?: string | null;
  language?: string | null;
  provenance?: string | null;
  [key: string]: unknown;
}

interface FilesPanelProps {
  runId: string;
  /** Navigate the parent page to the Findings tab. */
  onGoToFindings: () => void;
}

export function FilesPanel({ runId, onGoToFindings }: FilesPanelProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const selectedFile = searchParams.get("file") ?? null;
  const offsetRaw = searchParams.get("offset_fl");
  const offset = offsetRaw ? parseInt(offsetRaw, 10) : 0;

  // Page-local search string — explicitly NOT a repository-wide search
  const [search, setSearch] = useState("");

  const [allFiles, setAllFiles] = useState<FileNode[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      const result = await getAnalysisFiles(runId, {
        limit: PAGE_SIZE,
        offset,
      });
      setAllFiles(result.files as FileNode[]);
      setTotal(result.pagination.total);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to load files from backend"
      );
    } finally {
      setLoading(false);
    }
  }, [runId, offset]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  // Clear search when page changes
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSearch("");
  }, [offset]);

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  // Client-side filter within the currently loaded page only
  const filteredFiles =
    search.trim()
      ? allFiles.filter((f) =>
          (f.id ?? "").toLowerCase().includes(search.trim().toLowerCase())
        )
      : allFiles;

  return (
    <div>
      {/* ── Search + pagination header ── */}
      <div className="flex flex-wrap items-start gap-3 mb-4">
        <div className="flex-1 min-w-[240px]">
          <input
            id="file-search"
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={`Filter within this page (${allFiles.length} files loaded)…`}
            className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2 text-slate-200 text-sm placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
          {search.trim() && (
            <p className="text-amber-400 text-xs mt-1.5">
              ⚠ Filtering within the current page only — this is not a
              repository-wide search.
            </p>
          )}
        </div>
        {!loading && totalPages > 1 && (
          <p className="text-slate-500 text-xs self-center whitespace-nowrap pt-2">
            Page {currentPage} of {totalPages}
          </p>
        )}
      </div>

      {/* ── Results summary ── */}
      <div className="flex items-center justify-between mb-3">
        <p className="text-slate-400 text-sm">
          {loading
            ? "Loading…"
            : `${total} file${total !== 1 ? "s" : ""} total${
                search.trim()
                  ? ` · ${filteredFiles.length} match on this page`
                  : ""
              }`}
        </p>
      </div>

      {/* ── Content ── */}
      {loading ? (
        <LoadingSpinner label="Loading files…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : allFiles.length === 0 ? (
        <EmptyState
          title="No files"
          description="No parsed files were found in this analysis run."
        />
      ) : (
        <>
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-x-auto">
            <table className="w-full text-left text-sm min-w-[500px]">
              <thead className="bg-slate-950 text-xs text-slate-400 uppercase border-b border-slate-800">
                <tr>
                  <th className="px-4 py-3">File Path</th>
                  <th className="px-4 py-3">Language</th>
                  <th className="px-4 py-3">Provenance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {filteredFiles.map((f) => {
                  const isSelected = f.id === selectedFile;
                  const lang = getFileLanguage(f.id ?? "", f.language);
                  const fileName = f.id?.split("/").pop() ?? f.id;
                  return (
                    <tr
                      key={f.id}
                      id={`file-row-${f.id}`}
                      onClick={() =>
                        navigate({ file: isSelected ? null : f.id ?? null })
                      }
                      className={`cursor-pointer transition-colors ${
                        isSelected
                          ? "bg-blue-950/30"
                          : "hover:bg-slate-800/50"
                      }`}
                    >
                      <td className="px-4 py-3">
                        <div className="font-mono text-xs text-white">
                          {fileName}
                        </div>
                        <div
                          className="font-mono text-xs text-slate-500 mt-0.5 max-w-xs truncate"
                          title={f.id}
                        >
                          {f.id}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={lang} label={lang} />
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500 font-mono">
                        {f.provenance ?? "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {/* Empty-search state within current page */}
            {filteredFiles.length === 0 && search.trim() && (
              <div className="px-4 py-8 text-center text-slate-500 text-sm">
                No files on this page match &quot;{search}&quot;
              </div>
            )}
          </div>

          {/* File detail panel (inline, below the table) */}
          {selectedFile && (
            <FileDetailPanel
              runId={runId}
              filePath={selectedFile}
              onClose={() => navigate({ file: null })}
              onGoToFindings={onGoToFindings}
            />
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <button
                id="files-prev"
                disabled={offset === 0}
                onClick={() =>
                  navigate({
                    offset_fl: String(Math.max(0, offset - PAGE_SIZE)),
                    file: null,
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
                id="files-next"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() =>
                  navigate({
                    offset_fl: String(offset + PAGE_SIZE),
                    file: null,
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
