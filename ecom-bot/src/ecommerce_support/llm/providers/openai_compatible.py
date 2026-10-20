"""Generic OpenAI-compatible provider adapter (INT-001, NFR-007).

For local or third-party servers that speak the OpenAI Chat Completions protocol (vLLM, LM
Studio, Ollama's OpenAI endpoint, etc.) selected via config only. Structured output is not
declared in the capability matrix because ``response_format`` support varies by server, so
requesting it fails loudly with ``LLMCapabilityError`` (see ``llm/capabilities.py``).
"""

from __future__ import annotations

from openai import AsyncOpenAI

from ecommerce_support.core.exceptions import ConfigurationError
from ecommerce_support.llm.capabilities import capabilities_for
from ecommerce_support.llm.providers.openai import OpenAILLMClient


class OpenAICompatibleLLMClient(OpenAILLMClient):
    """OpenAI-compatible Chat Completions implementation of :class:`LLMClient`."""

    provider = "openai_compatible"
    capabilities = capabilities_for("openai_compatible")

    def __init__(
        self,
        *,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if not model:
            raise ConfigurationError("OpenAI-compatible provider requires a model name.")
        if client is None:
            if not base_url:
                raise ConfigurationError(
                    "OpenAI-compatible provider requires a base URL "
                    "(set LLM__OPENAI_COMPATIBLE_BASE_URL)."
                )
            client = AsyncOpenAI(
                api_key=api_key or "not-needed",
                base_url=base_url,
                timeout=timeout,
                max_retries=0,
            )
        super().__init__(model=model, client=client, max_tokens=max_tokens, temperature=temperature)
