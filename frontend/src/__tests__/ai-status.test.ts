import test, { describe } from "node:test";
import assert from "node:assert/strict";
import { getAiBadgeState } from "../lib/ai-status-helper";

describe("getAiBadgeState helper", () => {
  test("handles test mode correctly", () => {
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

  test("handles real mode correctly", () => {
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
    assert.strictEqual(getAiBadgeState(null as any).badgeLabel, "AI Mode: Unknown");
    assert.strictEqual(getAiBadgeState(null as any).showDisclaimer, false);

    assert.strictEqual(getAiBadgeState(undefined as any).badgeLabel, "AI Mode: Unknown");
    assert.strictEqual(getAiBadgeState({ invalid: true } as any).badgeLabel, "AI Mode: Unknown");
  });
});

