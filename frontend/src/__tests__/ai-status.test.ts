import { describe, it, expect } from "vitest";
import { getAiBadgeState } from "../lib/ai-status-helper";

describe("getAiBadgeState helper", () => {
  it("handles test mode correctly", () => {
    const state = getAiBadgeState({
      mode: "test",
      configured: true,
      embedding: { provider: "test", model: "sha256", dimension: 64 },
      llm: { provider: "test", model: "deterministic" },
    });
    expect(state.badgeLabel).toBe("AI Mode: Test");
    expect(state.badgeVariant).toBe("test");
    expect(state.showDisclaimer).toBe(true);
  });

  it("handles real mode correctly", () => {
    const state = getAiBadgeState({
      mode: "real",
      configured: true,
      embedding: { provider: "sentence_transformers", model: "all-MiniLM-L6-v2", dimension: 384 },
      llm: { provider: "openai", model: "gpt-4o-mini" },
    });
    expect(state.badgeLabel).toBe("AI Mode: Real (openai/gpt-4o-mini)");
    expect(state.badgeVariant).toBe("real");
    expect(state.showDisclaimer).toBe(false);
  });

  it("handles error mode correctly", () => {
    const state = getAiBadgeState({
      mode: "error",
      configured: false,
      message: "OPENAI_API_KEY is missing",
    });
    expect(state.badgeLabel).toBe("AI Mode: Misconfigured");
    expect(state.badgeVariant).toBe("error");
    expect(state.showDisclaimer).toBe(false);
  });

  it("handles unknown/null/malformed status responses safely", () => {
    expect(getAiBadgeState(null).badgeLabel).toBe("AI Mode: Unknown");
    expect(getAiBadgeState(null).showDisclaimer).toBe(false);

    expect(getAiBadgeState(undefined).badgeLabel).toBe("AI Mode: Unknown");
    expect(getAiBadgeState({ invalid: true }).badgeLabel).toBe("AI Mode: Unknown");
  });
});
