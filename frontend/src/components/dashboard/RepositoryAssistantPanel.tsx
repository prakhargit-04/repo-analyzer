"use client";

import React, { useState, useEffect } from "react";
import { askRepositoryQuestion, AskResponse, CitationItem, getAiStatus } from "@/lib/api";
import { getAiBadgeState, AiBadgeState } from "@/lib/ai-status-helper";

interface RepositoryAssistantPanelProps {
  runId: string;
  onSelectLocation?: (filePath: string, line: number) => void;
}

export function RepositoryAssistantPanel({
  runId,
  onSelectLocation,
}: RepositoryAssistantPanelProps) {
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [aiState, setAiState] = useState<AiBadgeState>(() => getAiBadgeState(null));

  useEffect(() => {
    getAiStatus()
      .then((data) => setAiState(getAiBadgeState(data)))
      .catch(() => setAiState(getAiBadgeState(null)));
  }, []);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const res = await askRepositoryQuestion(runId, question.trim(), topK);
      setResponse(res);
    } catch (err: any) {
      setError(err?.message || "Failed to generate repository-grounded answer");
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
        return "bg-purple-950 text-purple-300 border-purple-800";
      default:
        return "bg-slate-800 text-slate-400 border-slate-700";
    }
  };

  return (
    <div className="bg-slate-900 text-slate-100 rounded-xl p-5 border border-slate-800 shadow-xl space-y-4">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div>
          <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
            <svg className="w-5 h-5 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-4l-4 4z" />
            </svg>
            Repository Assistant (RAG Q&A)
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Ask questions grounded strictly in retrieved source evidence with exact file citations
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
          <span>Using deterministic test mode placeholders (Test Mode). Configure real providers in .env for production AI answering.</span>
        </div>
      )}


      <form onSubmit={handleAsk} className="flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. How is authentication or health score computed?"
          className="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-3.5 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-purple-500 placeholder-slate-500"
        />
        <select
          value={topK}
          onChange={(e) => setTopK(Number(e.target.value))}
          className="bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-purple-500 font-mono"
        >
          <option value={3}>3 Chunks</option>
          <option value={5}>5 Chunks</option>
          <option value={10}>10 Chunks</option>
        </select>
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white font-medium text-sm px-4 py-2 rounded-lg transition-colors flex items-center gap-1.5"
        >
          {loading ? (
            <>
              <svg className="animate-spin h-4 w-4 text-white" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              Thinking...
            </>
          ) : (
            "Ask"
          )}
        </button>
      </form>

      {error && (
        <div className="bg-red-950/60 border border-red-800 text-red-300 text-xs p-3 rounded-lg">
          {error}
        </div>
      )}

      {response && (
        <div className="space-y-4 pt-2 border-t border-slate-800">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span className="font-semibold text-purple-300">Grounded Answer</span>
              <span className="font-mono text-slate-500">
                {response.retrieved_chunks_count} chunks evaluated
              </span>
            </div>
            <div className="bg-slate-950 border border-slate-800 p-4 rounded-lg text-sm text-slate-200 leading-relaxed font-sans whitespace-pre-wrap">
              {response.answer}
            </div>
          </div>

          {response.citations && response.citations.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                Source Evidence Citations ({response.citations.length})
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {response.citations.map((cite: CitationItem) => (
                  <button
                    key={cite.citation_id || cite.chunk_id}
                    onClick={() => onSelectLocation?.(cite.file_path, cite.start_line)}
                    className="text-left bg-slate-950 hover:bg-slate-800/80 border border-slate-800 hover:border-slate-700 p-2.5 rounded-lg transition-colors flex items-start gap-2 group"
                  >
                    <span className="bg-purple-950 text-purple-300 border border-purple-800 font-mono text-xs font-bold px-2 py-0.5 rounded">
                      [{cite.citation_id}]
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-mono text-slate-200 truncate group-hover:text-purple-300 transition-colors">
                        {cite.file_path}
                      </div>
                      <div className="text-[11px] text-slate-500 font-mono flex items-center justify-between mt-0.5">
                        <span>Lines {cite.start_line}-{cite.end_line}</span>
                        {cite.entity_name && (
                          <span className="text-slate-400 truncate max-w-[120px]">
                            {cite.entity_name}
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
