export interface AiBadgeState {
  badgeLabel: string;
  badgeVariant: "test" | "real" | "error" | "unknown";
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
