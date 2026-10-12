"use client";

import React, { useEffect, useState } from "react";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { resolveSourceChunk, SourceChunkItem } from "@/lib/api";

/** Shape of a finding node as it comes back from the knowledge graph. */
export interface FindingNode {
  id: string;
  type?: string;
  analyzer?: string | null;
  severity?: string | null;
  message?: string | null;
  title?: string | null;
  name?: string | null;
  file?: string | null;
  line?: number | null;
  col?: number | null;
  end_line?: number | null;
  rule_id?: string | null;
  test_id?: string | null;
  confidence?: string | null;
  provenance?: string | null;
  cwe?: string | null;
  owasp?: string | null;
  [key: string]: unknown;
}

interface FindingDetailPanelProps {
  finding: FindingNode;
  runId?: string;
  onClose: () => void;
  /** Navigate the parent page to the Files tab with this file pre-selected. */
  onGoToFile: (filePath: string) => void;
}

const KNOWN_KEYS = new Set([
  "id",
  "type",
  "analyzer",
  "severity",
  "message",
  "title",
  "name",
  "file",
  "line",
  "col",
  "end_line",
  "rule_id",
  "test_id",
  "confidence",
  "provenance",
  "cwe",
  "owasp",
]);

function Field({
  label,
  value,
}: {
  label: string;
  value: unknown;
}) {
  if (value == null || value === "") return null;
  const display =
    typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
  return (
    <div>
      <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">
        {label}
      </p>
      <p className="text-slate-200 text-sm font-mono break-all">{display}</p>
    </div>
  );
}

export function FindingDetailPanel({
  finding,
  runId,
  onClose,
  onGoToFile,
}: FindingDetailPanelProps) {
  const title =
    finding.message || finding.title || finding.name || finding.id;
  const ruleId = finding.rule_id || finding.test_id || null;

  const [sourceChunk, setSourceChunk] = useState<SourceChunkItem | null>(null);
  const [chunkLoading, setChunkLoading] = useState<boolean>(false);

  useEffect(() => {
    let active = true;
    if (runId && finding.file && finding.line != null) {
      Promise.resolve().then(() => {
        if (active) setChunkLoading(true);
      });
      resolveSourceChunk(runId, finding.file, finding.line)
        .then((sc) => {
          if (active) setSourceChunk(sc);
        })
        .catch(() => {
          if (active) setSourceChunk(null);
        })
        .finally(() => {
          if (active) setChunkLoading(false);
        });
    } else {
      Promise.resolve().then(() => {
        if (active) {
          setSourceChunk(null);
          setChunkLoading(false);
        }
      });
    }
    return () => {
      active = false;
    };
  }, [runId, finding.file, finding.line]);

  // Extra fields that aren't already displayed individually
  const extraEntries = Object.entries(finding).filter(
    ([k]) => !KNOWN_KEYS.has(k)
  );

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 mt-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-5">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <SeverityBadge severity={finding.severity} />
            {finding.analyzer && (
              <span className="bg-slate-800 text-slate-300 border border-slate-700 text-xs px-2 py-0.5 rounded font-mono">
                {finding.analyzer}
              </span>
            )}
            {ruleId && (
              <span className="bg-slate-800 text-slate-400 border border-slate-700 text-xs px-2 py-0.5 rounded font-mono">
                {ruleId}
              </span>
            )}
            {finding.confidence && (
              <StatusBadge
                status={finding.confidence}
                label={`Confidence: ${finding.confidence}`}
              />
            )}
          </div>
          <p className="text-white font-medium text-sm leading-snug">{title}</p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close finding detail"
          className="text-slate-500 hover:text-white text-xl leading-none flex-shrink-0 transition-colors"
        >
          ×
        </button>
      </div>

      {/* Field grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
        {/* File — spans full width, includes navigation button */}
        {finding.file && (
          <div className="md:col-span-2">
            <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">
              File
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-slate-200 text-sm font-mono break-all">
                {finding.file}
              </p>
              <button
                onClick={() => finding.file && onGoToFile(finding.file)}
                className="flex-shrink-0 text-xs text-blue-400 hover:text-blue-300 border border-blue-800 hover:border-blue-600 px-2.5 py-1 rounded transition-colors"
              >
                Go to File →
              </button>
            </div>
          </div>
        )}

        {finding.line != null && <Field label="Line" value={finding.line} />}
        {finding.col != null && <Field label="Column" value={finding.col} />}
        {finding.end_line != null && (
          <Field label="End Line" value={finding.end_line} />
        )}
        {finding.provenance && (
          <Field label="Provenance" value={finding.provenance} />
        )}
        {finding.cwe && <Field label="CWE" value={finding.cwe} />}
        {finding.owasp && <Field label="OWASP" value={finding.owasp} />}
        <Field label="Finding ID" value={finding.id} />

        {/* Any extra fields from the knowledge graph node */}
        {extraEntries.map(([key, val]) => (
          <Field key={key} label={key} value={val} />
        ))}
      </div>

      {/* Source Evidence Preview Section (S19) */}
      <div className="mt-5 pt-4 border-t border-slate-800">
        <div className="flex items-center justify-between mb-2">
          <p className="text-slate-400 text-xs font-semibold uppercase tracking-wider">
            Source Evidence Preview (S19)
          </p>
          {sourceChunk && (
            <span className="text-xs text-slate-400 font-mono">
              {sourceChunk.file_path}:L{sourceChunk.start_line}–L{sourceChunk.end_line}
            </span>
          )}
        </div>

        {chunkLoading ? (
          <p className="text-xs text-slate-500 font-mono animate-pulse">Loading source evidence chunk...</p>
        ) : sourceChunk ? (
          <div>
            <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 font-mono text-xs text-slate-200 overflow-x-auto max-h-64 leading-relaxed">
              <pre>{sourceChunk.chunk_text}</pre>
            </div>
            <div className="flex flex-wrap items-center justify-between text-[11px] text-slate-500 mt-2 font-mono gap-2">
              <span>Provenance: {sourceChunk.provenance}</span>
              {sourceChunk.commit_sha && <span>Commit: {sourceChunk.commit_sha.substring(0, 8)}</span>}
            </div>
          </div>
        ) : (
          <p className="text-slate-500 text-xs">
            Source code chunk metadata is traceable to repo snapshot commit. Select a file or line location to view matching chunk preview.
          </p>
        )}
      </div>
    </div>
  );
}
