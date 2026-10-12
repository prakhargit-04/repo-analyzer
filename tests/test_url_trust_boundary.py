"""Ensure every API route accepting a repository URL applies the strict URL validator."""
from __future__ import annotations
import pytest

from pipeline.api.app import app
import pipeline.api.routes as routes_module
from test_v0246_failure_states import REPO_URL, env  # noqa: F401

INVALID_URLS = [
    "/tmp/repo", "file:///tmp/repo", "http://github.com/a/b", "git://github.com/a/b",
    "git@github.com:a/b.git", "https://user@github.com/a/b", "https://github.com@evil.com/a/b",
    "https://evil.com/a/b", "https://github.com.evil.com/a/b", "https://gіthub.com/a/b",
    "https://github.com:443/a/b", "https://github.com/a/b#frag", "https://github.com/a/b/../../x",
    "https://github.com/" + "a" * 2100,
]


def _routes_accepting_repo_url() -> set[str]:
    """Routes whose public contract takes a repo URL, read from the OpenAPI schema.

    FastAPI wraps endpoints, so inspect.signature() on the endpoint is not a
    reliable way to see query/body parameters (it returned an empty set and made
    the guard test vacuous). The generated OpenAPI document is the actual contract.
    """
    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    found = set()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            has_repo_url = any(p.get("name") == "repo_url" for p in operation.get("parameters", []))
            for media in operation.get("requestBody", {}).get("content", {}).values():
                schema = media.get("schema", {})
                ref = schema.get("$ref", "")
                if ref.startswith("#/components/schemas/"):
                    schema = schemas.get(ref.rsplit("/", 1)[-1], {})
                has_repo_url = has_repo_url or "repo_url" in schema.get("properties", {})
            if has_repo_url:
                found.add(path)
    return found


def test_every_route_accepting_repo_url_is_covered_by_validation_guard():
    expected = {"/api/v1/analyses", "/api/v1/analyses/latest", "/api/v1/repositories/runs"}
    found = _routes_accepting_repo_url()
    assert found, "route discovery returned nothing; the guard test would be vacuous"
    assert found == expected, f"Repository URL route coverage changed: found={found}, expected={expected}"


@pytest.mark.parametrize("url", INVALID_URLS)
def test_invalid_urls_rejected_before_clone(url, env, monkeypatch):
    called = []
    monkeypatch.setattr(routes_module.clone, "clone_repository", lambda *a, **k: called.append("clone"))
    monkeypatch.setattr(routes_module.clone, "resolve_remote_sha", lambda *a, **k: called.append("resolve"))
    post = env["client"].post("/api/v1/analyses", json={"repo_url": url})
    assert post.status_code == 422
    latest = env["client"].get("/api/v1/analyses/latest", params={"repo_url": url})
    runs = env["client"].get("/api/v1/repositories/runs", params={"repo_url": url})
    assert latest.status_code == 422
    assert runs.status_code == 422
    assert called == []
