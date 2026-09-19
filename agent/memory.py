"""MemoryStore — низкоуровневая работа с файлами памяти.

Каждый слой хранится в отдельном JSON-файле:
- краткосрочная:  short_term.json
- рабочая:        working_<task_name>.json (один файл на задачу)
- долговременная: long_term.json

Все идентификаторы — UUID и не переиспользуются после удаления.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from .errors import MemoryError

LAYERS = ("long", "working", "short")


def now_iso() -> str:
    """Текущее время в ISO 8601 (UTC)."""
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    """Новый уникальный UUID (не переиспользуется после удаления)."""
    return str(uuid4())


class MemoryStore:
    """Загрузка/сохранение и CRUD-операции над файлами памяти."""

    def __init__(self, memory_dir: str | Path) -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------- пути
    @property
    def short_path(self) -> Path:
        return self.memory_dir / "short_term.json"

    @property
    def long_path(self) -> Path:
        return self.memory_dir / "long_term.json"

    def working_path(self, task_name: str) -> Path:
        return self.memory_dir / f"working_{task_name}.json"

    def working_files(self) -> list[Path]:
        return sorted(self.memory_dir.glob("working_*.json"))

    # --------------------------------------------------- ввод-вывод JSON
    def _load(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise MemoryError(f"Не удалось прочитать файл памяти {path}: {exc}") from exc

    def _save(self, path: Path, data: Any) -> None:
        try:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            raise MemoryError(f"Не удалось записать файл памяти {path}: {exc}") from exc

    def _delete(self, path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            raise MemoryError(f"Не удалось удалить файл памяти {path}: {exc}") from exc

    # ------------------------------------------------- краткосрочная
    def load_short(self) -> dict:
        return self._load(self.short_path, {"task": None, "messages": []})

    def save_short(self, data: dict) -> None:
        self._save(self.short_path, data)

    def delete_short(self) -> None:
        self._delete(self.short_path)

    # ------------------------------------------------- долговременная
    def load_long(self) -> dict:
        return self._load(self.long_path, {"records": []})

    def save_long(self, data: dict) -> None:
        self._save(self.long_path, data)

    # --------------------------------------------------- рабочая
    def load_working(self, task_name: str) -> Optional[dict]:
        return self._load(self.working_path(task_name), None)

    def create_working(self, task_name: str) -> dict:
        data = {"task": task_name, "created_at": now_iso(), "records": []}
        self._save(self.working_path(task_name), data)
        return data

    def save_working(self, task_name: str, data: dict) -> None:
        self._save(self.working_path(task_name), data)

    # ------------------------------------------------- фабрики записей
    @staticmethod
    def make_message(role: str, content: str) -> dict:
        return {"id": new_id(), "role": role, "content": content, "ts": now_iso()}

    @staticmethod
    def make_working_record(content: str) -> dict:
        return {"id": new_id(), "content": content, "ts": now_iso()}

    @staticmethod
    def make_long_record(record_type: str, content: str) -> dict:
        return {"id": new_id(), "type": record_type, "content": content, "ts": now_iso()}

    @staticmethod
    def remove_record(records: list, record_id: str) -> bool:
        """Удалить запись по id; вернуть True, если запись найдена."""
        for index, record in enumerate(records):
            if record.get("id") == record_id:
                records.pop(index)
                return True
        return False
