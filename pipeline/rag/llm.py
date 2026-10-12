"""
LLM Provider Abstraction for Repository Question Answering (Session 21 & Session 23).

Provides an interchangeable interface for answer generation models with:
  - BaseLLMProvider: Abstract base class.
  - TestLLMProvider: Deterministic, offline provider for automated testing and CI.
  - OpenAILLMProvider / GeminiLLMProvider: Real API providers with timeout, token bounds, and strict errors.
  - get_llm_provider: Cached factory helper with fail-fast validation.
"""
from __future__ import annotations

import abc
import os
import re
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Custom LLM Exceptions (Session 23 Item 3 Error Mapping)
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Base exception for all LLM provider errors."""
    status_code: int = 502
    detail: str = "LLM provider error."


class LLMNotConfiguredError(LLMError):
    """Provider package missing, key missing, or unknown provider name."""
    status_code: int = 503
    detail: str = "LLM provider is not configured."


class LLMAuthenticationError(LLMError):
    """Invalid or rejected API key."""
    status_code: int = 502
    detail: str = "LLM provider rejected the configured API key."


class LLMRateLimitError(LLMError):
    """Quota or rate limit exceeded."""
    status_code: int = 429
    detail: str = "LLM provider rate limit exceeded."


class LLMTimeoutError(LLMError):
    """Provider call request timed out."""
    status_code: int = 504
    detail: str = "LLM provider request timed out."


class LLMResponseError(LLMError):
    """Network connection failure or malformed API response."""
    status_code: int = 502
    detail: str = "LLM provider network error or malformed response."


class BaseLLMProvider(abc.ABC):
    """Abstract interface for LLM answer generation models."""

    provider_id: str
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
    """

    __test__ = False  # Suppress pytest collection warning

    def __init__(self, model_name: str = "test-deterministic-rag"):
        self.provider_id = "test"
        self.name = "test-llm"
        self.model_name = model_name

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        evidence_matches = re.findall(r"\[(E\d+)\]", prompt)

        if "INSUFFICIENT_EVIDENCE_TEST" in prompt or not evidence_matches:
            return "The available repository evidence is insufficient to determine this."

        unique_ev = list(dict.fromkeys(evidence_matches))
        citations_str = "".join([f"[{ev}]" for ev in unique_ev])

        q_match = re.search(r"Question:\s*(.+)", prompt, re.IGNORECASE)
        question = q_match.group(1).strip() if q_match else "this query"

        return f"Based on the repository evidence, {question} is implemented as shown in the source code {citations_str}."


class OpenAILLMProvider(BaseLLMProvider):
    """
    OpenAI ChatCompletion provider with timeouts, token bounds, and strict error handling.
    """

    def __init__(self, model_name: str = "gpt-4o-mini"):
        self.provider_id = "openai"
        self.name = "openai"
        self.model_name = os.environ.get("OPENAI_MODEL_NAME", model_name)
        self.api_key = os.environ.get("OPENAI_API_KEY")

        try:
            import openai
        except ImportError as exc:
            raise LLMNotConfiguredError(
                "Package 'openai' is not installed. Install it with: pip install openai"
            ) from exc

        if not self.api_key:
            raise LLMNotConfiguredError(
                "OPENAI_API_KEY environment variable is not set."
            )

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        import openai

        client = openai.OpenAI(api_key=self.api_key, timeout=30.0)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.0,
                max_tokens=1024,
            )
            content = response.choices[0].message.content
            if not content:
                raise LLMResponseError("LLM provider network error or malformed response.")
            return content.strip()
        except openai.AuthenticationError as exc:
            raise LLMAuthenticationError("LLM provider rejected the configured API key.") from exc
        except openai.RateLimitError as exc:
            raise LLMRateLimitError("LLM provider rate limit exceeded.") from exc
        except (openai.APITimeoutError, TimeoutError) as exc:
            raise LLMTimeoutError("LLM provider request timed out.") from exc
        except (openai.APIConnectionError, openai.APIError) as exc:
            raise LLMResponseError("LLM provider network error or malformed response.") from exc
        except Exception as exc:
            raise LLMResponseError("LLM provider network error or malformed response.") from exc


