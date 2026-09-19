"""Загрузка и валидация конфигурации проекта.

Приоритет источников значений: CLI-аргументы -> env -> config.json.
API-ключ хранится только в переменных окружения (по имени api_key_env)
и никогда не записывается в config.json.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import ConfigError

DEFAULT_CONFIG_NAME = "config.json"


@dataclass
class ProviderConfig:
    """Описание LLM-провайдера."""

    name: str
    type: str = "openai_compatible"


@dataclass
class AgentConfig:
    """Конфигурация одного агента."""

    name: str
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    endpoint: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 1.0
    top_k: int = 50
    memory_dir: str = "memory/assistant"


@dataclass
class Config:
    """Корневая конфигурация проекта."""

    default_agent: str
    providers: Dict[str, ProviderConfig]
    agents: Dict[str, AgentConfig]
    path: Path = field(default_factory=Path)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        config_path = Path(path) if path else Path(DEFAULT_CONFIG_NAME)
        if not config_path.exists():
            raise ConfigError(f"Файл конфигурации не найден: {config_path}")
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigError(f"Не удалось прочитать {config_path}: {exc}") from exc
        return cls.from_dict(raw, config_path)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any], path: Path) -> "Config":
        if not isinstance(raw, dict):
            raise ConfigError("config.json должен быть объектом (dict).")

        providers_raw = raw.get("providers", {})
        providers: Dict[str, ProviderConfig] = {}
        for name, p in providers_raw.items():
            providers[name] = ProviderConfig(
                name=name,
                type=p.get("type", "openai_compatible"),
            )

        agents_raw = raw.get("agents", {})
        if not agents_raw:
            raise ConfigError("В config.json нет ни одного агента (agents).")

        agents: Dict[str, AgentConfig] = {}
        for name, a in agents_raw.items():
            agents[name] = AgentConfig(
                name=name,
                provider=a.get("provider", "deepseek"),
                model=a.get("model", "deepseek-chat"),
                endpoint=a.get("endpoint", "https://api.deepseek.com"),
                api_key_env=a.get("api_key_env", "DEEPSEEK_API_KEY"),
                system_prompt=a.get("system_prompt", ""),
                temperature=float(a.get("temperature", 0.7)),
                max_tokens=int(a.get("max_tokens", 1024)),
                top_p=float(a.get("top_p", 1.0)),
                top_k=int(a.get("top_k", 50)),
                memory_dir=a.get("memory_dir", f"memory/{name}"),
            )

        # env имеет приоритет над config.json для агента по умолчанию.
        default_agent = os.environ.get("DEFAULT_AGENT") or raw.get(
            "default_agent", next(iter(agents))
        )
        if default_agent not in agents:
            raise ConfigError(
                f"default_agent «{default_agent}» отсутствует в agents: "
                f"{', '.join(agents)}"
            )

        return cls(
            default_agent=default_agent,
            providers=providers,
            agents=agents,
            path=path,
        )

    def agent(self, name: str) -> AgentConfig:
        if name not in self.agents:
            raise ConfigError(f"Агент «{name}» не найден в конфигурации.")
        return self.agents[name]
