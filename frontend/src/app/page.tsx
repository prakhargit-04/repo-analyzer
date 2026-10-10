"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { submitAnalysis } from "@/lib/api";

const capabilityCards = [
  {
    number: "01",
    title: "Static analysis",
    detail: "Complexity, maintainability, and security signals in one review.",
  },
  {
    number: "02",
    title: "Architecture graph",
    detail: "Explore files, definitions, imports, and likely call relationships.",
  },
  {
    number: "03",
    title: "Evidence-backed answers",
    detail: "Search source chunks and inspect citations down to file and line.",
  },
];

function BrandMark() {
  return (
    <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyan-300/20 bg-cyan-300/10 text-sm font-bold tracking-tight text-cyan-200 shadow-[0_0_24px_rgba(34,211,238,0.08)]">
      RA
    </span>
  );
}

export default function Home() {
  const router = useRouter();
  const [repoUrl, setRepoUrl] = useState<string>("https://github.com/pytest-dev/iniconfig");
  const [commitSha, setCommitSha] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanUrl = repoUrl.trim();
    if (!cleanUrl || submitting) return;

    try {
      setSubmitting(true);
      setError(null);
      const job = await submitAnalysis({
        repo_url: cleanUrl,
        commit_sha: commitSha.trim() || undefined,
      });
      router.push(`/analyses/${job.job_id}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to submit repository for analysis.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const chooseRepository = (url: string) => {
    setRepoUrl(url);
    setCommitSha("");
    setError(null);
  };

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#070b14] text-slate-100 selection:bg-cyan-300/30">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-56 left-[8%] h-[34rem] w-[34rem] rounded-full bg-cyan-500/[0.08] blur-3xl" />
        <div className="absolute right-[-10rem] top-[18rem] h-[30rem] w-[30rem] rounded-full bg-indigo-500/[0.10] blur-3xl" />
        <div className="absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.035)_1px,transparent_1px)] bg-[size:56px_56px] [mask-image:linear-gradient(to_bottom,black,transparent_76%)]" />
      </div>

      <nav className="relative z-10 border-b border-white/[0.07] bg-[#070b14]/75 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 sm:px-8">
          <Link href="/" className="flex items-center gap-3" aria-label="Repo Analyzer home">
            <BrandMark />
            <span className="font-semibold tracking-tight text-white">Repo Analyzer</span>
            <span className="hidden rounded-full border border-white/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.16em] text-slate-500 sm:inline-flex">Developer preview</span>
          </Link>
          <div className="flex items-center gap-3 sm:gap-6">
            <a href="#capabilities" className="hidden text-sm text-slate-400 transition hover:text-white sm:inline">Capabilities</a>
            <Link href="/history" className="rounded-lg border border-white/10 bg-white/[0.03] px-3.5 py-2 text-sm font-medium text-slate-200 transition hover:border-cyan-200/30 hover:bg-white/[0.06]">
              Analysis history <span aria-hidden="true">↗</span>
            </Link>
          </div>
        </div>
      </nav>

      <div className="relative z-10 mx-auto max-w-7xl px-5 pb-16 pt-12 sm:px-8 sm:pt-20 lg:pb-24 lg:pt-24">
        <div className="grid items-start gap-12 lg:grid-cols-[1.05fr_0.85fr] lg:gap-16">
          <section className="max-w-2xl">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-cyan-300/15 bg-cyan-300/[0.06] px-3 py-1.5 text-xs font-medium tracking-wide text-cyan-100/90">
              <span className="h-1.5 w-1.5 rounded-full bg-cyan-300 shadow-[0_0_10px_rgba(103,232,249,0.8)]" />
              SOURCE-LEVEL REPOSITORY INTELLIGENCE
            </div>
            <h1 className="max-w-3xl text-4xl font-semibold leading-[1.08] tracking-[-0.045em] text-white sm:text-5xl lg:text-6xl">
              Understand the codebase,
              <span className="mt-1 block bg-gradient-to-r from-cyan-200 via-sky-300 to-indigo-300 bg-clip-text pb-2 text-transparent">not just the README.</span>
            </h1>
            <p className="mt-6 max-w-xl text-base leading-7 text-slate-400 sm:text-lg sm:leading-8">
              Trace repository structure, surface static-analysis findings, explore dependencies, and ask questions grounded in real source evidence.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-3 text-sm text-slate-400">
              <span className="inline-flex items-center gap-2"><span className="text-cyan-300">✓</span> Commit-aware analysis</span>
              <span className="inline-flex items-center gap-2"><span className="text-cyan-300">✓</span> Source-linked evidence</span>
              <span className="inline-flex items-center gap-2"><span className="text-cyan-300">✓</span> Explicit AI mode</span>
            </div>

            <div className="relative mt-12 overflow-hidden rounded-2xl border border-white/10 bg-[#0c1322]/90 p-5 shadow-2xl shadow-black/20 sm:p-6">
              <div className="flex items-center justify-between border-b border-white/[0.07] pb-4">
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">Analysis pipeline</p>
                  <p className="mt-1 text-sm font-medium text-slate-200">From source to evidence</p>
                </div>
                <span className="rounded-md border border-emerald-300/15 bg-emerald-300/[0.06] px-2 py-1 font-mono text-[10px] text-emerald-200">TRACEABLE</span>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { step: "01", title: "Parse", sub: "AST + entities", tone: "cyan" },
                  { step: "02", title: "Analyze", sub: "Quality + security", tone: "blue" },
                  { step: "03", title: "Connect", sub: "Graph + provenance", tone: "indigo" },
                  { step: "04", title: "Explore", sub: "Search + citations", tone: "emerald" },
                ].map((item) => (
                  <div key={item.step} className="relative rounded-xl border border-white/[0.08] bg-white/[0.025] p-3.5">
                    <span className="font-mono text-[10px] text-slate-500">{item.step}</span>
                    <p className="mt-3 text-sm font-semibold text-slate-100">{item.title}</p>
                    <p className="mt-1 text-[11px] leading-4 text-slate-500">{item.sub}</p>
                    <div className={`mt-4 h-1 w-9 rounded-full ${item.tone === "cyan" ? "bg-cyan-300/80" : item.tone === "blue" ? "bg-sky-300/80" : item.tone === "indigo" ? "bg-indigo-300/80" : "bg-emerald-300/80"}`} />
                  </div>
                ))}
              </div>
              <p className="mt-4 text-xs leading-5 text-slate-500">Findings and answers remain tied to a repository revision and source evidence. AI output is not a substitute for reviewing the underlying code.</p>
            </div>
          </section>

          <section aria-labelledby="analyze-title" className="relative">
            <div className="absolute -inset-3 rounded-[2rem] bg-gradient-to-b from-cyan-300/[0.07] via-indigo-400/[0.04] to-transparent blur-xl" />
            <div className="relative overflow-hidden rounded-2xl border border-white/[0.12] bg-[#0d1423]/95 shadow-[0_24px_100px_rgba(0,0,0,0.35)]">
              <div className="border-b border-white/[0.08] px-6 py-5 sm:px-7">
                <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em] text-cyan-200/80">
                  <span className="flex h-6 w-6 items-center justify-center rounded-md bg-cyan-200/10 text-cyan-200">↳</span>
                  Start an analysis
                </div>
                <h2 id="analyze-title" className="mt-3 text-xl font-semibold tracking-tight text-white">Inspect a repository</h2>
                <p className="mt-1.5 text-sm leading-6 text-slate-400">Submit a public GitHub repository and follow the analysis through to source-level evidence.</p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-5 px-6 py-6 sm:px-7 sm:py-7" aria-busy={submitting}>
                <div>
                  <label htmlFor="repo-url" className="mb-2 block text-sm font-medium text-slate-200">GitHub repository URL <span className="text-rose-300">*</span></label>
                  <div className="flex items-center gap-3 rounded-xl border border-white/[0.12] bg-[#070c16] px-3.5 transition focus-within:border-cyan-300/50 focus-within:ring-2 focus-within:ring-cyan-300/10">
                    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-slate-500" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 6v-3.4a3 3 0 0 0-.8-2.3c2.7-.3 5.5-1.3 5.5-6A4.7 4.7 0 0 0 18.4 7a4.3 4.3 0 0 0-.1-3.1S17.3 3.6 15 5.1a12.9 12.9 0 0 0-6 0C6.7 3.6 5.7 3.9 5.7 3.9A4.3 4.3 0 0 0 5.6 7a4.7 4.7 0 0 0-1.3 3.3c0 4.7 2.8 5.7 5.5 6A3 3 0 0 0 9 18.6V22" /></svg>
                    <input id="repo-url" type="url" value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="https://github.com/owner/repository" required autoComplete="url" className="min-w-0 flex-1 bg-transparent py-3.5 text-sm text-white outline-none placeholder:text-slate-600" />
                  </div>
                  <p className="mt-2 text-xs leading-5 text-slate-500">GitHub HTTPS repository URLs only (https://github.com/&lt;owner&gt;/&lt;repo&gt;).</p>
                </div>

                <div>
                  <label htmlFor="commit-sha" className="mb-2 block text-sm font-medium text-slate-200">Exact commit SHA <span className="font-normal text-slate-500">(optional)</span></label>
                  <input id="commit-sha" type="text" value={commitSha} onChange={(e) => setCommitSha(e.target.value)} placeholder="e.g. 00e7d87c…" autoComplete="off" spellCheck={false} className="w-full rounded-xl border border-white/[0.12] bg-[#070c16] px-3.5 py-3 font-mono text-xs text-slate-200 outline-none transition placeholder:text-slate-600 focus:border-cyan-300/50 focus:ring-2 focus:ring-cyan-300/10" />
                  <p className="mt-2 text-xs leading-5 text-slate-500">Pin a revision for reproducible analysis. Leave empty to resolve the default branch.</p>
                </div>

                {error && (
                  <div role="alert" className="rounded-xl border border-rose-300/20 bg-rose-400/[0.07] p-3.5 text-sm text-rose-100">
                    <div className="mb-1 font-semibold">Could not start analysis</div>
                    <div className="break-words leading-5 text-rose-100/80">{error}</div>
                  </div>
                )}

                <button type="submit" disabled={submitting || !repoUrl.trim()} className="group flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-300 to-sky-300 px-5 py-3.5 text-sm font-semibold text-slate-950 shadow-lg shadow-cyan-900/20 transition hover:from-cyan-200 hover:to-sky-200 disabled:cursor-not-allowed disabled:opacity-50">
                  {submitting ? <><span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-900/30 border-t-slate-900" /> Submitting repository…</> : <>Analyze repository <span className="text-base transition-transform group-hover:translate-x-0.5" aria-hidden="true">→</span></>}
                </button>
                <p className="text-center text-[11px] leading-5 text-slate-600">Analysis runs on the configured backend. Availability and live-AI capabilities depend on server configuration.</p>
              </form>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3">
              <button type="button" onClick={() => chooseRepository("https://github.com/pytest-dev/iniconfig")} className="group rounded-xl border border-white/[0.08] bg-white/[0.025] p-3.5 text-left transition hover:border-cyan-200/25 hover:bg-white/[0.05]">
                <span className="text-[10px] font-semibold uppercase tracking-[0.15em] text-cyan-200/70">Python sample</span>
                <span className="mt-2 block text-sm font-medium text-slate-200 group-hover:text-white">iniconfig <span className="text-slate-600">↗</span></span>
                <span className="mt-1 block text-xs leading-5 text-slate-500">Small config parser</span>
              </button>
              <button type="button" onClick={() => chooseRepository("https://github.com/ljharb/qs")} className="group rounded-xl border border-white/[0.08] bg-white/[0.025] p-3.5 text-left transition hover:border-indigo-200/25 hover:bg-white/[0.05]">
                <span className="text-[10px] font-semibold uppercase tracking-[0.15em] text-indigo-200/70">JavaScript sample</span>
                <span className="mt-2 block text-sm font-medium text-slate-200 group-hover:text-white">qs <span className="text-slate-600">↗</span></span>
                <span className="mt-1 block text-xs leading-5 text-slate-500">Query string utilities</span>
              </button>
            </div>
          </section>
        </div>

        <section id="capabilities" className="mt-20 border-t border-white/[0.08] pt-10 sm:mt-24 sm:pt-12">
          <div className="mb-7 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">What you can inspect</p>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight text-white">From repository structure to evidence</h2>
            </div>
            <p className="max-w-md text-sm leading-6 text-slate-500">The interface is built around traceability—not an opaque one-shot summary.</p>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {capabilityCards.map((card) => (
              <article key={card.number} className="group rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5 transition hover:-translate-y-0.5 hover:border-white/[0.15] hover:bg-white/[0.035] sm:p-6">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-cyan-200/65">{card.number}</span>
                  <span className="text-slate-600 transition group-hover:translate-x-1 group-hover:text-cyan-200" aria-hidden="true">↗</span>
                </div>
                <h3 className="mt-5 text-base font-semibold text-slate-100">{card.title}</h3>
                <p className="mt-2 text-sm leading-6 text-slate-500">{card.detail}</p>
              </article>
            ))}
          </div>
        </section>
      </div>
      <footer className="relative z-10 border-t border-white/[0.07] px-5 py-5 sm:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 text-xs text-slate-600 sm:flex-row sm:items-center sm:justify-between">
          <span>Repo Analyzer · Evidence-led repository inspection</span>
          <span>Test embeddings are non-semantic; validate AI results against source evidence.</span>
        </div>
      </footer>
    </main>
  );
}
