/**
 * Frontend API client unit tests using Node.js test runner.
 */
import test, { describe, afterEach } from "node:test";

import assert from "node:assert";
import { submitAnalysis, getJobStatus, getAnalysis, CanonicalAnalysisPayload } from "../lib/api";

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
});
