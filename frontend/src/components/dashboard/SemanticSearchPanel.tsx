"use client";

import React, { useState, useEffect } from "react";

import { retrieveSourceChunks, RetrievalResponse, RetrievalResultItem, getAiStatus } from "@/lib/api";
import { getAiBadgeState, AiBadgeState } from "@/lib/ai-status-helper";

interface SemanticSearchPanelProps {
  runId: string;
}

export function SemanticSearchPanel({ runId }: SemanticSearchPanelProps) {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<RetrievalResponse | null>(null);
  const [aiState, setAiState] = useState<AiBadgeState>(() => getAiBadgeState(null));

  useEffect(() => {
    getAiStatus()
      .then((data) => setAiState(getAiBadgeState(data)))
      .catch(() => setAiState(getAiBadgeState(null)));
  }, []);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const res = await retrieveSourceChunks(runId, query.trim(), topK);
      setResponse(res);
    } catch (err: any) {
      setError(err?.message || "Failed to retrieve source chunks");
    } finally {
      setLoading(false);
    }
  };

  const getBadgeStyle = (variant: string) => {
    switch (variant) {
      case "real":
        return "bg-emerald-950 text-emerald-300 border-emerald-800";
      case "error":
        return "bg-red-950 text-red-300 border-red-800";
      case "test":
        return "bg-indigo-950 text-indigo-300 border-indigo-800";
      default:
        return "bg-slate-800 text-slate-400 border-slate-700";
    }
  };

  return (
    <div className="bg-slate-900 text-slate-100 rounded-xl p-5 border border-slate-800 shadow-xl space-y-4">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div>
          <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
            <svg className="w-5 h-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            Vector Semantic Code Search
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Query source chunks by semantic vector similarity
          </p>
        </div>
        <span className={`text-xs border px-2.5 py-1 rounded-full font-mono ${getBadgeStyle(aiState.badgeVariant)}`}>
          {aiState.badgeLabel}
        </span>
      </div>

      {aiState.showDisclaimer && (
        <div className="bg-amber-950/40 border border-amber-800/60 text-amber-300 text-xs px-3 py-2 rounded-lg flex items-center gap-2">
          <svg className="w-4 h-4 shrink-0 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>Using deterministic test mode placeholders (Test Mode). Configure real providers in .env for production semantic analysis.</span>
        </div>
      )}


      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. Where is authentication or health score computed?"
          className="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-3.5 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 placeholder-slate-500"
        />
        <select
          value={topK}
          onChange={(e) => setTopK(Number(e.target.value))}
          className="bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 font-mono"
        >
          <option value={3}>Top 3</option>
          <option value={5}>Top 5</option>
          <option value={10}>Top 10</option>
        </select>
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium text-sm px-4 py-2 rounded-lg transition-colors flex items-center gap-1.5"
        >
          {loading ? (
            <>
              <svg className="animate-spin h-4 w-4 text-white" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              Searching...
            </>
          ) : (
            "Retrieve"
          )}
        </button>
      </form>

      {error && (
        <div className="bg-red-950/60 border border-red-800 text-red-300 text-xs p-3 rounded-lg">
          {error}
        </div>
      )}

      {response && (
        <div className="space-y-3 pt-2">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>Retrieved {response.total_retrieved} evidence chunk(s)</span>
            {response.commit_sha && (
              <span className="font-mono text-slate-500">SHA: {response.commit_sha.slice(0, 7)}</span>
            )}
          </div>

          <div className="space-y-3">
            {response.results.map((item: RetrievalResultItem, idx: number) => (
              <div
                key={item.chunk_id || idx}
                className="bg-slate-950 border border-slate-800 rounded-lg p-3.5 space-y-2 hover:border-slate-700 transition-colors"
              >
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 font-mono">
                    <span className="text-emerald-400 font-semibold bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-800/60">
                      Score: {item.score.toFixed(4)}
                    </span>
                    <span className="text-slate-300 font-semibold">{item.file_path}</span>
                    <span className="text-slate-500">
                      L{item.start_line}-{item.end_line}
                    </span>
                  </div>
                  {item.entity_name && (
                    <span className="text-indigo-400 bg-indigo-950/60 px-2 py-0.5 rounded text-[11px] font-mono border border-indigo-900">
                      {item.entity_type ? `${item.entity_type}: ` : ""}{item.entity_name}
                    </span>
                  )}
                </div>

                <pre className="text-xs font-mono bg-slate-900/90 p-2.5 rounded border border-slate-800 text-slate-300 overflow-x-auto max-h-48 leading-relaxed whitespace-pre-wrap">
                  {item.chunk_text}
                </pre>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
