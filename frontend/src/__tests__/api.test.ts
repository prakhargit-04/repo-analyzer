/**
 * Frontend API client unit tests using Node.js test runner.
 */
import test, { describe, afterEach } from "node:test";

import assert from "node:assert";
import {
  submitAnalysis,
  getJobStatus,
  getAnalysis,
  getAnalysisFindings,
  getAnalysisFiles,
  getFileDetail,
  CanonicalAnalysisPayload,
} from "../lib/api";

describe("Frontend API Client & Contract", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
  });

  test("submitAnalysis sends POST request to /api/v1/analyses", async () => {
    const mockJobResponse = {
      job_id: "test-job-123",
      repo_url: "https://github.com/pytest-dev/iniconfig",
      status: "queued",
      current_stage: "queued",
      progress: 0,
      cache_hit: false,
      stages: [],
    };

    global.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
      assert.strictEqual(url.toString().includes("/api/v1/analyses"), true);
      assert.strictEqual(init?.method, "POST");
      return new Response(JSON.stringify(mockJobResponse), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    const res = await submitAnalysis({
      repo_url: "https://github.com/pytest-dev/iniconfig",
    });

    assert.strictEqual(res.job_id, "test-job-123");
    assert.strictEqual(res.status, "queued");
  });

  test("submitAnalysis throws error on backend validation rejection", async () => {
    global.fetch = (async () => {
      return new Response(
        JSON.stringify({ detail: "Local file paths are not accepted via the API." }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    await assert.rejects(
      async () => {
        await submitAnalysis({ repo_url: "/tmp/invalid_path" });
      },
      { message: "Local file paths are not accepted via the API." }
    );
  });

  test("getJobStatus fetches status for given job_id", async () => {
    const mockStatus = {
      job_id: "test-job-123",
      repo_url: "https://github.com/pytest-dev/iniconfig",
      status: "analyzing",
      current_stage: "analyzing",
      progress: 50,
      cache_hit: false,
    };

    global.fetch = (async () => {
      return new Response(JSON.stringify(mockStatus), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    const statusRes = await getJobStatus("test-job-123");
    assert.strictEqual(statusRes.status, "analyzing");
    assert.strictEqual(statusRes.progress, 50);
  });

  test("getAnalysis fetches canonical analysis payload for given run_id", async () => {
    const mockPayload: Partial<CanonicalAnalysisPayload> = {
      schema_version: "1.0.0",
      repository: "https://github.com/pytest-dev/iniconfig",
      commit_sha: "00e7d87c7353b1ffecc4cd55f19acfffedd5233e",
      analysis_status: "complete",
      files_analyzed: 2,
    };

    global.fetch = (async () => {
      return new Response(JSON.stringify(mockPayload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    const payload = await getAnalysis("run-uuid-456");
    assert.strictEqual(payload.repository, "https://github.com/pytest-dev/iniconfig");
    assert.strictEqual(payload.files_analyzed, 2);
  });

  // ── S17 additions ────────────────────────────────────────────────────────

  test("getAnalysisFindings sends correct severity query param", async () => {
    let capturedUrl = "";
    global.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(
        JSON.stringify({
          run_id: "run-1",
          findings: [],
          pagination: { total: 0, limit: 25, offset: 0 },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    await getAnalysisFindings("run-1", { severity: "HIGH", limit: 25, offset: 0 });
    assert.ok(
      capturedUrl.includes("severity=HIGH"),
      `Expected severity=HIGH in URL, got: ${capturedUrl}`
    );
  });

  test("getAnalysisFindings sends correct analyzer query param", async () => {
    let capturedUrl = "";
    global.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(
        JSON.stringify({
          run_id: "run-1",
          findings: [],
          pagination: { total: 0, limit: 25, offset: 0 },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    await getAnalysisFindings("run-1", { analyzer: "bandit" });
    assert.ok(
      capturedUrl.includes("analyzer=bandit"),
      `Expected analyzer=bandit in URL, got: ${capturedUrl}`
    );
  });

  test("getAnalysisFindings handles empty findings array correctly", async () => {
    global.fetch = (async () => {
      return new Response(
        JSON.stringify({
          run_id: "run-empty",
          findings: [],
          pagination: { total: 0, limit: 25, offset: 0 },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    const result = await getAnalysisFindings("run-empty");
    assert.strictEqual(result.findings.length, 0);
    assert.strictEqual(result.pagination.total, 0);
  });

  test("getAnalysisFiles sends correct pagination query params", async () => {
    let capturedUrl = "";
    global.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(
        JSON.stringify({
          run_id: "run-1",
          files: [],
          pagination: { total: 0, limit: 25, offset: 25 },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    await getAnalysisFiles("run-1", { limit: 25, offset: 25 });
    assert.ok(
      capturedUrl.includes("limit=25"),
      `Expected limit=25 in URL, got: ${capturedUrl}`
    );
    assert.ok(
      capturedUrl.includes("offset=25"),
      `Expected offset=25 in URL, got: ${capturedUrl}`
    );
  });

  test("getAnalysisFiles handles empty files array correctly", async () => {
    global.fetch = (async () => {
      return new Response(
        JSON.stringify({
          run_id: "run-empty",
          files: [],
          pagination: { total: 0, limit: 25, offset: 0 },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    const result = await getAnalysisFiles("run-empty");
    assert.strictEqual(result.files.length, 0);
    assert.strictEqual(result.pagination.total, 0);
  });

  test("getFileDetail encodes file path correctly in URL", async () => {
    let capturedUrl = "";
    global.fetch = (async (url: string | URL | Request) => {
      capturedUrl = url.toString();
      return new Response(
        JSON.stringify({
          run_id: "run-1",
          file_path: "src/iniconfig/__init__.py",
          language: "python",
          parse_error: null,
          entities: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    await getFileDetail("run-1", "src/iniconfig/__init__.py");

    // Slashes should be preserved; __init__ should be encoded (%5F%5F...)
    assert.ok(
      capturedUrl.includes("src/iniconfig/"),
      `Expected path segments in URL, got: ${capturedUrl}`
    );
    assert.ok(
      capturedUrl.includes("__init__") || capturedUrl.includes("%5F%5Finit%5F%5F"),
      `Expected __init__ (encoded or plain) in URL, got: ${capturedUrl}`
    );
  });

  test("getFileDetail returns entity list including nullable fields", async () => {
    const mockDetail = {
      run_id: "run-1",
      file_path: "src/foo.py",
      language: "python",
      parse_error: null,
      entities: [
        {
          id: "fn::foo",
          type: "function",
          name: "foo",
          file: "src/foo.py",
          start_line: 10,
          end_line: 20,
        },
        {
          id: "finding::bandit::src/foo.py::15",
          type: "finding",
          analyzer: "bandit",
          severity: "LOW",
          message: "Use of assert",
          line: 15,
          // Deliberately omit col and end_line to test nullable handling
        },
      ],
    };

    global.fetch = (async () => {
      return new Response(JSON.stringify(mockDetail), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    const detail = await getFileDetail("run-1", "src/foo.py");
    assert.strictEqual(detail.entities.length, 2);
    assert.strictEqual(detail.language, "python");
    assert.strictEqual(detail.parse_error, null);
  });

  test("getFileDetail throws on 404 response", async () => {
    global.fetch = (async () => {
      return new Response(
        JSON.stringify({ detail: "Analysis run 'bad-id' not found" }),
        { status: 404, headers: { "Content-Type": "application/json" } }
      );
    }) as typeof fetch;

    await assert.rejects(
      async () => {
        await getFileDetail("bad-id", "src/foo.py");
      },
      (err: Error) => {
        assert.ok(err.message.includes("bad-id") || err.message.includes("404"));
        return true;
      }
    );
  });
});
