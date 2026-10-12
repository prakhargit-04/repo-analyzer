/**
 * Frontend AI Panels Contract Unit Tests (Session 23 Part A).
 * Uses Node.js built-in test runner.
 *
 * Covers:
 *  1. Analysis completeness rendering condition
 *  2. Citation location callback formatting
 *  3. Error state message formatting (no fabricated data)
 */
import test, { describe } from "node:test";
import assert from "node:assert/strict";

// Helper functions matching panel behavior
export function shouldRenderAIPanels(analysisStatus: string | null | undefined): boolean {
  if (!analysisStatus) return false;
  const s = analysisStatus.toLowerCase();
  return s === "completed" || s === "partial" || s === "complete";
}

export function formatCitationTarget(filePath: string, line: number): { path: string; line: number } {
  return {
    path: filePath.trim(),
    line: Math.max(1, Math.floor(line)),
  };
}

export function formatPanelErrorMessage(err: unknown): string {
  if (!err) return "An unexpected error occurred.";
  if (typeof err === "string") return err;
  if (typeof err === "object" && err !== null && "message" in err && typeof (err as { message: unknown }).message === "string") {
    return (err as { message: string }).message;
  }
  return "Failed to process request.";
}

describe("Frontend AI Panels Render Condition", () => {
  test("returns true for completed analysis", () => {
    assert.strictEqual(shouldRenderAIPanels("completed"), true);
    assert.strictEqual(shouldRenderAIPanels("complete"), true);
  });

  test("returns true for partial analysis", () => {
    assert.strictEqual(shouldRenderAIPanels("partial"), true);
  });

  test("returns false for queued or running analysis", () => {
    assert.strictEqual(shouldRenderAIPanels("queued"), false);
    assert.strictEqual(shouldRenderAIPanels("running"), false);
    assert.strictEqual(shouldRenderAIPanels("analyzing"), false);
  });

  test("returns false for failed analysis", () => {
    assert.strictEqual(shouldRenderAIPanels("failed"), false);
    assert.strictEqual(shouldRenderAIPanels("error"), false);
  });

  test("returns false for null or undefined status", () => {
    assert.strictEqual(shouldRenderAIPanels(null), false);
    assert.strictEqual(shouldRenderAIPanels(undefined), false);
    assert.strictEqual(shouldRenderAIPanels(""), false);
  });
});

describe("Citation Target Parsing", () => {
  test("formats citation target path and line number correctly", () => {
    const target = formatCitationTarget("src/pipeline/main.py", 42);
    assert.strictEqual(target.path, "src/pipeline/main.py");
    assert.strictEqual(target.line, 42);
  });

  test("strips whitespace from file path", () => {
    const target = formatCitationTarget("  src/app.py  ", 10);
    assert.strictEqual(target.path, "src/app.py");
    assert.strictEqual(target.line, 10);
  });

  test("enforces minimum line number of 1", () => {
    const target = formatCitationTarget("src/app.py", -5);
    assert.strictEqual(target.line, 1);
  });
});

describe("Panel Error State Formatting", () => {
  test("formats Error objects with message", () => {
    const err = new Error("Network timeout during RAG query");
    assert.strictEqual(formatPanelErrorMessage(err), "Network timeout during RAG query");
  });

  test("formats string errors", () => {
    assert.strictEqual(formatPanelErrorMessage("Backend 500 error"), "Backend 500 error");
  });

  test("returns fallback string for null or empty errors without fabricating output", () => {
    assert.strictEqual(formatPanelErrorMessage(null), "An unexpected error occurred.");
    assert.strictEqual(formatPanelErrorMessage(undefined), "An unexpected error occurred.");
  });
});
