"""AgentManager — управление набором агентов."""
from __future__ import annotations

import os
from typing import Optional

from .agent import Agent
from .config import AgentConfig, Config
from .errors import AgentError, ConfigError
from .providers.base import LLMProvider
from .providers.openai_compatible import OpenAICompatibleProvider


def build_provider(agent_config: AgentConfig, provider_type: str) -> LLMProvider:
    """Создать провайдер для агента.

    API-ключ берётся только из переменной окружения по имени api_key_env
    и никогда не хранится в конфиге.
    """
    api_key = os.environ.get(agent_config.api_key_env)
    if not api_key:
        raise ConfigError(
            f"Не задана переменная окружения {agent_config.api_key_env} "
            f"(API-ключ для агента «{agent_config.name}»)."
        )
    if provider_type == "openai_compatible":
        return OpenAICompatibleProvider(
            endpoint=agent_config.endpoint,
            model=agent_config.model,
            api_key=api_key,
            temperature=agent_config.temperature,
            max_tokens=agent_config.max_tokens,
            top_p=agent_config.top_p,
            top_k=agent_config.top_k,
        )
    raise ConfigError(f"Неизвестный тип провайдера: {provider_type}")


class AgentManager:
    """Поддерживает произвольное число агентов; активен один."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._agents: dict[str, Agent] = {}
        self.active_name: Optional[str] = None
        self._build()

    def _build(self) -> None:
        for name, agent_config in self.config.agents.items():
            def factory(acfg: AgentConfig = agent_config) -> LLMProvider:
                provider_type = self.config.providers[acfg.provider].type
                return build_provider(acfg, provider_type)

            self._agents[name] = Agent(agent_config, provider_factory=factory)

        default = self.config.default_agent
        if default not in self._agents:
            default = next(iter(self._agents), None)
        self.active_name = default

    def active(self) -> Agent:
        """Вернуть активного агента (провайдер создаётся лениво при ask)."""
        if self.active_name is None:
            raise AgentError("Нет доступных агентов.")
        return self._agents[self.active_name]

    def switch(self, name: str) -> Agent:
        """Переключить активного агента."""
        if name not in self._agents:
            raise AgentError(
                f"Агент «{name}» не найден. Доступные: {', '.join(self._agents)}"
            )
        self.active_name = name
        return self._agents[name]

    def get(self, name: str) -> Agent:
        if name not in self._agents:
            raise AgentError(f"Агент «{name}» не найден.")
        return self._agents[name]

    def list_names(self) -> list[str]:
        return list(self._agents.keys())
