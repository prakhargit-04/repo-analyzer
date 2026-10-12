/**
 * API error model + user-facing message formatting.
 *
 * The backend returns `detail` as a string for our own HTTPExceptions
 * (e.g. GitHub URL validation, 409 embedding mismatch, 429 rate limit) and as
 * an ARRAY of `{loc, msg, type}` objects for FastAPI/Pydantic validation
 * failures (422). Both must render as readable text, never raw JSON.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly retryAfterSeconds?: number;

  constructor(status: number, detail: string, retryAfterSeconds?: number) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

interface ValidationIssue {
  loc?: unknown;
  msg?: unknown;
}

/** Turn a FastAPI `detail` (string | validation-issue[] | object) into readable text. */
export function formatErrorDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        const issue = item as ValidationIssue;
        if (typeof issue?.msg !== "string") return null;
        const loc = Array.isArray(issue.loc)
          ? issue.loc.filter((p) => p !== "body" && p !== "query").join(".")
          : "";
        return loc ? `${loc}: ${issue.msg}` : issue.msg;
      })
      .filter((p): p is string => Boolean(p));
    if (parts.length > 0) return parts.join("; ");
  }
  if (detail && typeof detail === "object") {
    const msg = (detail as { message?: unknown }).message;
    if (typeof msg === "string") return msg;
  }
  return "The request could not be processed.";
}

export function parseRetryAfter(value: string | null | undefined): number | undefined {
  if (!value) return undefined;
  const seconds = Number.parseInt(value, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined;
}

/**
 * Message shown in panels (Assistant, Semantic Search). Status-specific
 * wording for the failures a user can act on; falls back to the error text.
 */
export function formatPanelErrorMessage(err: unknown): string {
  if (!err) return "An unexpected error occurred.";
  if (typeof err === "string") return err;
  if (err instanceof ApiError) {
    switch (err.status) {
      case 409:
        return `This analysis can't be searched with the current AI configuration. ${err.detail}`;
      case 422:
        return `Please check your input: ${err.detail}`;
      case 429: {
        const wait =
          err.retryAfterSeconds != null
            ? ` Try again in ${err.retryAfterSeconds} second${err.retryAfterSeconds === 1 ? "" : "s"}.`
            : " Please wait a moment and try again.";
        return `Too many requests.${wait}`;
      }
      case 503:
        return `The service is temporarily unavailable: ${err.detail}`;
      default:
        return err.detail || "Failed to process request.";
    }
  }
  const message = (err as { message?: unknown }).message;
  if (typeof message === "string" && message.trim()) return message;
  return "Failed to process request.";
}
