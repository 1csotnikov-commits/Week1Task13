"""ProfileStore — работа с профилями агента (отдельный слой памяти).

Профиль — отдельный слой памяти, более приоритетный, чем long-term. Он
описывает пользователя: предпочтения по стилю, формату, ограничениям.

Хранение:
- один файл на профиль: memory/<agent>/profiles/<name>.json;
- memory/<agent>/active_profile.txt — имя активного профиля (одна строка).
  Если файл отсутствует или пуст — активного профиля нет.

У каждого агента — свой набор профилей; переключение агента не влияет на
профили других агентов.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .errors import MemoryError
from .memory import now_iso

# Обязательные поля профиля (могут быть пустыми строками, но ключи присутствуют).
REQUIRED_FIELDS = ("style", "format", "constraints")

# Поля, которые можно задавать/очищать командами /profile set|unset.
EDITABLE_FIELDS = ("style", "format", "constraints")


def _valid_name(name: str) -> str:
    """Проверить и нормализовать имя профиля (оно же — имя файла)."""
    name = (name or "").strip()
    if not name:
        raise MemoryError("Имя профиля не может быть пустым.")
    if any(ch in name for ch in ("/", "\\", "..")):
        raise MemoryError(f"Недопустимое имя профиля: {name}")
    return name


class ProfileStore:
    """Загрузка/сохранение и CRUD-операции над профилями агента."""

    def __init__(self, memory_dir: str | Path) -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ пути
    @property
    def profiles_dir(self) -> Path:
        return self.memory_dir / "profiles"

    @property
    def active_profile_path(self) -> Path:
        return self.memory_dir / "active_profile.txt"

    def profile_path(self, name: str) -> Path:
        return self.profiles_dir / f"{name}.json"

    # ------------------------------------------------------- ввод-вывод JSON
    def _ensure_profiles_dir(self) -> None:
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    def _load(self, path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise MemoryError(f"Профиль не найден: {path.stem}") from None
        except (json.JSONDecodeError, OSError) as exc:
            raise MemoryError(f"Не удалось прочитать профиль {path}: {exc}") from exc

    def _save(self, path: Path, data: Any) -> None:
        try:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            raise MemoryError(f"Не удалось записать профиль {path}: {exc}") from exc

    # ------------------------------------------------------ активный профиль
    def active_name(self) -> Optional[str]:
        """Имя активного профиля; None, если файл отсутствует или пуст."""
        try:
            text = self.active_profile_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise MemoryError(
                f"Не удалось прочитать {self.active_profile_path}: {exc}"
            ) from exc
        return text or None

    def _write_active(self, name: str) -> None:
        try:
            self.active_profile_path.write_text(name + "\n", encoding="utf-8")
        except OSError as exc:
            raise MemoryError(
                f"Не удалось записать {self.active_profile_path}: {exc}"
            ) from exc

    def _clear_active(self) -> None:
        try:
            if self.active_profile_path.exists():
                self.active_profile_path.unlink()
        except OSError as exc:
            raise MemoryError(
                f"Не удалось удалить {self.active_profile_path}: {exc}"
            ) from exc

    # ------------------------------------------------------------- операции
    def list_profiles(self) -> list[str]:
        if not self.profiles_dir.exists():
            return []
        return sorted(p.stem for p in self.profiles_dir.glob("*.json"))

    def create(self, name: str) -> dict:
        name = _valid_name(name)
        self._ensure_profiles_dir()
        path = self.profile_path(name)
        if path.exists():
            raise MemoryError(f"Профиль «{name}» уже существует.")
        now = now_iso()
        profile = {
            "name": name,
            "style": "",
            "format": "",
            "constraints": "",
            "notes": [],
            "created_at": now,
            "updated_at": now,
        }
        self._save(path, profile)
        return profile

    def load(self, name: Optional[str] = None) -> dict:
        """Загрузить профиль; по умолчанию — активный."""
        if name is None:
            active = self.active_name()
            if not active:
                raise MemoryError("Активный профиль не задан.")
            name = active
        name = _valid_name(name)
        data = self._load(self.profile_path(name))
        # Обязательные поля всегда присутствуют (на случай ручных правок файла).
        for field in REQUIRED_FIELDS:
            data.setdefault(field, "")
        data.setdefault("notes", [])
        data["name"] = name
        return data

    def save(self, profile: dict) -> dict:
        name = _valid_name(profile.get("name"))
        self._ensure_profiles_dir()
        profile["updated_at"] = now_iso()
        self._save(self.profile_path(name), profile)
        return profile

    def delete(self, name: str) -> None:
        name = _valid_name(name)
        path = self.profile_path(name)
        if not path.exists():
            raise MemoryError(f"Профиль «{name}» не найден.")
        try:
            path.unlink()
        except OSError as exc:
            raise MemoryError(f"Не удалось удалить профиль {path}: {exc}") from exc
        if self.active_name() == name:
            self._clear_active()

    def switch(self, name: str) -> str:
        name = _valid_name(name)
        if not self.profile_path(name).exists():
            raise MemoryError(f"Профиль «{name}» не найден.")
        self._write_active(name)
        return name

    # ------------------------------------------------------- правка содержимого
    def _update(self, name: str, mutate) -> dict:
        name = _valid_name(name)
        profile = self.load(name)
        mutate(profile)
        return self.save(profile)

    def set_field(self, name: str, field: str, value: str) -> dict:
        field = (field or "").lower()
        if field not in EDITABLE_FIELDS:
            raise MemoryError("Поле должно быть style | format | constraints.")

        def mutate(profile: dict) -> None:
            profile[field] = value

        return self._update(name, mutate)

    def unset_field(self, name: str, field: str) -> dict:
        return self.set_field(name, field, "")

    def add_note(self, name: str, text: str) -> dict:
        def mutate(profile: dict) -> None:
            profile.setdefault("notes", []).append(text)

        return self._update(name, mutate)

    def del_note(self, name: str, index: int) -> dict:
        def mutate(profile: dict) -> None:
            notes = profile.setdefault("notes", [])
            if index < 0 or index >= len(notes):
                raise MemoryError(
                    f"Индекс заметки вне диапазона: {index} (всего {len(notes)})."
                )
            notes.pop(index)

        return self._update(name, mutate)
