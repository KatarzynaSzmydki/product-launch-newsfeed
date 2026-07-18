"""Provider-agnostic LLM + embeddings client.

Every caller in this package talks to the `LLMClient` protocol, not to a
specific vendor SDK. Today the only backend is Gemini (free tier); adding
Groq / OpenRouter / OpenAI later is a one-module change — implement the
protocol and point `get_default_client` at it.
"""

from __future__ import annotations

import os
from typing import Protocol


class LLMClient(Protocol):
    def generate(self, prompt: str) -> str:
        """Return a text completion for a single prompt."""
        ...

    def embed(self, text: str) -> list[float]:
        """Return an embedding vector for a piece of text."""
        ...


class GeminiClient:
    """Gemini free-tier backend. One API key covers both generation and embeddings."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-flash-latest",
        embedding_model: str = "gemini-embedding-001",
    ) -> None:
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Get a free key from "
                "https://aistudio.google.com/apikey (no card required), then:\n"
                "- deployed: add `GEMINI_API_KEY = \"...\"` under Settings > Secrets "
                "in the Streamlit Cloud dashboard;\n"
                "- local: copy analytics/.env.example to analytics/.env and fill it in."
            )

        from google import genai  # deferred import: rest of the package works without the SDK installed

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._embedding_model = embedding_model

    def generate(self, prompt: str) -> str:
        response = self._client.models.generate_content(model=self._model, contents=prompt)
        return response.text

    def embed(self, text: str) -> list[float]:
        response = self._client.models.embed_content(model=self._embedding_model, contents=text)
        return response.embeddings[0].values


def get_default_client() -> LLMClient:
    """The configured LLM backend. Gemini today; swap the return here when adding a provider."""
    return GeminiClient()
