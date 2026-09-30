"""
Citation Validation Engine (Session 21).

Parses citation tags [E1], [E2], etc. from LLM answer text, validates them against
the supplied evidence map, and rejects hallucinated or unknown evidence citations.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def validate_citations(
    answer_text: str,
    evidence_map: Dict[str, Dict[str, Any]]
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Validates citations referenced in LLM answer text.

    Args:
        answer_text: Raw answer string from LLM provider.
        evidence_map: Dict mapping valid citation IDs ("E1", "E2"...) to SourceChunk metadata.

    Returns:
        Tuple of (cleaned_answer_text, validated_citations_list):
          - cleaned_answer_text: Answer string with hallucinated/invalid citation tags removed.
          - validated_citations_list: List of valid CitationItem dicts.
    """
    if not answer_text:
        return "", []

    # Find all citation patterns like [E1], [E2], [E99]
    raw_citations = re.findall(r"\[(E\d+)\]", answer_text)
    
    validated_citations: List[Dict[str, Any]] = []
    seen_ids = set()

    invalid_tags_to_strip = []

    for ev_id in raw_citations:
        if ev_id in evidence_map:
            if ev_id not in seen_ids:
                seen_ids.add(ev_id)
                validated_citations.append(evidence_map[ev_id])
        else:
            invalid_tags_to_strip.append(ev_id)

    # Strip invalid citation tags (e.g. [E99]) from answer text to maintain server-side integrity
    cleaned_text = answer_text
    for invalid_id in invalid_tags_to_strip:
        cleaned_text = cleaned_text.replace(f"[{invalid_id}]", "")

    # Clean up double spaces created by stripping
    cleaned_text = re.sub(r" +", " ", cleaned_text).strip()

    return cleaned_text, validated_citations
