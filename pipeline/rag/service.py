"""
RAG Answer Generation Service (Session 21).

Orchestrates retrieval, context building, grounded LLM prompt execution, and citation validation.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from db.store import retrieve_similar_chunks, get_analysis_by_run_id
from rag.llm import BaseLLMProvider, get_llm_provider
from rag.context_builder import build_evidence_context, build_rag_user_prompt, SYSTEM_GROUNDING_PROMPT
from rag.citation_validator import validate_citations


def answer_repository_question(
    session: Session,
    run_id: str,
    question: str,
    top_k: int = 5,
    llm_provider: Optional[BaseLLMProvider] = None,
    embedding_provider: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Main entry point for repository-grounded Q&A (Session 21 RAG Pipeline).

    Args:
        session: SQLAlchemy database session.
        run_id: Analysis run UUID.
        question: Natural language question about the repository code.
        top_k: Number of source chunks to retrieve.
        llm_provider: Optional custom LLM provider instance.
        embedding_provider: Optional custom embedding provider instance.

    Returns:
        Structured AskResponse dict with question, answer, repository, commit_sha,
        validated citations list, and metadata.
    """
    clean_q = question.strip() if question else ""
    if not clean_q:
        return {
            "question": question,
            "answer": "The available repository evidence is insufficient to determine this.",
            "repository": "unknown",
            "commit_sha": None,
            "run_id": run_id,
            "citations": [],
            "retrieved_chunks_count": 0,
            "llm_model": "none",
            "provenance": "AI_GENERATED",
        }

    # 1. Resolve analysis run
    analysis = get_analysis_by_run_id(session, run_id)
    if not analysis:
        return {
            "question": clean_q,
            "answer": f"Analysis run '{run_id}' not found.",
            "repository": "unknown",
            "commit_sha": None,
            "run_id": run_id,
            "citations": [],
            "retrieved_chunks_count": 0,
            "llm_model": "none",
            "provenance": "AI_GENERATED",
        }

    repo_url = analysis.get("repository", "unknown")
    commit_sha = analysis.get("commit_sha")

    # 2. Perform repository/version-scoped vector retrieval (S20)
    retrieval_res = retrieve_similar_chunks(
        session,
        run_id=run_id,
        query_text=clean_q,
        top_k=top_k,
        provider=embedding_provider,
    )

    retrieved_chunks = retrieval_res.get("results", [])

    # 3. Handle empty retrieval or insufficient evidence
    if not retrieved_chunks:
        return {
            "question": clean_q,
            "answer": "The available repository evidence is insufficient to determine this.",
            "repository": repo_url,
            "commit_sha": commit_sha,
            "run_id": run_id,
            "citations": [],
            "retrieved_chunks_count": 0,
            "llm_model": "none",
            "provenance": "AI_GENERATED",
        }

    # 4. Build evidence context & map
    evidence_context, evidence_map = build_evidence_context(retrieved_chunks)
    user_prompt = build_rag_user_prompt(clean_q, evidence_context)

    # 5. Resolve active LLM provider & generate answer
    active_llm = llm_provider or get_llm_provider()
    try:
        raw_answer = active_llm.generate(prompt=user_prompt, system_prompt=SYSTEM_GROUNDING_PROMPT)
    except Exception as exc:
        return {
            "question": clean_q,
            "answer": f"LLM answer service encountered an error: {type(exc).__name__}: {exc}",
            "repository": repo_url,
            "commit_sha": commit_sha,
            "run_id": run_id,
            "citations": [],
            "retrieved_chunks_count": len(retrieved_chunks),
            "llm_model": getattr(active_llm, "model_name", "unknown"),
            "provenance": "AI_GENERATED",
        }

    # 6. Server-side citation validation against authoritative evidence map
    cleaned_answer, validated_citations = validate_citations(raw_answer, evidence_map)

    # If answer is empty or LLM indicated insufficient evidence
    if not cleaned_answer or "insufficient" in cleaned_answer.lower():
        cleaned_answer = "The available repository evidence is insufficient to determine this."
        validated_citations = []

    return {
        "question": clean_q,
        "answer": cleaned_answer,
        "repository": repo_url,
        "commit_sha": commit_sha,
        "run_id": run_id,
        "citations": validated_citations,
        "retrieved_chunks_count": len(retrieved_chunks),
        "llm_model": active_llm.model_name,
        "provenance": "AI_GENERATED",
    }
