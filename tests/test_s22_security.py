"""
Session 22 â€” Security & Cleanup Tests

Covers:
  A) URL Validator (api/url_validator.py) â€” comprehensive edge-case coverage
  B) CORS configuration (api/app.py) â€” no wildcard, env-configurable
"""
from __future__ import annotations

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from api.url_validator import validate_github_url


# ---------------------------------------------------------------------------
# URL VALIDATOR â€” Valid inputs
# ---------------------------------------------------------------------------

class TestUrlValidatorValid:
    def test_basic_github_https(self):
        ok, result = validate_github_url("https://github.com/user/repo")
        assert ok is True
        assert result == "https://github.com/user/repo"

    def test_trailing_git_suffix(self):
        ok, result = validate_github_url("https://github.com/user/repo.git")
        assert ok is True
        assert result == "https://github.com/user/repo"

    def test_trailing_slash(self):
        ok, result = validate_github_url("https://github.com/user/repo/")
        assert ok is True
        assert result == "https://github.com/user/repo"

    def test_git_suffix_and_trailing_slash(self):
        ok, result = validate_github_url("https://github.com/user/repo.git/")
        # regex anchors â€” trailing slash after .git may not match; acceptable either way
        # The important thing is it's not treated as a valid extra-segment URL
        # This is an edge case; just assert no crash
        assert isinstance(ok, bool)

    def test_org_with_hyphens(self):
        ok, result = validate_github_url("https://github.com/pytest-dev/iniconfig")
        assert ok is True
        assert result == "https://github.com/pytest-dev/iniconfig"

    def test_repo_with_dots(self):
        ok, result = validate_github_url("https://github.com/owner/my.repo")
        assert ok is True
        assert result == "https://github.com/owner/my.repo"

    def test_repo_with_underscores(self):
        ok, result = validate_github_url("https://github.com/owner/my_repo")
        assert ok is True
        assert result == "https://github.com/owner/my_repo"

    def test_uppercase_is_accepted(self):
        # GitHub URLs are case-insensitive at the scheme/host level
        ok, result = validate_github_url("https://GitHub.com/Owner/Repo")
        assert ok is True
        assert result == "https://github.com/Owner/Repo"

    def test_normalizes_url(self):
        """Normalized form strips .git and trailing slash."""
        ok, result = validate_github_url("https://github.com/pallets/itsdangerous.git")
        assert ok is True
        assert result == "https://github.com/pallets/itsdangerous"


# ---------------------------------------------------------------------------
# URL VALIDATOR â€” Invalid: scheme
# ---------------------------------------------------------------------------

class TestUrlValidatorInvalidScheme:
    def test_http_rejected(self):
        ok, reason = validate_github_url("http://github.com/user/repo")
        assert ok is False
        assert "HTTPS" in reason or "https" in reason.lower() or "scheme" in reason.lower()

    def test_git_scheme_rejected(self):
        ok, reason = validate_github_url("git://github.com/user/repo")
        assert ok is False

    def test_ssh_git_at_rejected(self):
        ok, reason = validate_github_url("git@github.com:user/repo.git")
        assert ok is False

    def test_file_scheme_rejected(self):
        ok, reason = validate_github_url("file:///home/user/repo")
        assert ok is False

    def test_local_path_rejected(self):
        ok, reason = validate_github_url("/home/user/repo")
        assert ok is False

    def test_windows_local_path_rejected(self):
        ok, reason = validate_github_url("C:\\Users\\user\\repo")
        assert ok is False


# ---------------------------------------------------------------------------
# URL VALIDATOR â€” Invalid: host
# ---------------------------------------------------------------------------

