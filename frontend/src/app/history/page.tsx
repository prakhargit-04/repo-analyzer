"use client";

import { useState } from "react";
import Link from "next/link";
import { getRepositoryRuns } from "@/lib/api";

interface AnalysisRunItem {
  run_id: string;
  commit_sha: string;
  analysis_status: string;
  files_analyzed: number;
  languages: string[];
}

export default function AnalysisHistoryPage() {
  const [repoUrl, setRepoUrl] = useState<string>("https://github.com/pytest-dev/iniconfig");
  const [runs, setRuns] = useState<AnalysisRunItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState<boolean>(false);

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!repoUrl.trim()) return;

    try {
      setLoading(true);
      setError(null);
      setSearched(true);
      const res = await getRepositoryRuns(repoUrl.trim());

      setRuns(res.runs || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to fetch repository history from backend";
      setError(msg);
      setRuns([]);
    } finally {
      setLoading(false);
    }
  };


  return (
    <main className="min-h-screen bg-slate-950 text-white p-8">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <Link href="/" className="text-slate-400 hover:text-white text-sm">
            ← Back to Home
          </Link>
        </div>

        <h1 className="text-4xl font-bold">Analysis History</h1>
        <p className="text-slate-400 mt-1">Search historical analysis runs from the database backend</p>

        {/* Search form */}
        <form onSubmit={handleSearch} className="mt-6 flex flex-col sm:flex-row gap-3">
          <input
            type="url"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="Enter GitHub Repository URL (https://github.com/owner/repo)"
            required
            className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
          <button
            type="submit"
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-medium px-6 py-3 rounded-lg transition-colors"
          >
            {loading ? "Searching..." : "Search Runs"}
          </button>
        </form>

        {/* Error message */}
        {error && (
          <div className="mt-6 bg-rose-950/60 border border-rose-800 text-rose-200 rounded-xl p-4 text-sm">
            {error}
          </div>
        )}

        {/* Results table */}
        {searched && !loading && (
          <div className="mt-8 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-800 flex justify-between items-center">
              <h2 className="text-lg font-semibold">Repository Runs ({runs.length})</h2>
              <span className="text-xs text-slate-400">{repoUrl}</span>
            </div>

            {runs.length === 0 ? (
              <div className="p-8 text-center text-slate-500 text-sm">
                No analysis runs found for this repository.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm text-slate-300">
                  <thead className="bg-slate-950 text-xs text-slate-400 uppercase border-b border-slate-800">
                    <tr>
                      <th className="px-6 py-3">Run ID</th>
                      <th className="px-6 py-3">Commit SHA</th>
                      <th className="px-6 py-3">Status</th>
                      <th className="px-6 py-3">Files</th>
                      <th className="px-6 py-3">Languages</th>
                      <th className="px-6 py-3">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800">
                    {runs.map((r) => (
                      <tr key={r.run_id} className="hover:bg-slate-850">
                        <td className="px-6 py-4 font-mono text-xs text-white">{r.run_id}</td>
                        <td className="px-6 py-4 font-mono text-xs">{r.commit_sha}</td>
                        <td className="px-6 py-4">
                          <span
                            className={`px-2 py-1 rounded-full text-xs font-semibold ${
                              r.analysis_status === "complete"
                                ? "bg-emerald-950 text-emerald-300 border border-emerald-800"
                                : "bg-amber-950 text-amber-300 border border-amber-800"
                            }`}
                          >
                            {r.analysis_status}
                          </span>
                        </td>
                        <td className="px-6 py-4">{r.files_analyzed}</td>
                        <td className="px-6 py-4">{r.languages ? r.languages.join(", ") : "python"}</td>
                        <td className="px-6 py-4">
                          <Link
                            href={`/analyses/${r.run_id}`}
                            className="text-blue-400 hover:text-blue-300 font-medium text-xs"
                          >
                            View Result →
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
