/**
 * Component-level tests (server-side render, no DOM library needed).
 * Covers StatsGrid (incl. missing summary), HealthScorePanel (incl. reduced
 * component set) and the Assistant/Search error states (409/422/429/503).
 */
import test, { describe, afterEach } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { StatsGrid } from "../components/dashboard/StatsGrid";
import { HealthScorePanel } from "../components/dashboard/HealthScorePanel";
import { PanelError } from "../components/ui/PanelError";
import { ApiError, formatPanelErrorMessage } from "../lib/api-errors";
import { askRepositoryQuestion, type CanonicalAnalysisPayload } from "../lib/api";

const html = (el: React.ReactElement) => renderToStaticMarkup(el);
const noop = () => {};

function analysis(over: Partial<CanonicalAnalysisPayload> = {}): CanonicalAnalysisPayload {
  return {
    files_analyzed: 3,
    knowledge_graph: {
      nodes: [
        { id: "a.py", type: "file" },
        { id: "a.py::f", type: "function", file: "a.py" },
        { id: "a.py::C", type: "class", file: "a.py" },
        { id: "x", type: "finding", file: "a.py" },
      ],
      edges: [{ source: "a.py", target: "a.py::f", relation: "defines" }],
    },
    knowledge_graph_summary: {
      total_nodes: 4, total_edges: 1, call_edges_total: 7, call_edges_resolved_pct: 85.7,
    },
    ...over,
  } as unknown as CanonicalAnalysisPayload;
}

describe("StatsGrid", () => {
  test("renders summary-backed values", () => {
    const out = html(<StatsGrid analysis={analysis()} />);
    assert.match(out, /Files Analyzed/);
    assert.match(out, /85\.7%/);
    assert.match(out, />7</); // call edges from the summary
  });

  test("empty/missing summary falls back to graph counts and dashes, never crashes", () => {
    const out = html(
      <StatsGrid analysis={analysis({ knowledge_graph_summary: undefined })} />,
    );
    assert.match(out, /Graph Nodes/);
    assert.match(out, />4</);          // total nodes derived from nodes.length
    assert.match(out, />1</);          // total edges derived from edges.length
    assert.doesNotMatch(out, /undefined|NaN/);
    assert.match(out, /—/);            // call edges / resolved% unavailable
  });

  test("a graph with no nodes at all still renders", () => {
    const out = html(
      <StatsGrid analysis={analysis({ knowledge_graph: { nodes: [], edges: [] }, knowledge_graph_summary: {} as CanonicalAnalysisPayload["knowledge_graph_summary"] })} />,
    );
    assert.doesNotMatch(out, /undefined|NaN/);
  });
});

describe("HealthScorePanel", () => {
  test("no health score -> explicit empty state", () => {
    assert.match(html(<HealthScorePanel healthScore={null} onViewFindings={noop} />), /No health score data/);
  });

  test("full component set shows score and no reduced notice", () => {
    const out = html(
      <HealthScorePanel
        onViewFindings={noop}
        healthScore={{
          composite_health_score: 91.5, status: "complete",
          sub_scores: { complexity: 90, security: 93 },
          component_statuses: { complexity: "success", security: "success" },
          missing_components: [], reduced_component_set: false,
        }}
      />,
    );
    assert.match(out, /91\.5/);
    assert.doesNotMatch(out, /reduced-score-notice/);
  });

  test("shows the formula version when present and omits it for legacy rows", () => {
    const base = { composite_health_score: 90, status: "complete", sub_scores: { complexity: 90 }, component_statuses: {}, missing_components: [] };
    assert.match(html(<HealthScorePanel onViewFindings={noop} healthScore={{ ...base, formula_version: "2.1" }} />), /Scoring formula v2\.1/);
    assert.doesNotMatch(html(<HealthScorePanel onViewFindings={noop} healthScore={{ ...base, formula_version: null }} />), /formula-version/);
  });

  test("reduced component set is stated explicitly", () => {
    const out = html(
      <HealthScorePanel
        onViewFindings={noop}
        healthScore={{
          composite_health_score: 80, status: "partial",
          sub_scores: { complexity: 80, security: 80, sast: null, secrets: 80 },
          component_statuses: { sast: "unavailable" },
          missing_components: ["sast"], weights_renormalized: true, reduced_component_set: true,
        }}
      />,
    );
    assert.match(out, /reduced-score-notice/);
    assert.match(out, /3 of 4 components/);
    assert.match(out, /Missing components/);
  });
});

describe("Assistant / Search error states", () => {
  const render = (status: number, detail: string, retry?: number) =>
    html(<PanelError error={new ApiError(status, detail, retry)} />);

  test("409 embedding mismatch is actionable", () => {
    const out = render(409, "Re-run the analysis with the current embedding provider.");
    assert.match(out, /role="alert"/);
    assert.match(out, /Re-run the analysis/);
  });

  test("422 validation shows the field message", () => {
    assert.match(render(422, "question: String should have at most 1000 characters"), /at most 1000 characters/);
  });

  test("429 shows retry hint", () => {
    assert.match(render(429, "rate limited", 12), /Try again in 12 seconds/);
    assert.match(render(429, "rate limited"), /wait a moment/);
  });

  test("503 says the service is unavailable", () => {
    assert.match(render(503, "LLM provider is not configured."), /temporarily unavailable.*not configured/);
  });

  test("no error renders nothing; plain errors and strings still show", () => {
    assert.equal(html(<PanelError error={null} />), "");
    assert.match(html(<PanelError error={new Error("boom")} />), /boom/);
    assert.equal(formatPanelErrorMessage(undefined), "An unexpected error occurred.");
  });
});

describe("API client surfaces status + Retry-After to the panels", () => {
  const originalFetch = global.fetch;
  afterEach(() => { global.fetch = originalFetch; });

  test("askRepositoryQuestion throws ApiError with status and retryAfterSeconds", async () => {
    global.fetch = (async () =>
      new Response(JSON.stringify({ detail: "Too many requests" }), {
        status: 429, headers: { "Content-Type": "application/json", "Retry-After": "7" },
      })) as typeof fetch;
    await assert.rejects(
      () => askRepositoryQuestion("run1", "q"),
      (err: unknown) => err instanceof ApiError && err.status === 429 && err.retryAfterSeconds === 7,
    );
  });

  test("422 array detail becomes readable text, not JSON", async () => {
    global.fetch = (async () =>
      new Response(JSON.stringify({ detail: [{ loc: ["body", "question"], msg: "String should have at most 1000 characters" }] }), {
        status: 422, headers: { "Content-Type": "application/json" },
      })) as typeof fetch;
    await assert.rejects(
      () => askRepositoryQuestion("run1", "q"),
      (err: unknown) => err instanceof ApiError && err.status === 422 && /at most 1000/.test(err.detail) && !/\{/.test(err.detail),
    );
  });
});
