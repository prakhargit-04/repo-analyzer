"""
LLM Provider Abstraction for Repository Question Answering (Session 21).

Provides an interchangeable interface for answer generation models.
Includes:
  - BaseLLMProvider: Abstract base class.
  - TestLLMProvider: Deterministic, offline provider for automated testing and CI.
  - OpenAILLMProvider / GeminiLLMProvider: Optional API providers.
  - get_llm_provider: Factory helper.
"""
from __future__ import annotations

import abc
import os
import re
import sys
from typing import Optional


class BaseLLMProvider(abc.ABC):
    """Abstract interface for LLM answer generation models."""

    name: str
    model_name: str

    @abc.abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate answer response text from user prompt and system prompt."""
        pass


class TestLLMProvider(BaseLLMProvider):
    """
    Deterministic mock LLM provider for automated testing & CI.
    Does NOT invoke any external network or paid API.
    Parses the evidence blocks in prompt text and generates predictable answers
    citing available evidence IDs (e.g. [E1], [E2]).
    """

    __test__ = False  # Suppress pytest collection warning

    def __init__(self, model_name: str = "test-deterministic-rag"):
        self.name = "test-llm"
        self.model_name = model_name

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        # Check if evidence context is present in prompt
        evidence_matches = re.findall(r"\[(E\d+)\]", prompt)
        
        # Check if explicitly forced to simulate insufficient evidence
        if "INSUFFICIENT_EVIDENCE_TEST" in prompt or not evidence_matches:
            return "The available repository evidence is insufficient to determine this."

        # Deduplicate evidence matches preserving order
        unique_ev = list(dict.fromkeys(evidence_matches))
        citations_str = "".join([f"[{ev}]" for ev in unique_ev])

        # Extract question if present
        q_match = re.search(r"Question:\s*(.+)", prompt, re.IGNORECASE)
        question = q_match.group(1).strip() if q_match else "this query"

        return f"Based on the repository evidence, {question} is implemented as shown in the source code {citations_str}."


class OpenAILLMProvider(BaseLLMProvider):
    """
    OpenAI ChatCompletion provider.
    Requires OPENAI_API_KEY environment variable.
    """

    def __init__(self, model_name: str = "gpt-4o-mini"):
        self.name = "openai"
        self.model_name = model_name
        self.api_key = os.environ.get("OPENAI_API_KEY")

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is not configured.")
        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.0,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            raise RuntimeError(f"OpenAI generation failed: {exc}") from exc


class GeminiLLMProvider(BaseLLMProvider):
    """
    Google Gemini provider.
    Requires GEMINI_API_KEY or GOOGLE_API_KEY environment variable.
    """

    def __init__(self, model_name: str = "gemini-1.5-flash"):
        self.name = "gemini"
        self.model_name = model_name
        self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY / GOOGLE_API_KEY environment variable is not configured.")
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model_name, system_instruction=system_prompt)
            response = model.generate_content(prompt)
            return response.text or ""
        except Exception as exc:
            raise RuntimeError(f"Gemini generation failed: {exc}") from exc


def get_llm_provider(provider_name: Optional[str] = None) -> BaseLLMProvider:
    """
    Factory function resolving LLM provider instance.
    Defaults to TestLLMProvider in test environments or when unconfigured.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("TESTING"):
        return TestLLMProvider()

    p_name = provider_name or os.environ.get("LLM_PROVIDER", "test")
    p_name_lower = p_name.lower()

    if p_name_lower in ("test", "mock", "deterministic"):
        return TestLLMProvider()
    elif p_name_lower == "openai":
        return OpenAILLMProvider()
    elif p_name_lower in ("gemini", "google"):
        return GeminiLLMProvider()

    # Default fallback to TestLLMProvider for offline safety
    return TestLLMProvider()
