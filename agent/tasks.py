"""TaskManager — управление задачами агента."""
from __future__ import annotations

from .errors import TaskError
from .memory import MemoryStore


class TaskManager:
    """Одна активная задача на агента. Задачи привязаны к агенту.

    Задачи хранятся в виде файлов working_<task_name>.json в каталоге памяти
    агента; список задач — это список таких файлов.
    """

    def __init__(self, agent_name: str, store: MemoryStore) -> None:
        self.agent_name = agent_name
        self.store = store
        self.active_task: str | None = None

    def exists(self, name: str) -> bool:
        return self.store.working_path(name).exists()

    def list_tasks(self) -> list[str]:
        names = [p.stem[len("working_"):] for p in self.store.working_files()]
        return sorted(names)

    def create_task(self, name: str) -> str:
        if not name.strip():
            raise TaskError("Имя задачи не может быть пустым.")
        if self.exists(name):
            raise TaskError(
                f"Задача «{name}» уже существует. Используйте /task switch {name}."
            )
        self.store.create_working(name)
        self.active_task = name
        return name

    def switch_task(self, name: str) -> str:
        if not self.exists(name):
            raise TaskError(f"Задача «{name}» не найдена. Список задач: /tasks")
        self.active_task = name
        return name

    def current_task(self) -> str | None:
        return self.active_task
