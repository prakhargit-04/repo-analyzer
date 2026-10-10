/**
 * Pure helper functions for the S17 dashboard.
 * No React dependencies — all functions are individually testable with the Node.js test runner.
 */

/** Format a numeric score to one decimal place, or return "N/A" for null/undefined. */
export function formatScore(score: number | null | undefined): string {
  if (score == null) return "N/A";
  return score.toFixed(1);
}

/** Return a semantic tier for a score value so UI components can apply consistent colours. */
export function getScoreLevel(
  score: number | null | undefined
): "good" | "warning" | "poor" | "unknown" {
  if (score == null) return "unknown";
  if (score >= 80) return "good";
  if (score >= 60) return "warning";
  return "poor";
}

/**
 * Separate a flat entity array (as returned by the file-detail endpoint) into code entities
 * (functions, classes, methods, …) and finding entities (type === "finding").
 * The backend mixes both in the same array; the frontend separates them for display.
 */
export function separateEntities(entities: unknown[]): {
  codeEntities: unknown[];
  findingEntities: unknown[];
} {
  const codeEntities: unknown[] = [];
  const findingEntities: unknown[] = [];
  for (const e of entities) {
    if (
      e != null &&
      typeof e === "object" &&
      (e as Record<string, unknown>)["type"] === "finding"
    ) {
      findingEntities.push(e);
    } else {
      codeEntities.push(e);
    }
  }
  return { codeEntities, findingEntities };
}

/**
 * Determine a human-readable language label for a file.
 * Prefers the explicit `language` field; falls back to extension inference.
 */
export function getFileLanguage(
  filePath: string,
  language?: string | null
): string {
  if (language && language !== "unknown") return language;
  if (filePath.endsWith(".py")) return "python";
  if (filePath.endsWith(".java")) return "java";
  if (filePath.endsWith(".ts") || filePath.endsWith(".tsx")) return "typescript";
  if (filePath.endsWith(".js") || filePath.endsWith(".jsx")) return "javascript";
  return "unknown";
}

/**
 * Truncate a git SHA to `length` characters and append an ellipsis,
 * or return "—" for absent values.
 */
export function truncateSha(
  sha: string | null | undefined,
  length = 16
): string {
  if (!sha) return "—";
  return sha.length > length ? sha.slice(0, length) + "…" : sha;
}

/**
 * Return the final two path segments of a repository URL as a short display name,
 * e.g. "https://github.com/pytest-dev/iniconfig" → "pytest-dev/iniconfig".
 * Falls back to the full URL when parsing fails.
 */
export function repoDisplayName(url: string | null | undefined): string {
  if (!url) return "—";
  const parts = url.replace(/\.git$/, "").split("/");
  if (parts.length >= 2) return parts.slice(-2).join("/");
  return url;
}
