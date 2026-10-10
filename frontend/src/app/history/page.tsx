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

function shortSha(value: string) {
  return value ? value.slice(0, 10) : "—";
}

export default function AnalysisHistoryPage() {
  const [repoUrl, setRepoUrl] = useState<string>("https://github.com/pytest-dev/iniconfig");
  const [runs, setRuns] = useState<AnalysisRunItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState<boolean>(false);

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!repoUrl.trim() || loading) return;

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

  const completeCount = runs.filter((run) => run.analysis_status === "complete").length;
  const partialCount = runs.filter((run) => run.analysis_status === "partial").length;

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#070b14] text-slate-100">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -right-40 top-0 h-[28rem] w-[28rem] rounded-full bg-indigo-500/[0.08] blur-3xl" />
        <div className="absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.025)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.025)_1px,transparent_1px)] bg-[size:56px_56px] [mask-image:linear-gradient(to_bottom,black,transparent_85%)]" />
      </div>

      <nav className="relative z-10 border-b border-white/[0.07] bg-[#070b14]/75 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 sm:px-8">
          <Link href="/" className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyan-300/20 bg-cyan-300/10 text-sm font-bold text-cyan-200">RA</span>
            <span className="font-semibold tracking-tight text-white">Repo Analyzer</span>
          </Link>
          <Link href="/" className="rounded-lg border border-white/10 bg-white/[0.03] px-3.5 py-2 text-sm font-medium text-slate-300 transition hover:border-cyan-200/30 hover:text-white">
            <span aria-hidden="true">←</span> Back to workspace
          </Link>
        </div>
      </nav>

      <div className="relative z-10 mx-auto max-w-7xl px-5 py-10 sm:px-8 sm:py-14">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200/70">Workspace records</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-[-0.035em] text-white sm:text-4xl">Analysis history</h1>
            <p className="mt-3 max-w-xl text-sm leading-6 text-slate-400 sm:text-base">Review previous runs for a repository, compare commit revisions, and reopen an analysis with its source evidence.</p>
          </div>
          <div className="grid grid-cols-3 gap-2 sm:min-w-[20rem]">
            <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-3.5">
              <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Loaded</p>
              <p className="mt-2 text-2xl font-semibold tabular-nums text-white">{runs.length}</p>
            </div>
            <div className="rounded-xl border border-emerald-300/10 bg-emerald-300/[0.035] p-3.5">
              <p className="text-[10px] uppercase tracking-[0.14em] text-emerald-200/60">Complete</p>
              <p className="mt-2 text-2xl font-semibold tabular-nums text-emerald-100">{completeCount}</p>
            </div>
            <div className="rounded-xl border border-amber-300/10 bg-amber-300/[0.035] p-3.5">
              <p className="text-[10px] uppercase tracking-[0.14em] text-amber-200/60">Partial</p>
              <p className="mt-2 text-2xl font-semibold tabular-nums text-amber-100">{partialCount}</p>
            </div>
          </div>
        </div>

        <section className="mt-9 rounded-2xl border border-white/[0.1] bg-[#0d1423]/90 p-4 shadow-2xl shadow-black/10 sm:p-5">
          <form onSubmit={handleSearch} className="flex flex-col gap-3 md:flex-row">
            <label htmlFor="history-repo-url" className="sr-only">GitHub repository URL</label>
            <div className="flex min-w-0 flex-1 items-center gap-3 rounded-xl border border-white/[0.12] bg-[#070c16] px-3.5 focus-within:border-cyan-300/50 focus-within:ring-2 focus-within:ring-cyan-300/10">
              <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-slate-500" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="11" cy="11" r="7" /><path d="m16.2 16.2 4.3 4.3" /></svg>
              <input id="history-repo-url" type="url" value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="https://github.com/owner/repository" required className="min-w-0 flex-1 bg-transparent py-3.5 text-sm text-white outline-none placeholder:text-slate-600" />
            </div>
            <button type="submit" disabled={loading || !repoUrl.trim()} className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-300 to-sky-300 px-6 text-sm font-semibold text-slate-950 transition hover:from-cyan-200 hover:to-sky-200 disabled:cursor-not-allowed disabled:opacity-50">
              {loading ? <><span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-900/30 border-t-slate-900" /> Searching…</> : <>Find runs <span aria-hidden="true">→</span></>}
            </button>
          </form>
          {error && <div role="alert" className="mt-4 rounded-xl border border-rose-300/20 bg-rose-400/[0.07] p-3.5 text-sm text-rose-100">{error}</div>}
        </section>

        <section className="mt-7 overflow-hidden rounded-2xl border border-white/[0.09] bg-[#0b1120]/90">
          <div className="flex flex-col gap-2 border-b border-white/[0.08] px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <div>
              <h2 className="font-semibold text-white">Repository runs</h2>
              <p className="mt-1 text-xs text-slate-500">{searched ? `${runs.length} run${runs.length === 1 ? "" : "s"} returned` : "Search a repository to load its analysis history"}</p>
            </div>
            {searched && <span className="max-w-full truncate rounded-lg border border-white/[0.08] bg-white/[0.025] px-3 py-1.5 font-mono text-[11px] text-slate-500" title={repoUrl}>{repoUrl}</span>}
          </div>

          {loading ? (
            <div className="flex items-center justify-center gap-3 px-5 py-16 text-sm text-slate-400"><span className="h-5 w-5 animate-spin rounded-full border-2 border-cyan-300/25 border-t-cyan-200" />Loading saved runs…</div>
          ) : !searched ? (
            <div className="px-5 py-16 text-center sm:px-8">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] text-xl text-slate-400">⌕</div>
              <h3 className="mt-4 text-sm font-semibold text-slate-200">Look up a repository</h3>
              <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-500">Enter a GitHub URL above to find saved analysis runs and reopen their results.</p>
            </div>
          ) : runs.length === 0 ? (
            <div className="px-5 py-16 text-center sm:px-8">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] text-xl text-slate-400">∅</div>
              <h3 className="mt-4 text-sm font-semibold text-slate-200">No saved runs found</h3>
              <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-500">No analysis records were returned for this URL. You can start a new analysis from the workspace.</p>
              <Link href="/" className="mt-5 inline-flex rounded-lg border border-cyan-200/20 bg-cyan-200/[0.06] px-4 py-2 text-sm font-medium text-cyan-100 transition hover:bg-cyan-200/10">Analyze repository →</Link>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="bg-white/[0.025] text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                  <tr>
                    <th scope="col" className="px-5 py-3.5 sm:px-6">Run</th>
                    <th scope="col" className="px-5 py-3.5">Commit</th>
                    <th scope="col" className="px-5 py-3.5">Status</th>
                    <th scope="col" className="px-5 py-3.5">Files</th>
                    <th scope="col" className="px-5 py-3.5">Languages</th>
                    <th scope="col" className="px-5 py-3.5 text-right"> </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.055]">
                  {runs.map((run) => {
                    const complete = run.analysis_status === "complete";
                    const partial = run.analysis_status === "partial";
                    return (
                      <tr key={run.run_id} className="group transition hover:bg-white/[0.025]">
                        <td className="px-5 py-4 sm:px-6">
                          <span className="block max-w-[14rem] truncate font-mono text-xs text-slate-300" title={run.run_id}>{run.run_id}</span>
                        </td>
                        <td className="px-5 py-4"><code className="rounded-md border border-white/[0.07] bg-white/[0.025] px-2 py-1 text-xs text-slate-400" title={run.commit_sha}>{shortSha(run.commit_sha)}</code></td>
                        <td className="px-5 py-4">
                          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium ${complete ? "border-emerald-300/15 bg-emerald-300/[0.06] text-emerald-200" : partial ? "border-amber-300/15 bg-amber-300/[0.06] text-amber-200" : "border-rose-300/15 bg-rose-300/[0.06] text-rose-200"}`}>
                            <span className={`h-1.5 w-1.5 rounded-full ${complete ? "bg-emerald-300" : partial ? "bg-amber-300" : "bg-rose-300"}`} />{run.analysis_status}
                          </span>
                        </td>
                        <td className="px-5 py-4 tabular-nums text-slate-300">{run.files_analyzed.toLocaleString()}</td>
                        <td className="px-5 py-4"><div className="flex flex-wrap gap-1.5">{(run.languages ?? []).slice(0, 3).map((language) => <span key={language} className="rounded-md border border-white/[0.08] bg-white/[0.025] px-2 py-1 text-[10px] text-slate-400">{language}</span>)}</div></td>
                        <td className="px-5 py-4 text-right"><Link href={`/analyses/${run.run_id}`} className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.025] px-3 py-2 text-xs font-medium text-slate-300 transition hover:border-cyan-200/25 hover:text-cyan-100">Open <span className="transition-transform group-hover:translate-x-0.5" aria-hidden="true">→</span></Link></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
