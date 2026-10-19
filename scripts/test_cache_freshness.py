#!/usr/bin/env python3
"""
Test cache freshness, cache key generation, and config fingerprint sensitivity.
"""
import os
import sys
import tempfile
from pathlib import Path

# Setup paths
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PIPELINE_DIR = os.path.join(REPO_ROOT, "pipeline")
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from util import (
    analysis_config_fingerprint,
    build_cache_key,
    semgrep_ruleset_identity,
    resolve_snapshot_id,
    CACHE_SCHEMA_VERSION,
    ANALYZER_VERSION,
)
from chunker import SOURCE_CHUNKER_VERSION
from embeddings import EMBEDDING_PIPELINE_VERSION, embedding_cache_identity

out_lines = []
out_lines.append("=== A4 CACHE FRESHNESS INVESTIGATION ===\n")

# 1. Config Fingerprint Components
provider_name, model_name, provider_version = embedding_cache_identity()
out_lines.append("1. Config Fingerprint Components:")
out_lines.append(f"   - CACHE_SCHEMA_VERSION     : {CACHE_SCHEMA_VERSION}")
out_lines.append(f"   - ANALYZER_VERSION         : {ANALYZER_VERSION}")
out_lines.append(f"   - SOURCE_CHUNKER_VERSION   : {SOURCE_CHUNKER_VERSION}")
out_lines.append(f"   - EMBEDDING_PIPELINE_VER   : {EMBEDDING_PIPELINE_VERSION}")
out_lines.append(f"   - Embedding provider_name  : {provider_name}")
out_lines.append(f"   - Embedding model_name     : {model_name}")
out_lines.append(f"   - Embedding provider_ver   : {provider_version}")
out_lines.append(f"   - semgrep_ruleset_identity : {semgrep_ruleset_identity()}")

fp_default = analysis_config_fingerprint()
out_lines.append(f"\nDefault analysis_config_fingerprint: {fp_default}")

# 2. Check Embedding Provider Sensitivity
out_lines.append("\n2. Embedding Provider Sensitivity:")
os.environ["EMBEDDING_PROVIDER"] = "test"
fp_test_prov = analysis_config_fingerprint()
out_lines.append(f"   - EMBEDDING_PROVIDER='test': {fp_test_prov}")
out_lines.append(f"   - Fingerprint matches default? {fp_default == fp_test_prov}")

# 3. Check Semgrep Ruleset Sensitivity
out_lines.append("\n3. Semgrep Ruleset Sensitivity:")
# Test with dummy rules file
with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
    f.write("rules:\n  - id: custom-rule\n    pattern: eval($X)\n    message: bad\n    severity: ERROR\n    languages: [python]\n")
    rule_file = f.name

try:
    os.environ["SEMGREP_CONFIG"] = rule_file
    fp_custom_rule = analysis_config_fingerprint()
    out_lines.append(f"   - SEMGREP_CONFIG='{rule_file}' identity: {semgrep_ruleset_identity()}")
    out_lines.append(f"   - Custom rule fingerprint: {fp_custom_rule}")
    out_lines.append(f"   - Custom rule fingerprint differs from default: {fp_custom_rule != fp_default}")

    # Edit custom rule file
    with open(rule_file, "a") as f:
        f.write("# comment change\n")
    fp_edited_rule = analysis_config_fingerprint()
    out_lines.append(f"   - Edited rule file fingerprint: {fp_edited_rule}")
    out_lines.append(f"   - Editing rules file changed fingerprint? {fp_edited_rule != fp_custom_rule}")
finally:
    if os.path.exists(rule_file):
        os.remove(rule_file)
    os.environ.pop("SEMGREP_CONFIG", None)

# 4. Check Analyzer Availability Sensitivity
out_lines.append("\n4. Analyzer Availability Sensitivity:")
out_lines.append("   - Are analyzer versions or availability (semgrep, gitleaks, bandit, radon, lizard, osv) in analysis_config_fingerprint()?")
out_lines.append(f"   - Answer: NO. The components tuple in analysis_config_fingerprint only contains: {['CACHE_SCHEMA_VERSION', 'ANALYZER_VERSION', 'SOURCE_CHUNKER_VERSION', 'EMBEDDING_PIPELINE_VERSION', 'provider_name', 'model_name', 'provider_version', 'semgrep_ruleset_identity']}")
out_lines.append("   - Implication: If an analyzer was missing (status='unavailable') when a cache entry was created, and the user subsequently installs the analyzer on the host machine, the cache key does NOT change. The pipeline will hit the existing cache and return the old result where that analyzer was unavailable!")

# 5. Check Commit SHA in Cache Key
out_lines.append("\n5. Commit SHA in Cache Key:")
dummy_sha_1 = "1111111111111111111111111111111111111111"
dummy_sha_2 = "2222222222222222222222222222222222222222"
key_1 = build_cache_key(dummy_sha_1)
key_2 = build_cache_key(dummy_sha_2)
out_lines.append(f"   - Cache key for commit {dummy_sha_1[:8]}: {key_1}")
out_lines.append(f"   - Cache key for commit {dummy_sha_2[:8]}: {key_2}")
out_lines.append(f"   - Does commit SHA change the cache key? {key_1 != key_2}")
out_lines.append("   - Fresh clone uses git SHA as snapshot_id -> commit SHA is directly baked into cache key.")
out_lines.append("   - Local path uses content-sha256 of all files -> dirty trees invalidate, identical content with different commit SHA reuses snapshot content hash unless git SHA is used.")

out_text = "\n".join(out_lines) + "\n"
out_path = os.path.join(REPO_ROOT, "docs", "s25_evidence", "a4_cache_freshness.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(out_text)

print(out_text)
