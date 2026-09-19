"""Иерархия исключений проекта."""


class AgentError(Exception):
    """Базовое исключение агента.

    Все ошибки приложения оборачиваются в AgentError или его подклассы,
    чтобы интерфейсы (CLI) могли единообразно показывать их пользователю.
    """


class ConfigError(AgentError):
    """Ошибка конфигурации."""


class MemoryError(AgentError):
    """Ошибка работы с памятью."""


class TaskError(AgentError):
    """Ошибка работы с задачами."""


class LLMError(AgentError):
    """Ошибка обращения к LLM-провайдеру."""
