"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { submitAnalysis } from "@/lib/api";

export default function Home() {
  const router = useRouter();

  const [repoUrl, setRepoUrl] = useState<string>("https://github.com/pytest-dev/iniconfig");
  const [commitSha, setCommitSha] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanUrl = repoUrl.trim();
    if (!cleanUrl) return;

    try {
      setSubmitting(true);
      setError(null);

      const job = await submitAnalysis({
        repo_url: cleanUrl,
        commit_sha: commitSha.trim() || undefined,
      });

      // Redirect to analysis job progress page
      router.push(`/analyses/${job.job_id}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to submit repository for analysis.";
      setError(msg);
    } finally {

      setSubmitting(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 text-white p-8">
      <div className="max-w-4xl mx-auto py-12">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-4xl font-bold">GitHub Project Analyzer</h1>
            <p className="text-slate-400 mt-2">
              Deep repository intelligence, static analysis, and knowledge graph engine
            </p>
          </div>

          <Link
            href="/history"
            className="text-sm bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-300 hover:text-white px-4 py-2 rounded-lg transition-colors"
          >
            Analysis History →
          </Link>
        </div>

        {/* Submission Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-8">
          <h2 className="text-xl font-bold mb-4">Analyze a Repository</h2>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                GitHub Repository URL <span className="text-rose-400">*</span>
              </label>
              <input
                type="url"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/owner/repository"
                required
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono text-sm"
              />
              <p className="text-xs text-slate-500 mt-1">
                Enter a remote Git repository URL (https://, http://, git@)
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Commit SHA or Ref <span className="text-slate-500">(Optional)</span>
              </label>
              <input
                type="text"
                value={commitSha}
                onChange={(e) => setCommitSha(e.target.value)}
                placeholder="e.g. 00e7d87c7353b1ffecc4cd55f19acfffedd5233e"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono text-sm"
              />
            </div>

            {error && (
              <div className="bg-rose-950/70 border border-rose-800 text-rose-200 rounded-lg p-4 text-sm font-mono">
                <div className="font-semibold mb-1">Backend Validation Error</div>
                <div>{error}</div>
              </div>
            )}

            <button
              type="submit"
              disabled={submitting || !repoUrl.trim()}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-semibold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2 text-base"
            >
              {submitting ? (
                <>
                  <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Submitting Job...
                </>
              ) : (
                "Analyze Repository"
              )}
            </button>
          </form>
        </div>

        {/* Quick Example Presets */}
        <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-4">
          <button
            type="button"
            onClick={() => {
              setRepoUrl("https://github.com/pytest-dev/iniconfig");
              setCommitSha("");
            }}
            className="text-left bg-slate-900/60 border border-slate-800/80 hover:border-slate-700 p-4 rounded-xl transition-all"
          >
            <div className="text-xs text-blue-400 font-semibold uppercase tracking-wider mb-1">
              Sample Python Repository
            </div>
            <div className="text-sm font-mono text-slate-200">pytest-dev/iniconfig</div>
            <div className="text-xs text-slate-400 mt-1">Python configuration parsing library</div>
          </button>

          <Link
            href="/history"
            className="text-left bg-slate-900/60 border border-slate-800/80 hover:border-slate-700 p-4 rounded-xl transition-all"
          >
            <div className="text-xs text-emerald-400 font-semibold uppercase tracking-wider mb-1">
              Database History
            </div>
            <div className="text-sm font-mono text-slate-200">View Recent Analyses</div>
            <div className="text-xs text-slate-400 mt-1">Browse past analysis runs and cached graphs</div>
          </Link>
        </div>
      </div>
    </main>
  );
}