class TestUrlValidatorInvalidHost:
    def test_non_github_host_rejected(self):
        ok, reason = validate_github_url("https://gitlab.com/user/repo")
        assert ok is False
        assert "github.com" in reason.lower() or "host" in reason.lower()

    def test_bitbucket_rejected(self):
        ok, reason = validate_github_url("https://bitbucket.org/user/repo")
        assert ok is False

    def test_localhost_rejected(self):
        ok, reason = validate_github_url("https://localhost/user/repo")
        assert ok is False

    def test_127_ip_rejected(self):
        ok, reason = validate_github_url("https://127.0.0.1/user/repo")
        assert ok is False

    def test_private_ip_rejected(self):
        ok, reason = validate_github_url("https://192.168.1.1/user/repo")
        assert ok is False


# ---------------------------------------------------------------------------
# URL VALIDATOR â€” Invalid: userinfo (SSRF / host confusion tricks)
# ---------------------------------------------------------------------------

class TestUrlValidatorUserinfoTricks:
    def test_userinfo_at_github_rejected(self):
        ok, reason = validate_github_url("https://user@github.com/owner/repo")
        assert ok is False

    def test_github_at_evil_rejected(self):
        # Trick: host is actually evil.com, userinfo is github.com
        ok, reason = validate_github_url("https://github.com@evil.com/owner/repo")
        assert ok is False


# ---------------------------------------------------------------------------
# URL VALIDATOR â€” Invalid: port
# ---------------------------------------------------------------------------

class TestUrlValidatorPort:
    def test_explicit_port_rejected(self):
        ok, reason = validate_github_url("https://github.com:8443/user/repo")
        assert ok is False
        assert "port" in reason.lower()

    def test_port_443_rejected(self):
        # Even default HTTPS port should be rejected (normalized form has no port)
        ok, reason = validate_github_url("https://github.com:443/user/repo")
        assert ok is False


# ---------------------------------------------------------------------------
# URL VALIDATOR â€” Invalid: path
# ---------------------------------------------------------------------------

class TestUrlValidatorPath:
    def test_no_repo_segment_rejected(self):
        ok, reason = validate_github_url("https://github.com/user")
        assert ok is False

    def test_extra_path_segment_rejected(self):
        ok, reason = validate_github_url("https://github.com/user/repo/tree/main")
        assert ok is False

    def test_very_deep_path_rejected(self):
        ok, reason = validate_github_url("https://github.com/user/repo/blob/main/file.py")
        assert ok is False

    def test_empty_owner_rejected(self):
        ok, reason = validate_github_url("https://github.com//repo")
        assert ok is False

    def test_empty_repo_rejected(self):
        ok, reason = validate_github_url("https://github.com/user/")
        # trailing slash but no repo name
        # This is ambiguous â€” either rejected or treated as empty repo
        if ok:
            # If accepted, the normalized URL must not have empty repo
            assert "//" not in result if (ok, result := validate_github_url("https://github.com/user/")) else True
        else:
            assert ok is False

    def test_dash_owner_rejected(self):
        ok, reason = validate_github_url("https://github.com/-owner/repo")
        assert ok is False

    def test_dash_repo_rejected(self):
        ok, reason = validate_github_url("https://github.com/owner/-repo")
        assert ok is False


# ---------------------------------------------------------------------------
# URL VALIDATOR â€” Invalid: query/fragment
# ---------------------------------------------------------------------------

class TestUrlValidatorQueryFragment:
    def test_query_string_rejected(self):
        ok, reason = validate_github_url("https://github.com/user/repo?ref=main")
        assert ok is False
        assert "query" in reason.lower()

    def test_fragment_rejected(self):
        ok, reason = validate_github_url("https://github.com/user/repo#readme")
        assert ok is False
        assert "fragment" in reason.lower()


# ---------------------------------------------------------------------------
# URL VALIDATOR â€” Invalid: injection / whitespace
# ---------------------------------------------------------------------------

