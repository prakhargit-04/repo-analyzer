import test, { describe } from "node:test";
import assert from "node:assert/strict";
import { getAiBadgeState } from "../lib/ai-status-helper";

describe("getAiBadgeState helper", () => {
  test("handles test mode correctly (both test)", () => {
    const state = getAiBadgeState({
      mode: "test",
      configured: true,
      embedding: { provider: "test", model: "sha256", dimension: 64 },
      llm: { provider: "test", model: "deterministic" },
    });
    assert.strictEqual(state.badgeLabel, "AI Mode: Test");
    assert.strictEqual(state.badgeVariant, "test");
    assert.strictEqual(state.showDisclaimer, true);
  });

  test("handles real mode correctly (both real)", () => {
    const state = getAiBadgeState({
      mode: "real",
      configured: true,
      embedding: { provider: "sentence_transformers", model: "all-MiniLM-L6-v2", dimension: 384 },
      llm: { provider: "openai", model: "gpt-4o-mini" },
    });
    assert.strictEqual(state.badgeLabel, "AI Mode: Real (openai/gpt-4o-mini)");
    assert.strictEqual(state.badgeVariant, "real");
    assert.strictEqual(state.showDisclaimer, false);
  });

  test("handles mixed mode: test embeddings + real LLM", () => {
    const state = getAiBadgeState({
      mode: "mixed",
      configured: true,
      embedding: { provider: "test", model: "sha256", dimension: 64 },
      llm: { provider: "openai", model: "gpt-4o-mini" },
    });
    assert.strictEqual(state.badgeLabel, "AI Mode: Mixed (embeddings: test, LLM: openai)");
    assert.strictEqual(state.badgeVariant, "mixed");
    assert.strictEqual(state.showDisclaimer, true, "disclaimer must show when embeddings are test");
  });

  test("handles mixed mode: real embeddings + test LLM", () => {
    const state = getAiBadgeState({
      mode: "mixed",
      configured: true,
      embedding: { provider: "sentence_transformers", model: "all-MiniLM-L6-v2", dimension: 384 },
      llm: { provider: "test", model: "deterministic" },
    });
    assert.strictEqual(state.badgeLabel, "AI Mode: Mixed (embeddings: sentence_transformers, LLM: test)");
    assert.strictEqual(state.badgeVariant, "mixed");
    assert.strictEqual(state.showDisclaimer, false, "disclaimer not shown when embeddings are real");
  });

  test("handles error mode correctly", () => {
    const state = getAiBadgeState({
      mode: "error",
      configured: false,
      message: "OPENAI_API_KEY is missing",
    });
    assert.strictEqual(state.badgeLabel, "AI Mode: Misconfigured");
    assert.strictEqual(state.badgeVariant, "error");
    assert.strictEqual(state.showDisclaimer, false);
  });

  test("handles unknown/null/malformed status responses safely", () => {
    assert.strictEqual(getAiBadgeState(null as unknown as Parameters<typeof getAiBadgeState>[0]).badgeLabel, "AI Mode: Unknown");
    assert.strictEqual(getAiBadgeState(null as unknown as Parameters<typeof getAiBadgeState>[0]).showDisclaimer, false);

    assert.strictEqual(getAiBadgeState(undefined as unknown as Parameters<typeof getAiBadgeState>[0]).badgeLabel, "AI Mode: Unknown");
    assert.strictEqual(getAiBadgeState({ invalid: true } as unknown as Parameters<typeof getAiBadgeState>[0]).badgeLabel, "AI Mode: Unknown");
  });
});
