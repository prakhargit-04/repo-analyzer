"""Dependency-light unit tests for the cache configuration fingerprint."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
import util  # noqa: E402
import chunker  # noqa: E402
import embeddings  # noqa: E402


def test_fingerprint_is_deterministic_and_semgrep_path_independent(tmp_path, monkeypatch):
    one, two = tmp_path / "one.yml", tmp_path / "two.yml"
    one.write_text("rules: []\n")
    two.write_text("rules: []\n")
    monkeypatch.setenv("SEMGREP_CONFIG", str(one))
    expected = util.analysis_config_fingerprint()
    assert util.analysis_config_fingerprint() == expected
    monkeypatch.setenv("SEMGREP_CONFIG", str(two))
    assert util.analysis_config_fingerprint() == expected


def test_fingerprint_tracks_rules_content_and_auto_default(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yml"
    rules.write_text("rules: []\n")
    monkeypatch.setenv("SEMGREP_CONFIG", str(rules))
    before = util.analysis_config_fingerprint()
    rules.write_text("rules:\n  - id: changed\n")
    assert util.analysis_config_fingerprint() != before
    monkeypatch.delenv("SEMGREP_CONFIG", raising=False)
    assert util.semgrep_ruleset_identity() == "auto"


def test_fingerprint_tracks_every_embedding_identity_component_and_versions(monkeypatch):
    baseline = util.analysis_config_fingerprint()
    identities = [
        ("another-provider", "test-deterministic", "1.0"),
        ("test-deterministic", "another-model", "1.0"),
        ("test-deterministic", "test-deterministic", "another-version"),
    ]
    for identity in identities:
        with monkeypatch.context() as m:
            m.setattr(embeddings, "embedding_cache_identity", lambda identity=identity: identity)
            assert util.analysis_config_fingerprint() != baseline
    with monkeypatch.context() as m:
        m.setattr(util, "CACHE_SCHEMA_VERSION", util.CACHE_SCHEMA_VERSION + "-next")
        assert util.analysis_config_fingerprint() != baseline
    with monkeypatch.context() as m:
        m.setattr(util, "ANALYZER_VERSION", util.ANALYZER_VERSION + "-next")
        assert util.analysis_config_fingerprint() != baseline
    with monkeypatch.context() as m:
        m.setattr(chunker, "SOURCE_CHUNKER_VERSION", "different-chunker")
        assert util.analysis_config_fingerprint() != baseline
    with monkeypatch.context() as m:
        m.setattr(embeddings, "EMBEDDING_PIPELINE_VERSION", embeddings.EMBEDDING_PIPELINE_VERSION + "-next")
        assert util.analysis_config_fingerprint() != baseline


def test_unknown_provider_keeps_value_error(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "invalid-provider")
    with pytest.raises(ValueError, match="Unknown EMBEDDING_PROVIDER"):
        util.analysis_config_fingerprint()
    with pytest.raises(ValueError, match="Unknown EMBEDDING_PROVIDER"):
        util.build_cache_key("snapshot")