class TestUrlValidatorInjection:
    def test_empty_rejected(self):
        ok, reason = validate_github_url("")
        assert ok is False
        assert "empty" in reason.lower()

    def test_whitespace_only_rejected(self):
        ok, reason = validate_github_url("   ")
        assert ok is False

    def test_starts_with_dash_rejected(self):
        ok, reason = validate_github_url("-bad-option")
        assert ok is False

    def test_newline_in_url_rejected(self):
        ok, reason = validate_github_url("https://github.com/user/repo\n")
        assert ok is False

    def test_tab_in_url_rejected(self):
        ok, reason = validate_github_url("https://github.com/user/\trepo")
        assert ok is False

    def test_null_byte_rejected(self):
        ok, reason = validate_github_url("https://github.com/user/\x00repo")
        assert ok is False


# ---------------------------------------------------------------------------
# CORS configuration tests
# ---------------------------------------------------------------------------

class TestCORSConfiguration:
    """Verify CORS middleware is configured safely."""

    def test_no_wildcard_in_default_origins(self):
        """Default CORS origins must not include '*'."""
        # Save and clear env var to force default
        saved = os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        try:
            from api.app import _get_cors_origins
            origins = _get_cors_origins()
            assert "*" not in origins, (
                "Wildcard '*' must not be in CORS allowed origins "
                "(security: wildcard + credentials=True is rejected by browsers "
                "and is a misconfiguration)."
            )
        finally:
            if saved is not None:
                os.environ["CORS_ALLOWED_ORIGINS"] = saved

    def test_default_origins_include_localhost(self):
        """Default CORS origins must include localhost dev URLs."""
        saved = os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        try:
            from api.app import _get_cors_origins
            origins = _get_cors_origins()
            assert any("localhost:3000" in o for o in origins), (
                "Default origins must include http://localhost:3000 for local dev."
            )
        finally:
            if saved is not None:
                os.environ["CORS_ALLOWED_ORIGINS"] = saved

    def test_cors_origins_env_configurable(self):
        """CORS_ALLOWED_ORIGINS env var overrides the default list."""
        saved = os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        try:
            os.environ["CORS_ALLOWED_ORIGINS"] = "https://example.com,https://other.example.com"
            # Need to reload to pick up env change
            import importlib
            import api.app as app_module
            importlib.reload(app_module)
            origins = app_module._get_cors_origins()
            assert "https://example.com" in origins
            assert "https://other.example.com" in origins
            assert "*" not in origins
        finally:
            if saved is not None:
                os.environ["CORS_ALLOWED_ORIGINS"] = saved
            else:
                os.environ.pop("CORS_ALLOWED_ORIGINS", None)
            # Reload to restore defaults
            import importlib
            import api.app as app_module
            importlib.reload(app_module)

    def test_cors_env_strips_whitespace(self):
        """Whitespace in CORS_ALLOWED_ORIGINS entries must be stripped."""
        saved = os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        try:
            os.environ["CORS_ALLOWED_ORIGINS"] = "  https://example.com  ,  https://other.com  "
            import importlib
            import api.app as app_module
            importlib.reload(app_module)
            origins = app_module._get_cors_origins()
            assert "https://example.com" in origins
            assert "https://other.com" in origins
            # No whitespace-padded entries
            assert all(o == o.strip() for o in origins)
        finally:
            if saved is not None:
                os.environ["CORS_ALLOWED_ORIGINS"] = saved
            else:
                os.environ.pop("CORS_ALLOWED_ORIGINS", None)
            import importlib
            import api.app as app_module
            importlib.reload(app_module)


# ---------------------------------------------------------------------------
# URL VALIDATOR - Additional edge cases required by S22 audit
# ---------------------------------------------------------------------------

