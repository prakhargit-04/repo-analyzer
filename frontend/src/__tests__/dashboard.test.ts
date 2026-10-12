/**
 * S17 Dashboard utility unit tests.
 * Uses the Node.js built-in test runner — no additional test framework required.
 *
 * Run: node --test src/__tests__/dashboard.test.ts
 * (requires ts-node or ts-jest transpilation; see package.json test script)
 */
import test, { describe } from "node:test";
import assert from "node:assert/strict";

import {
  formatScore,
  getScoreLevel,
  separateEntities,
  getFileLanguage,
  truncateSha,
  repoDisplayName,
} from "../lib/dashboard-utils";

// ─── formatScore ──────────────────────────────────────────────────────────────

describe("formatScore", () => {
  test("formats a number to one decimal place", () => {
    assert.strictEqual(formatScore(79.42), "79.4");
    assert.strictEqual(formatScore(100), "100.0");
    assert.strictEqual(formatScore(0), "0.0");
    assert.strictEqual(formatScore(81.25), "81.3");
  });

  test("returns N/A for null", () => {
    assert.strictEqual(formatScore(null), "N/A");
  });

  test("returns N/A for undefined", () => {
    assert.strictEqual(formatScore(undefined), "N/A");
  });
});

// ─── getScoreLevel ────────────────────────────────────────────────────────────

describe("getScoreLevel", () => {
  test("returns good for score >= 80", () => {
    assert.strictEqual(getScoreLevel(80), "good");
    assert.strictEqual(getScoreLevel(100), "good");
    assert.strictEqual(getScoreLevel(95.5), "good");
  });

  test("returns warning for score 60–79.9", () => {
    assert.strictEqual(getScoreLevel(60), "warning");
    assert.strictEqual(getScoreLevel(79.99), "warning");
    assert.strictEqual(getScoreLevel(61.67), "warning");
  });

  test("returns poor for score below 60", () => {
    assert.strictEqual(getScoreLevel(0), "poor");
    assert.strictEqual(getScoreLevel(59.9), "poor");
    assert.strictEqual(getScoreLevel(1), "poor");
  });

  test("returns unknown for null", () => {
    assert.strictEqual(getScoreLevel(null), "unknown");
  });

  test("returns unknown for undefined", () => {
    assert.strictEqual(getScoreLevel(undefined), "unknown");
  });
});

// ─── separateEntities ────────────────────────────────────────────────────────

describe("separateEntities", () => {
  test("separates finding nodes from code entities", () => {
    const entities = [
      { id: "1", type: "function", name: "foo" },
      { id: "2", type: "finding", analyzer: "bandit" },
      { id: "3", type: "class", name: "Bar" },
      { id: "4", type: "finding", analyzer: "semgrep" },
    ];
    const { codeEntities, findingEntities } = separateEntities(entities);
    assert.strictEqual(codeEntities.length, 2);
    assert.strictEqual(findingEntities.length, 2);
  });

  test("handles an empty array", () => {
    const { codeEntities, findingEntities } = separateEntities([]);
    assert.strictEqual(codeEntities.length, 0);
    assert.strictEqual(findingEntities.length, 0);
  });

  test("treats entities without a type as code entities", () => {
    const entities = [{ id: "1" }, { id: "2", type: null }];
    const { codeEntities, findingEntities } = separateEntities(entities);
    assert.strictEqual(codeEntities.length, 2);
    assert.strictEqual(findingEntities.length, 0);
  });

  test("treats file-type nodes as code entities (not findings)", () => {
    const entities = [{ id: "src/foo.py", type: "file" }];
    const { codeEntities } = separateEntities(entities);
    assert.strictEqual(codeEntities.length, 1);
  });

  test("all-findings array works correctly", () => {
    const entities = [
      { id: "f1", type: "finding" },
      { id: "f2", type: "finding" },
    ];
    const { codeEntities, findingEntities } = separateEntities(entities);
    assert.strictEqual(codeEntities.length, 0);
    assert.strictEqual(findingEntities.length, 2);
  });
});

// ─── getFileLanguage ─────────────────────────────────────────────────────────

describe("getFileLanguage", () => {
  test("returns explicit language when provided and non-empty", () => {
    assert.strictEqual(getFileLanguage("foo.py", "python"), "python");
    assert.strictEqual(getFileLanguage("foo.java", "java"), "java");
  });

  test("ignores unknown as explicit language and falls back to extension", () => {
    assert.strictEqual(getFileLanguage("foo.py", "unknown"), "python");
  });

  test("ignores null and falls back to extension inference", () => {
    assert.strictEqual(getFileLanguage("src/foo.py", null), "python");
    assert.strictEqual(getFileLanguage("src/Foo.java", null), "java");
    assert.strictEqual(getFileLanguage("src/foo.ts", null), "typescript");
    assert.strictEqual(getFileLanguage("src/foo.tsx", null), "typescript");
    assert.strictEqual(getFileLanguage("src/foo.js", null), "javascript");
    assert.strictEqual(getFileLanguage("src/foo.jsx", null), "javascript");
  });

  test("returns unknown for unrecognised extensions", () => {
    assert.strictEqual(getFileLanguage("Makefile", null), "unknown");
    assert.strictEqual(getFileLanguage("src/config.rb", null), "unknown");
    assert.strictEqual(getFileLanguage("src/main.go", null), "unknown");
  });

  test("handles file paths with multiple dots correctly", () => {
    // Should match last extension
    assert.strictEqual(getFileLanguage("src/foo.test.py", null), "python");
  });
});

// ─── truncateSha ─────────────────────────────────────────────────────────────

describe("truncateSha", () => {
  const FULL_SHA = "00e7d87c7353b1ffecc4cd55f19acfffedd5233e";

  test("truncates a full SHA to the requested length with ellipsis", () => {
    const result = truncateSha(FULL_SHA, 16);
    assert.strictEqual(result, "00e7d87c7353b1ff…");
    assert.strictEqual(result.length, 17); // 16 chars + ellipsis char
  });

  test("returns full SHA when shorter than the limit", () => {
    assert.strictEqual(truncateSha("abc123", 16), "abc123");
  });

  test("returns — for null", () => {
    assert.strictEqual(truncateSha(null), "—");
  });

  test("returns — for undefined", () => {
    assert.strictEqual(truncateSha(undefined), "—");
  });

  test("returns — for empty string", () => {
    assert.strictEqual(truncateSha(""), "—");
  });
});

// ─── repoDisplayName ─────────────────────────────────────────────────────────

describe("repoDisplayName", () => {
  test("extracts last two path segments from a GitHub URL", () => {
    assert.strictEqual(
      repoDisplayName("https://github.com/pytest-dev/iniconfig"),
      "pytest-dev/iniconfig"
    );
  });

  test("strips .git suffix before parsing", () => {
    assert.strictEqual(
      repoDisplayName("https://github.com/owner/repo.git"),
      "owner/repo"
    );
  });

  test("returns — for null", () => {
    assert.strictEqual(repoDisplayName(null), "—");
  });

  test("returns — for undefined", () => {
    assert.strictEqual(repoDisplayName(undefined), "—");
  });

  test("returns last two segments even for bare domain-only URLs", () => {
    // "https://github.com" splits to ["https:","","github.com"] — last two are ""/"github.com"
    const result = repoDisplayName("https://github.com");
    assert.strictEqual(result, "/github.com");
  });
});
