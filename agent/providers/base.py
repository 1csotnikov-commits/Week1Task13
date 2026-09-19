"""Базовый класс LLM-провайдера."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Интерфейс провайдера LLM.

    Реализация обязана вернуть dict с ключами:
    - content: str — текст ответа модели;
    - usage: dict — информация о токенах (может быть пустой);
    - model: str  — имя фактически использованной модели (опционально).
    """

    @abstractmethod
    def chat(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Отправить список сообщений и вернуть результат."""
        raise NotImplementedError