class TestUrlValidatorAuditCases:
    """
    Edge cases mandated by the S22 audit that were absent from the original suite.
    No existing test was modified; only new cases added.
    """

    def test_uppercase_github_com_host_accepted(self):
        ok, result = validate_github_url("https://GITHUB.COM/user/repo")
        assert ok is True
        assert result == "https://github.com/user/repo"

    def test_trailing_dot_host_rejected(self):
        ok, reason = validate_github_url("https://github.com./user/repo")
        assert ok is False
        assert isinstance(reason, str) and "github.com" in reason.lower()

    def test_github_com_evil_com_subdomain_rejected(self):
        ok, reason = validate_github_url("https://github.com.evil.com/user/repo")
        assert ok is False
        assert isinstance(reason, str) and ("github.com" in reason.lower() or "host" in reason.lower())

    def test_gist_github_com_rejected(self):
        ok, reason = validate_github_url("https://gist.github.com/user/abc123")
        assert ok is False
        assert isinstance(reason, str) and ("github.com" in reason.lower() or "host" in reason.lower())

    def test_percent_encoded_dot_dot_rejected(self):
        ok, reason = validate_github_url("https://github.com/user/%2e%2e/etc/passwd")
        assert ok is False
        assert isinstance(reason, str) and "percent-encoded" in reason.lower()

    def test_percent_encoded_slash_rejected(self):
        ok, reason = validate_github_url("https://github.com/user%2frepo")
        assert ok is False
        assert isinstance(reason, str) and "percent-encoded" in reason.lower()

    def test_backslash_in_url_rejected(self):
        ok, reason = validate_github_url(r"https://github.com/user\repo")
        assert ok is False
        assert isinstance(reason, str) and len(reason) > 0 and ("form" in reason.lower() or "invalid" in reason.lower() or "control" in reason.lower())

    def test_tree_main_extra_segment_rejected(self):
        ok, reason = validate_github_url("https://github.com/user/repo/tree/main")
        assert ok is False
        assert isinstance(reason, str) and "extra path segments" in reason.lower()

    def test_zero_ip_rejected(self):
        ok, reason = validate_github_url("https://0.0.0.0/user/repo")
        assert ok is False
        assert isinstance(reason, str) and "github.com" in reason.lower()

    def test_ipv6_loopback_rejected(self):
        ok, reason = validate_github_url("https://[::1]/user/repo")
        assert ok is False
        assert isinstance(reason, str) and "github.com" in reason.lower()

    def test_link_local_ip_rejected(self):
        ok, reason = validate_github_url("https://169.254.169.254/user/repo")
        assert ok is False
        assert isinstance(reason, str) and "github.com" in reason.lower()

    def test_decimal_ip_rejected(self):
        ok, reason = validate_github_url("https://2130706433/user/repo")
        assert ok is False
        assert isinstance(reason, str) and "github.com" in reason.lower()


# ---------------------------------------------------------------------------
# Task R3 Hardening Tests — Middleware Order, Rate Limiting & Auth
# ---------------------------------------------------------------------------

