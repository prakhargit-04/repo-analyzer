import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  validateBackendPath,
  buildBackendRequest,
  responseHeaders,
} from "../lib/proxy.js";

describe("Frontend Backend Proxy", () => {
  describe("validateBackendPath matrix", () => {
    it("accepts valid api/v1 paths", () => {
      assert.equal(validateBackendPath(["api", "v1", "health"]), "api/v1/health");
      assert.equal(
        validateBackendPath(["api", "v1", "analyses", "123", "summary"]),
        "api/v1/analyses/123/summary"
      );
    });

    it("rejects paths without api/v1 prefix", () => {
      assert.equal(validateBackendPath(["v1", "health"]), null);
      assert.equal(validateBackendPath(["api", "v2", "health"]), null);
      assert.equal(validateBackendPath(["health"]), null);
    });

    it("rejects path traversal and dot segments", () => {
      assert.equal(validateBackendPath(["api", "v1", "..", "secret"]), null);
      assert.equal(validateBackendPath(["api", "v1", "."]), null);
      assert.equal(validateBackendPath(["api", "v1", ""]), null);
    });

    it("rejects encoded traversal and slashes", () => {
      assert.equal(validateBackendPath(["api", "v1", "%2e%2e"]), null);
      assert.equal(validateBackendPath(["api", "v1", "%2F"]), null);
      assert.equal(validateBackendPath(["api", "v1", "%5c"]), null);
      assert.equal(validateBackendPath(["api", "v1", "%252f"]), null);
      assert.equal(validateBackendPath(["api", "v1", "%252e%252e"]), null);
    });

    it("rejects raw slashes and backslashes in segments", () => {
      assert.equal(validateBackendPath(["api", "v1", "foo/bar"]), null);
      assert.equal(validateBackendPath(["api", "v1", "foo\\bar"]), null);
    });
  });

  describe("buildBackendRequest", () => {
    it("forwards only header allowlist and strips prohibited/hop-by-hop headers", () => {
      const incoming = new Request("http://localhost:3000/api/backend/api/v1/health", {
        method: "GET",
        headers: {
          accept: "application/json",
          "accept-language": "en-US",
          "content-type": "application/json",
          "user-agent": "test-agent",
          host: "malicious.com",
          origin: "http://malicious.com",
          cookie: "session=123",
          authorization: "Bearer secret",
          "x-api-key": "user-supplied-key",
          connection: "close",
          "content-length": "100",
        },
      });

      const req = buildBackendRequest(
        incoming,
        ["api", "v1", "health"],
        "http://localhost:8000"
      );

      assert.equal(req.headers.get("accept"), "application/json");
      assert.equal(req.headers.get("accept-language"), "en-US");
      assert.equal(req.headers.get("content-type"), "application/json");
      assert.equal(req.headers.get("user-agent"), "test-agent");

      assert.equal(req.headers.get("host"), null);
      assert.equal(req.headers.get("origin"), null);
      assert.equal(req.headers.get("cookie"), null);
      assert.equal(req.headers.get("authorization"), null);
      assert.equal(req.headers.get("x-api-key"), null);
      assert.equal(req.headers.get("connection"), null);
    });

    it("injects BACKEND_API_KEY into X-API-Key header when provided", () => {
      const incoming = new Request("http://localhost:3000/api/backend/api/v1/health");
      const req = buildBackendRequest(
        incoming,
        ["api", "v1", "health"],
        "http://localhost:8000",
        "secret-backend-key"
      );

      assert.equal(req.headers.get("X-API-Key"), "secret-backend-key");
    });

    it("populates X-Forwarded-For with first hop of incoming x-forwarded-for or client IP", () => {
      const incomingXff = new Request("http://localhost:3000/api/backend/api/v1/health", {
        headers: { "x-forwarded-for": "203.0.113.195, 70.41.3.18" },
      });
      const req1 = buildBackendRequest(
        incomingXff,
        ["api", "v1", "health"],
        "http://localhost:8000"
      );
      assert.equal(req1.headers.get("X-Forwarded-For"), "203.0.113.195");

      const incomingRealIp = new Request("http://localhost:3000/api/backend/api/v1/health", {
        headers: { "x-real-ip": "198.51.100.1" },
      });
      const req2 = buildBackendRequest(
        incomingRealIp,
        ["api", "v1", "health"],
        "http://localhost:8000"
      );
      assert.equal(req2.headers.get("X-Forwarded-For"), "198.51.100.1");
    });

    it("ensures GET has no body and POST forwards body", () => {
      const getReq = buildBackendRequest(
        new Request("http://localhost:3000/api/backend/api/v1/health", { method: "GET" }),
        ["api", "v1", "health"],
        "http://localhost:8000"
      );
      assert.equal(getReq.body, null);

      const postReq = buildBackendRequest(
        new Request("http://localhost:3000/api/backend/api/v1/analyses", {
          method: "POST",
          body: JSON.stringify({ repo_url: "https://github.com/foo/bar" }),
        }),
        ["api", "v1", "analyses"],
        "http://localhost:8000"
      );
      assert.notEqual(postReq.body, null);
    });
  });

  describe("responseHeaders", () => {
    it("forwards content-type, retry-after and enforces cache-control: no-store", () => {
      const upstream = new Headers({
        "content-type": "application/json",
        "retry-after": "60",
        "x-custom-backend-header": "secret",
        "set-cookie": "session=123",
      });

      const resH = responseHeaders(upstream);
      assert.equal(resH.get("content-type"), "application/json");
      assert.equal(resH.get("retry-after"), "60");
      assert.equal(resH.get("cache-control"), "no-store");
      assert.equal(resH.get("x-custom-backend-header"), null);
      assert.equal(resH.get("set-cookie"), null);
    });
  });
});
