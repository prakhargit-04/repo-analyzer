"""
Evidence Context Builder & Grounded Prompt Generator (Session 21).

Formats retrieved SourceChunks into structured evidence blocks [E1], [E2], ...
Builds grounded system and user prompts enforcing strict source-derived facts.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


def build_evidence_context(
    retrieved_chunks: List[Dict[str, Any]],
    max_evidence_chars: int = 12000,
) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    """
    Converts a list of retrieved SourceChunk dicts into formatted evidence context.
    Enforces a budget on evidence text to avoid blowing token limits while preserving
    system rules and the user question.

    Returns:
        Tuple of (formatted_context_string, evidence_map):
          - formatted_context_string: Human-readable structured blocks tagged with [E1], [E2]...
          - evidence_map: Dict mapping citation ID ("E1", "E2"...) to full SourceChunk metadata.
    """
    if not retrieved_chunks:
        return "No relevant repository evidence found.", {}

    formatted_blocks: List[str] = []
    evidence_map: Dict[str, Dict[str, Any]] = {}
    current_chars = 0

    for idx, chunk in enumerate(retrieved_chunks, start=1):
        ev_id = f"E{idx}"
        
        chunk_id = chunk.get("chunk_id", "")
        file_path = chunk.get("file_path", "")
        start_line = chunk.get("start_line", 1)
        end_line = chunk.get("end_line", 1)
        language = chunk.get("language", "unknown")
        entity_name = chunk.get("entity_name")
        entity_type = chunk.get("entity_type")
        commit_sha = chunk.get("commit_sha", "")
        provenance = chunk.get("provenance", "TOOL_DERIVED")
        text = chunk.get("chunk_text", "")

        entity_info = f"Entity: {entity_type} {entity_name}\n" if entity_name else ""
        commit_info = f"Commit: {commit_sha}\n" if commit_sha else ""

        header = (
            f"[{ev_id}]\n"
            f"File: {file_path}\n"
            f"Lines: {start_line}-{end_line}\n"
            f"Language: {language}\n"
            f"{entity_info}"
            f"{commit_info}"
            f"ChunkID: {chunk_id}\n\n"
        )
        marker = "\n[truncated]"
        remaining = max_evidence_chars - current_chars
        if remaining <= 0:
            break
        if len(header) + len(text) > remaining:
            # Always retain a first block; its header can itself exceed an
            # impractically tiny caller budget, but text remains correctly
            # truncated and Python slicing is Unicode-safe.
            allowance = max(0, remaining - len(header) - len(marker))
            text = text[:allowance] + marker
        block = header + text
        if len(block) > remaining and idx != 1:
            break
        formatted_blocks.append(block)
        current_chars += len(block)

        evidence_map[ev_id] = {
            "citation_id": ev_id,
            "chunk_id": chunk_id,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "language": language,
            "entity_name": entity_name,
            "entity_type": entity_type,
            "commit_sha": commit_sha,
            "provenance": provenance,
        }

    formatted_context_string = "\n\n" + ("=" * 40) + "\n\n".join(formatted_blocks) + "\n" + ("=" * 40)
    return formatted_context_string, evidence_map


SYSTEM_GROUNDING_PROMPT = """You are an expert technical repository assistant. Your job is to answer user questions about the codebase strictly using the provided repository evidence blocks.

STRICT RULES:
1. Use ONLY the supplied repository evidence blocks marked [E1], [E2], etc.
2. Cite every factual claim or code reference using the exact evidence tag (e.g. [E1], [E2]).
3. Do NOT invent files, function names, line numbers, dependencies, or architectural patterns.
4. If the provided evidence is empty, missing, or insufficient to answer the question, explicitly state:
   "The available repository evidence is insufficient to determine this."
5. Do NOT fabricate or invent citation tags (e.g., do not cite [E99] if E99 was not supplied).
6. Keep source-derived facts separate from any inference.
"""


def build_rag_user_prompt(question: str, evidence_context: str) -> str:
    """Combines user question and formatted evidence context into RAG user prompt."""
    return f"""User Question: {question}

Repository Evidence:
{evidence_context}

Question: {question}

Provide an answer grounded ONLY in the repository evidence above, citing evidence tags [E1], [E2]... where appropriate."""