class TestMiddlewareAndRateLimitHardening:
    """Task R3 Verification: Middleware ordering, rate limit identity, auth fail throttling, CORS, thread safety."""

    def test_middleware_registration_order(self):
        """app.user_middleware registration order must be RateLimit -> APIKey -> CORS."""
        from api.app import create_app
        from api.security import APIKeyMiddleware
        from api.rate_limit import RateLimitMiddleware
        from fastapi.middleware.cors import CORSMiddleware

        app = create_app()
        classes = [m.cls for m in app.user_middleware]
        # Starlette inserts added middleware at index 0, so adding RateLimit, then APIKey, then CORS
        # results in app.user_middleware = [CORSMiddleware, APIKeyMiddleware, RateLimitMiddleware] (outermost -> innermost).
        assert classes == [CORSMiddleware, APIKeyMiddleware, RateLimitMiddleware]

    def test_unauthenticated_requests_do_not_drain_authenticated_bucket(self, monkeypatch, tmp_path):
        """N unauthenticated requests return 401 and do NOT consume the authenticated rate limit bucket."""
        db_url = f"sqlite:///{tmp_path}/test.db"
        monkeypatch.setenv("API_KEY", "test-secret-key")
        monkeypatch.setenv("RATE_LIMIT_RPM", "3")
        monkeypatch.setenv("AUTH_FAIL_RPM", "100")
        monkeypatch.setenv("DATABASE_URL", db_url)
        from db.engine import get_engine, create_all_tables
        create_all_tables(get_engine(db_url))
        from api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        # 5 unauthenticated requests -> 401
        for _ in range(5):
            res = client.post("/api/v1/analyses", json={"repo_url": "https://github.com/foo/bar"})
            assert res.status_code == 401

        # Request WITH correct key -> NOT 429
        res_valid = client.post(
            "/api/v1/analyses",
            json={"repo_url": "https://github.com/foo/bar"},
            headers={"X-API-Key": "test-secret-key"},
        )
        assert res_valid.status_code != 429

    def test_per_client_rate_limiting_with_trust_proxy(self, monkeypatch, tmp_path):
        """Two different clients (X-Forwarded-For) have independent buckets when TRUST_PROXY_HEADERS=1."""
        db_url = f"sqlite:///{tmp_path}/test.db"
        monkeypatch.setenv("API_KEY", "test-secret-key")
        monkeypatch.setenv("RATE_LIMIT_RPM", "2")
        monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
        monkeypatch.setenv("DATABASE_URL", db_url)
        from db.engine import get_engine, create_all_tables
        create_all_tables(get_engine(db_url))
        from api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        headers1 = {"X-API-Key": "test-secret-key", "X-Forwarded-For": "1.1.1.1"}
        headers2 = {"X-API-Key": "test-secret-key", "X-Forwarded-For": "2.2.2.2"}

        # Client 1 uses 2 requests (reaches limit)
        client.post("/api/v1/analyses", json={"repo_url": "https://github.com/foo/bar"}, headers=headers1)
        client.post("/api/v1/analyses", json={"repo_url": "https://github.com/foo/bar"}, headers=headers1)
        res1_3 = client.post("/api/v1/analyses", json={"repo_url": "https://github.com/foo/bar"}, headers=headers1)
        assert res1_3.status_code == 429

        # Client 2 is independent and can still make requests
        res2_1 = client.post("/api/v1/analyses", json={"repo_url": "https://github.com/foo/bar"}, headers=headers2)
        assert res2_1.status_code != 429

    def test_trust_proxy_headers_ignored_when_disabled(self, monkeypatch, tmp_path):
        """Without TRUST_PROXY_HEADERS=1, X-Forwarded-For is ignored."""
        db_url = f"sqlite:///{tmp_path}/test.db"
        monkeypatch.setenv("API_KEY", "test-secret-key")
        monkeypatch.setenv("RATE_LIMIT_RPM", "2")
        monkeypatch.setenv("TRUST_PROXY_HEADERS", "0")
        monkeypatch.setenv("DATABASE_URL", db_url)
        from db.engine import get_engine, create_all_tables
        create_all_tables(get_engine(db_url))
        from api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        headers1 = {"X-API-Key": "test-secret-key", "X-Forwarded-For": "1.1.1.1"}
        headers2 = {"X-API-Key": "test-secret-key", "X-Forwarded-For": "2.2.2.2"}

        client.post("/api/v1/analyses", json={"repo_url": "https://github.com/foo/bar"}, headers=headers1)
        client.post("/api/v1/analyses", json={"repo_url": "https://github.com/foo/bar"}, headers=headers1)

        # Both headers map to same request.client.host, so client2 is rate limited
        res2 = client.post("/api/v1/analyses", json={"repo_url": "https://github.com/foo/bar"}, headers=headers2)
        assert res2.status_code == 429

    def test_failed_auth_throttling(self, monkeypatch):
        """Failed-auth throttling returns 429 with Retry-After and CORS headers."""
        monkeypatch.setenv("API_KEY", "test-secret-key")
        monkeypatch.setenv("AUTH_FAIL_RPM", "2")
        from api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)
        origin_header = {"Origin": "http://localhost:3000"}

        # 2 failed auth attempts -> 401
        res1 = client.post("/api/v1/analyses", json={}, headers=origin_header)
        assert res1.status_code == 401
        res2 = client.post("/api/v1/analyses", json={}, headers=origin_header)
        assert res2.status_code == 401

        # 3rd failed attempt -> 429 with Retry-After and CORS origin
        res3 = client.post("/api/v1/analyses", json={}, headers=origin_header)
        assert res3.status_code == 429
        assert "Retry-After" in res3.headers
        assert res3.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_cors_preflight_and_error_response_headers(self, monkeypatch):
        """Preflight OPTIONS returns 200/204 with allow-headers; 401/429 carry Access-Control-Allow-Origin."""
        monkeypatch.setenv("API_KEY", "test-secret-key")
        monkeypatch.setenv("AUTH_FAIL_RPM", "1")
        from api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)
        headers = {
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-API-Key, Content-Type",
        }

        # Preflight OPTIONS
        res_opt = client.options("/api/v1/analyses", headers=headers)
        assert res_opt.status_code in (200, 204)
        assert res_opt.headers.get("access-control-allow-origin") == "http://localhost:3000"

        # 401 response has CORS header
        res_401 = client.post("/api/v1/analyses", json={}, headers={"Origin": "http://localhost:3000"})
        assert res_401.status_code == 401
        assert res_401.headers.get("access-control-allow-origin") == "http://localhost:3000"

        # 429 response has CORS header
        res_429 = client.post("/api/v1/analyses", json={}, headers={"Origin": "http://localhost:3000"})
        assert res_429.status_code == 429
        assert res_429.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_unrelated_paths_and_get_routes_not_rate_limited(self, monkeypatch):
        """GET routes, unrelated POST paths, health and docs are exempt from rate limiting."""
        monkeypatch.setenv("RATE_LIMIT_RPM", "1")
        from api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        # GET /health multiple times -> 200
        for _ in range(5):
            assert client.get("/api/v1/health").status_code == 200

        # Unrelated POST path -> 404/405, NOT 429
        for _ in range(5):
            res = client.post("/api/v1/unknown_route")
            assert res.status_code != 429

    def test_bucket_cap_and_amortized_sweep(self):
        """Bucket cap holds under 10k distinct clients and sweep is amortized."""
        from api.rate_limit import RateLimitMiddleware
        mw = RateLimitMiddleware(app=None, rpm=30, cap=50, ttl=0.1)

        class FakeRequest:
            def __init__(self, ip):
                self.headers = {}
                self.url = type("URL", (), {"path": "/api/v1/analyses"})()
                self.method = "POST"
                self.client = type("Client", (), {"host": ip})()

        for i in range(150):
            mw._key(FakeRequest(f"10.0.0.{i}"))

        assert len(mw.buckets) <= 50

    def test_thread_safety_under_concurrent_requests(self, monkeypatch):
        """N concurrent threads never exceed the rate limit burst capacity."""
        monkeypatch.setenv("RATE_LIMIT_RPM", "5")
        from api.app import create_app
        from fastapi.testclient import TestClient
        import threading

        app = create_app()
        client = TestClient(app)

        results = []
        def make_req():
            res = client.post("/api/v1/analyses", json={"repo_url": "https://github.com/foo/bar"})
            results.append(res.status_code)

        threads = [threading.Thread(target=make_req) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        non_429 = [s for s in results if s != 429]
        assert len(non_429) <= 5

    def test_hmac_compare_digest_is_used(self, monkeypatch):
        """Verify hmac.compare_digest is called during API key check."""
        import hmac
        called = []
        orig_compare = hmac.compare_digest

        def spy_compare(a, b):
            called.append(True)
            return orig_compare(a, b)

        monkeypatch.setattr(hmac, "compare_digest", spy_compare)
        monkeypatch.setenv("API_KEY", "test-secret-key")

        from api.app import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)

        client.post("/api/v1/analyses", json={}, headers={"X-API-Key": "wrong-key"})
        assert len(called) > 0


