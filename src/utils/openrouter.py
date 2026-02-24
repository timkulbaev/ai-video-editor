"""OpenRouter API client — OpenAI-compatible format via httpx."""

from __future__ import annotations

import os
from typing import Any

import httpx

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT = 60.0  # seconds
# Shown in OpenRouter usage dashboard. Override via OPENROUTER_REFERER env var.
_DEFAULT_REFERER = "https://github.com/timkulbaev/ai-video-editor"


class OpenRouterError(RuntimeError):
    """Raised on non-2xx responses from OpenRouter."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"OpenRouter error {status_code}: {body[:500]}")


def chat_completion(
    prompt: str,
    model: str,
    system: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> str:
    """Send a chat completion request to OpenRouter and return the response text.

    Args:
        prompt: User message content.
        model: OpenRouter model identifier (e.g., "anthropic/claude-sonnet-4").
        system: Optional system message.
        api_key: OpenRouter API key. Falls back to OPENROUTER_API_KEY env var.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens in the response.

    Returns:
        The assistant's response text.

    Raises:
        OpenRouterError: On non-2xx response.
        EnvironmentError: If no API key is available.
    """
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise EnvironmentError(
            "OPENROUTER_API_KEY is not set. "
            "Set it in your environment or .env file to enable hook/chapter generation."
        )

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    referer = os.environ.get("OPENROUTER_REFERER", _DEFAULT_REFERER)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": referer,
        "X-Title": "AI Video Editor",
    }

    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        response = client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
        )

    if response.status_code != 200:
        raise OpenRouterError(response.status_code, response.text)

    data = response.json()
    return data["choices"][0]["message"]["content"]
