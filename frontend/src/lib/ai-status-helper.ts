export interface AiBadgeState {
  badgeLabel: string;
  badgeVariant: "test" | "real" | "mixed" | "error" | "unknown";
  showDisclaimer: boolean;
}

export function getAiBadgeState(
  statusData: unknown
): AiBadgeState {
  if (
    !statusData ||
    typeof statusData !== "object" ||
    !("mode" in statusData)
  ) {
    return {
      badgeLabel: "AI Mode: Unknown",
      badgeVariant: "unknown",
      showDisclaimer: false,
    };
  }

  const data = statusData as {
    mode?: string;
    llm?: { provider?: string; model?: string };
    embedding?: { provider?: string; model?: string };
  };

  if (data.mode === "test") {
    return {
      badgeLabel: "AI Mode: Test",
      badgeVariant: "test",
      showDisclaimer: true,
    };
  }

  if (data.mode === "real") {
    const prov = data.llm?.provider || data.embedding?.provider || "real";
    const model = data.llm?.model || data.embedding?.model || "active";
    return {
      badgeLabel: `AI Mode: Real (${prov}/${model})`,
      badgeVariant: "real",
      showDisclaimer: false,
    };
  }

  if (data.mode === "mixed") {
    const embProv = data.embedding?.provider || "test";
    const llmProv = data.llm?.provider || "test";
    // Disclaimer is visible whenever embeddings are test (non-semantic)
    const _TEST_EMBEDDING_IDS = new Set(["test", "test-deterministic"]);
    const showDisclaimer = _TEST_EMBEDDING_IDS.has(embProv);
    return {
      badgeLabel: `AI Mode: Mixed (embeddings: ${embProv}, LLM: ${llmProv})`,
      badgeVariant: "mixed",
      showDisclaimer,
    };
  }

  if (data.mode === "error") {
    return {
      badgeLabel: "AI Mode: Misconfigured",
      badgeVariant: "error",
      showDisclaimer: false,
    };
  }

  return {
    badgeLabel: "AI Mode: Unknown",
    badgeVariant: "unknown",
    showDisclaimer: false,
  };
}