class GeminiLLMProvider(BaseLLMProvider):
    """
    Google Gemini provider with timeouts, token bounds, and strict error handling.
    """

    def __init__(self, model_name: str = "gemini-1.5-flash"):
        self.provider_id = "gemini"
        self.name = "gemini"
        self.model_name = os.environ.get("GEMINI_MODEL_NAME", model_name)
        self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise LLMNotConfiguredError(
                "Package 'google-generativeai' is not installed. Install it with: pip install google-generativeai"
            ) from exc

        if not self.api_key:
            raise LLMNotConfiguredError(
                "GEMINI_API_KEY / GOOGLE_API_KEY environment variable is not set."
            )

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        import google.generativeai as genai
        import google.api_core.exceptions as g_exceptions

        genai.configure(api_key=self.api_key)
        try:
            model = genai.GenerativeModel(
                self.model_name,
                system_instruction=system_prompt,
                generation_config={"max_output_tokens": 1024, "temperature": 0.0},
            )
            response = model.generate_content(prompt, request_options={"timeout": 30.0})
            if not response.text:
                raise LLMResponseError("LLM provider network error or malformed response.")
            return response.text.strip()
        except g_exceptions.Unauthenticated as exc:
            raise LLMAuthenticationError("LLM provider rejected the configured API key.") from exc
        except g_exceptions.ResourceExhausted as exc:
            raise LLMRateLimitError("LLM provider rate limit exceeded.") from exc
        except g_exceptions.DeadlineExceeded as exc:
            raise LLMTimeoutError("LLM provider request timed out.") from exc
        except g_exceptions.GoogleAPICallError as exc:
            raise LLMResponseError("LLM provider network error or malformed response.") from exc
        except Exception as exc:
            raise LLMResponseError("LLM provider network error or malformed response.") from exc


_CACHED_LLM_PROVIDER: Optional[BaseLLMProvider] = None
_CACHED_LLM_KEY: Optional[tuple] = None


def reset_llm_provider_cache() -> None:
    """Clear the cached LLM provider instance."""
    global _CACHED_LLM_PROVIDER, _CACHED_LLM_KEY
    _CACHED_LLM_PROVIDER = None
    _CACHED_LLM_KEY = None


def get_llm_provider(
    provider_name: Optional[str] = None,
    force_reload: bool = False,
) -> BaseLLMProvider:
    """
    Factory function resolving cached LLM provider instance.
    Default (unconfigured) provider is TestLLMProvider.
    Raises LLMNotConfiguredError for explicit misconfiguration or unknown provider.
    """
    global _CACHED_LLM_PROVIDER, _CACHED_LLM_KEY

    p_name = provider_name or os.environ.get("LLM_PROVIDER")
    if not p_name:
        p_name = "test"

    p_name_clean = p_name.strip().lower()
    model_name = (
        os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini") if p_name_clean == "openai"
        else os.environ.get("GEMINI_MODEL_NAME", "gemini-1.5-flash") if p_name_clean in ("gemini", "google")
        else "test-deterministic-rag"
    )
    cache_key = (p_name_clean, model_name)

    if not force_reload and _CACHED_LLM_PROVIDER is not None and _CACHED_LLM_KEY == cache_key:
        return _CACHED_LLM_PROVIDER

    if p_name_clean in ("test", "mock", "deterministic"):
        instance = TestLLMProvider()
    elif p_name_clean == "openai":
        instance = OpenAILLMProvider(model_name)
    elif p_name_clean in ("gemini", "google"):
        instance = GeminiLLMProvider(model_name)
    else:
        raise LLMNotConfiguredError(
            f"Unknown LLM_PROVIDER '{p_name}'. Valid options: 'test', 'openai', 'gemini'."
        )

    _CACHED_LLM_PROVIDER = instance
    _CACHED_LLM_KEY = cache_key
    return instance
