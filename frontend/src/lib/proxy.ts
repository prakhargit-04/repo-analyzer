export type StreamingInit = RequestInit & { duplex?: "half" };

const ALLOWED_REQUEST_HEADERS = new Set([
  "accept",
  "accept-language",
  "content-type",
  "user-agent",
]);

export function validateBackendPath(parts: string[]): string | null {
  if (!parts || parts.length < 2 || parts[0] !== "api" || parts[1] !== "v1") {
    return null;
  }

  for (const part of parts) {
    if (!part || part === "." || part === "..") {
      return null;
    }
    if (
      /%2e/i.test(part) ||
      /%2f/i.test(part) ||
      /%5c/i.test(part) ||
      part.includes("/") ||
      part.includes("\\")
    ) {
      return null;
    }

    try {
      const decoded = decodeURIComponent(part);
      if (
        decoded === "." ||
        decoded === ".." ||
        decoded.includes("/") ||
        decoded.includes("\\") ||
        decoded.includes("\0")
      ) {
        return null;
      }
      if (/%25/i.test(part)) {
        return null;
      }
    } catch {
      return null;
    }
  }

  return parts.join("/");
}

export function buildBackendRequest(
  request: Request,
  parts: string[],
  backendUrl: string,
  apiKey?: string,
  clientIp?: string
): Request {
  const path = validateBackendPath(parts);
  if (!path) throw new Error("invalid backend path");

  const targetUrl = new URL(request.url);
  const target = new URL(path + targetUrl.search, backendUrl.replace(/\/$/, "") + "/");

  const headers = new Headers();
  for (const [name, value] of request.headers.entries()) {
    const lower = name.toLowerCase();
    if (ALLOWED_REQUEST_HEADERS.has(lower)) {
      headers.set(lower, value);
    }
  }

  if (apiKey) {
    headers.set("X-API-Key", apiKey);
  }

  const incomingXff = request.headers.get("x-forwarded-for");
  let resolvedIp = clientIp || "127.0.0.1";
  if (incomingXff && incomingXff.trim()) {
    resolvedIp = incomingXff.split(",")[0].trim();
  } else {
    const realIp = request.headers.get("x-real-ip");
    if (realIp && realIp.trim()) {
      resolvedIp = realIp.trim();
    }
  }
  headers.set("X-Forwarded-For", resolvedIp);

  const method = request.method.toUpperCase();
  const init: StreamingInit = {
    method,
    headers,
    body: method === "GET" || method === "HEAD" ? undefined : request.body,
    duplex: "half",
  };

  return new Request(target, init);
}

export function responseHeaders(upstream: Headers): Headers {
  const headers = new Headers();
  const contentType = upstream.get("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }
  const retryAfter = upstream.get("retry-after");
  if (retryAfter) {
    headers.set("retry-after", retryAfter);
  }
  headers.set("cache-control", "no-store");
  return headers;
}
