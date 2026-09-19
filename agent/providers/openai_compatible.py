"""OpenAI-совместимый провайдер (DeepSeek, Groq, OpenRouter и т.п.)."""
from __future__ import annotations

from typing import Any

import httpx

from ..errors import LLMError
from .base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    """Единая реализация для API, совместимых с OpenAI Chat Completions.

    Ошибки (сеть, HTTP, неверная структура ответа) пробрасываются наверх
    как LLMError. Ретраи и таймауты не используются (кроме базового таймаута
    httpx, чтобы не зависать бесконечно).
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        top_p: float = 1.0,
        top_k: int = 50,
        timeout: float = 60.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.top_k = top_k
        self.timeout = timeout

    def chat(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        url = f"{self.endpoint}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
        }
        if self.top_k:
            payload["top_k"] = self.top_k

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"Ошибка сети при обращении к LLM ({url}): {exc}") from exc

        if response.status_code >= 400:
            raise LLMError(
                f"LLM вернул ошибку {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(f"Некорректный JSON в ответе LLM: {response.text}") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Неожиданная структура ответа LLM: {data}") from exc

        return {
            "content": content or "",
            "usage": data.get("usage") or {},
            "model": data.get("model"),
        }
