"""Agent — объектная сущность, инкапсулирующая LLM и слои памяти."""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from .config import AgentConfig
from .errors import LLMError, MemoryError, TaskError
from .fsm import Fsm, Stage
from .memory import MemoryStore, now_iso
from .profiles import ProfileStore
from .providers.base import LLMProvider
from .tasks import TaskManager

LAYER_LABELS = {
    "profile": "ПРОФИЛЬ (PROFILE)",
    "long": "ДОЛГОВРЕМЕННАЯ ПАМЯТЬ (LONG-TERM)",
    "working": "РАБОЧАЯ ПАМЯТЬ (WORKING)",
    "short": "КРАТКОСРОЧНАЯ ПАМЯТЬ (SHORT-TERM)",
}

LONG_TYPES = ("decision", "knowledge")


class Agent:
    """Агент с явной многослойной моделью памяти.

    Каждый слой хранится отдельно; пользователь явно выбирает слой при
    сохранении. Все включённые слои подмешиваются в промт в порядке:
    system -> profile -> long-term -> working -> short-term -> текущий запрос.
    """

    def __init__(
        self,
        config: AgentConfig,
        provider: Optional[LLMProvider] = None,
        provider_factory: Optional[Callable[[], LLMProvider]] = None,
    ) -> None:
        self.config = config
        self.name = config.name
        self._provider = provider
        self._provider_factory = provider_factory

        self.store = MemoryStore(config.memory_dir)
        self.profiles = ProfileStore(config.memory_dir)
        self.tasks = TaskManager(config.name, self.store)

        # Какие слои подмешиваются в промт. По умолчанию — все.
        self.usage = {"profile": True, "long": True, "working": True, "short": True}
        self.debug_enabled = False
        self.metrics_enabled = False
        self.prompt_save = False  # CLI-вариант A: спрашивать «сохранить куда?»

        self.last_debug: Optional[list[dict]] = None
        self.last_metrics: Optional[dict] = None

        # Восстановление краткосрочной памяти и активной задачи из файла.
        self.short_term = self.store.load_short()
        saved_task = self.short_term.get("task")
        if saved_task and self.tasks.exists(saved_task):
            self.tasks.active_task = saved_task
        else:
            self.tasks.active_task = None
            self.short_term["task"] = None

    # ------------------------------------------------------------------ провайдер
    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            if self._provider_factory is None:
                raise LLMError("У агента не задан LLM-провайдер.")
            self._provider = self._provider_factory()
        return self._provider

    # ------------------------------------------------------------- основной метод
    def ask(self, prompt: str) -> str:
        """Обработать запрос пользователя и вернуть ответ модели."""
        started = time.perf_counter()

        # 1. Сообщение пользователя в short-term.
        self.short_term["task"] = self.tasks.active_task
        self.short_term.setdefault("messages", [])
        self.short_term["messages"].append(self.store.make_message("user", prompt))

        # 2. Формирование промта с учётом включённых слоёв.
        messages, debug_sections = self._build_prompt(prompt)
        self.last_debug = debug_sections

        # 3. Запрос к LLM.
        result = self.provider.chat(messages)
        content = result.get("content") or ""

        # 4. Ответ в short-term.
        self.short_term["messages"].append(
            self.store.make_message("assistant", content)
        )

        # 5. Сохранение short-term на диск (только при активной задаче).
        if self.tasks.active_task:
            self.store.save_short(self.short_term)

        # Метрики.
        self.last_metrics = self._make_metrics(result, time.perf_counter() - started)
        return content

    # ------------------------------------------------------------------- промт
    def _build_prompt(self, current_request: str) -> tuple[list[dict], list[dict]]:
        sections: list[tuple[str, str]] = []
        debug_sections: list[dict] = []

        if self.usage["profile"]:
            active_profile = self.profiles.active_name()
            if active_profile:
                try:
                    profile = self.profiles.load(active_profile)
                except MemoryError:
                    profile = None
                if profile:
                    sections.append(("profile", self._format_profile(profile)))
                    debug_sections.append(
                        {
                            "layer": "profile",
                            "name": profile.get("name"),
                            "fields": {
                                "style": profile.get("style", ""),
                                "format": profile.get("format", ""),
                                "constraints": profile.get("constraints", ""),
                            },
                            "notes": list(profile.get("notes", [])),
                        }
                    )

        if self.usage["long"]:
            records = self.store.load_long().get("records", [])
            if records:
                sections.append(("long", self._format_long(records)))
                debug_sections.append({"layer": "long", "records": list(records)})

        if self.usage["working"] and self.tasks.active_task:
            data = self.store.load_working(self.tasks.active_task)
            if data and data.get("records"):
                sections.append(("working", self._format_working(data)))
                debug_sections.append(
                    {
                        "layer": "working",
                        "task": data.get("task"),
                        "records": list(data["records"]),
                    }
                )

        state = self._build_state_block()
        if state:
            sections.append(("fsm", state[0]))
            debug_sections.append(state[1])

        if self.usage["short"]:
            messages = self.short_term.get("messages", [])
            if messages:
                sections.append(("short", self._format_short(messages)))
                debug_sections.append(
                    {
                        "layer": "short",
                        "task": self.short_term.get("task"),
                        "messages": list(messages),
                    }
                )

        blocks = []
        for layer, text in sections:
            if layer == "fsm":
                blocks.append(text)
            else:
                blocks.append(f"=== {LAYER_LABELS[layer]} ===\n{text}")
        blocks.append(f"=== ТЕКУЩИЙ ЗАПРОС ===\n{current_request}")
        user_content = "\n\n".join(blocks)

        messages = [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": user_content},
        ]
        return messages, debug_sections

    @staticmethod
    def _format_profile(profile: dict) -> str:
        lines = [f"Имя профиля: {profile.get('name')}"]
        lines.append(f"Стиль: {profile.get('style', '')}")
        lines.append(f"Формат: {profile.get('format', '')}")
        lines.append(f"Ограничения: {profile.get('constraints', '')}")
        notes = profile.get("notes", [])
        if notes:
            lines.append("Заметки:")
            lines.extend(f"- {n}" for n in notes)
        return "\n".join(lines)

    @staticmethod
    def _format_long(records: list[dict]) -> str:
        return "\n".join(f"[{r.get('type')}] {r.get('content')}" for r in records)

    @staticmethod
    def _format_working(data: dict) -> str:
        lines = [f"Задача: {data.get('task')}"]
        lines.extend(f"- {r.get('content')}" for r in data.get("records", []))
        return "\n".join(lines)

    @staticmethod
    def _format_short(messages: list[dict]) -> str:
        lines = []
        for m in messages:
            role = "Пользователь" if m.get("role") == "user" else "Ассистент"
            lines.append(f"{role}: {m.get('content')}")
        return "\n".join(lines)

    @staticmethod
    def _make_metrics(result: dict, elapsed: float) -> dict:
        usage = result.get("usage") or {}
        return {
            "elapsed": round(elapsed, 3),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "model": result.get("model"),
        }

    def _build_state_block(self) -> Optional[tuple[str, dict]]:
        """Блок состояния задачи (FSM) для промта, если он применим.

        Блок добавляется только если у активной задачи есть этапы, задача не на
        паузе и не завершена. Возвращает (текст, отладочную секцию) или None.
        """
        if not self.tasks.active_task:
            return None
        fsm = self.fsm()
        if fsm is None or fsm.is_empty() or fsm.paused or fsm.completed:
            return None
        stage = fsm.active_stage()
        if stage is None:
            return None
        text = (
            "[СОСТОЯНИЕ ЗАДАЧИ]\n"
            f"Текущий этап: {stage.name}\n"
            f"Описание этапа: {stage.description}\n"
            f"Ожидаемое действие: {stage.expected_action}\n"
            f"Условие завершения этапа: {stage.condition}\n"
            "\nРаботай в рамках текущего этапа. Не переходи к следующему, "
            "пока не выполнено условие."
        )
        return text, {"layer": "fsm", "text": text}

    # ------------------------------------------------------------------- задачи
    def task_new(self, name: str) -> str:
        self.tasks.create_task(name)
        self._reset_short_for_task(name)
        return name

    def task_switch(self, name: str) -> str:
        self.tasks.switch_task(name)
        self._reset_short_for_task(name)
        return name

    def _reset_short_for_task(self, name: str) -> None:
        self.short_term = {"task": name, "messages": []}
        self.store.save_short(self.short_term)

    def task_list(self) -> list[str]:
        return self.tasks.list_tasks()

    def task_current(self) -> Optional[str]:
        return self.tasks.current_task()

    # --------------------------------------------------------------------- FSM
    def fsm(self) -> Optional[Fsm]:
        """Вернуть состояние конечного автомата активной задачи (или None)."""
        data = self._working_data()
        return Fsm.from_dict(data.get("fsm")) if data else None

    def fsm_info(self) -> Optional[dict]:
        fsm = self.fsm()
        if fsm is None:
            return None
        data = fsm.to_dict()
        data["stages"] = sorted(data["stages"], key=lambda s: s["order"])
        return data

    def fsm_current_stage(self) -> Optional[dict]:
        fsm = self.fsm()
        if fsm is None:
            return None
        stage = fsm.active_stage()
        return stage.to_dict() if stage else None

    def fsm_current_stage_name(self) -> Optional[str]:
        fsm = self.fsm()
        return fsm.current_stage if fsm else None

    def _working_data(self) -> Optional[dict]:
        if not self.tasks.active_task:
            return None
        return self.store.load_working(self.tasks.active_task)

    def _require_working(self) -> dict:
        if not self.tasks.active_task:
            raise TaskError("Нет активной задачи.")
        data = self.store.load_working(self.tasks.active_task)
        if data is None:
            data = self.store.create_working(self.tasks.active_task)
        return data

    def _save_working(self, data: dict) -> None:
        self.store.save_working(self.tasks.active_task, data)

    @staticmethod
    def _fsm_from(data: dict) -> Fsm:
        fsm = Fsm.from_dict(data.get("fsm"))
        if fsm is None or fsm.is_empty():
            raise TaskError("У задачи нет этапов. Задайте их через /task stages set.")
        return fsm

    def fsm_stages_set(self, stages: list[dict]) -> list[str]:
        """Полностью перезаписать набор этапов.

        Очищает рабочую память, все статусы — pending, первый этап — active.
        Возвращает список имён этапов в порядке их order.
        """
        data = self._require_working()
        built: list[Stage] = []
        for i, raw in enumerate(stages):
            name = str(raw.get("name") or "").strip()
            if not name:
                raise TaskError("Имя этапа не может быть пустым.")
            built.append(
                Stage(
                    name=name,
                    description=str(raw.get("description") or "").strip(),
                    condition=str(raw.get("condition") or "").strip(),
                    expected_action=str(raw.get("expected_action") or "").strip(),
                    status="active" if i == 0 else "pending",
                    order=i,
                )
            )
        fsm = Fsm(stages=built, current_stage=built[0].name if built else None)
        data["records"] = []
        data["fsm"] = fsm.to_dict()
        self._save_working(data)
        return [s.name for s in built]

    def fsm_next(self) -> str:
        """Принудительно перейти на следующий этап (или завершить задачу)."""
        data = self._require_working()
        fsm = self._fsm_from(data)
        if fsm.completed:
            raise TaskError("Задача уже завершена.")
        current = fsm.active_stage()
        if current is None:
            raise TaskError("Нет активного этапа.")
        nxt = fsm.next_stage()
        current.status = "completed"
        if nxt is None:
            for s in fsm.stages:
                s.status = "completed"
            fsm.completed = True
            fsm.current_stage = None
            data["records"] = []
            data["fsm"] = fsm.to_dict()
            self._save_working(data)
            return (
                "Последний этап завершён. Задача помечена завершённой, "
                "рабочая память очищена."
            )
        nxt.status = "active"
        fsm.current_stage = nxt.name
        data["fsm"] = fsm.to_dict()
        self._save_working(data)
        return f"Переход к этапу «{nxt.name}»."

    def fsm_back(self) -> str:
        """Вернуться на предыдущий этап."""
        data = self._require_working()
        fsm = self._fsm_from(data)
        if fsm.completed:
            raise TaskError("Задача завершена — назад переходить нельзя.")
        current = fsm.active_stage()
        if current is None:
            raise TaskError("Нет активного этапа.")
        prev = fsm.prev_stage()
        if prev is None:
            raise TaskError("Это первый этап — назад переходить некуда.")
        current.status = "pending"
        prev.status = "active"
        fsm.current_stage = prev.name
        data["fsm"] = fsm.to_dict()
        self._save_working(data)
        return f"Возврат к этапу «{prev.name}»."

    def fsm_goto(self, name: str) -> str:
        """Перейти к конкретному этапу по имени."""
        data = self._require_working()
        fsm = self._fsm_from(data)
        if fsm.completed:
            raise TaskError("Задача завершена.")
        target = fsm.stage_by_name(name)
        if target is None:
            raise TaskError(f"Этап «{name}» не найден.")
        current = fsm.active_stage()
        if current is not None and current.name != name:
            current.status = "pending"
        target.status = "active"
        fsm.current_stage = target.name
        data["fsm"] = fsm.to_dict()
        self._save_working(data)
        return f"Переход к этапу «{target.name}»."

    def fsm_pause(self) -> str:
        data = self._require_working()
        fsm = self._fsm_from(data)
        fsm.paused = True
        data["fsm"] = fsm.to_dict()
        self._save_working(data)
        return "Задача поставлена на паузу."

    def fsm_resume(self) -> str:
        data = self._require_working()
        fsm = self._fsm_from(data)
        fsm.paused = False
        data["fsm"] = fsm.to_dict()
        self._save_working(data)
        return "Задача снята с паузы."

    def check_current_stage(self) -> Optional[bool]:
        """Проверить условие текущего этапа через LLM.

        Возвращает:
        - None — проверка неприменима (нет задачи/этапов/пауза/завершено/нет
          последнего обмена);
        - True — условие выполнено (LLM ответил «да»);
        - False — условие не выполнено.
        """
        if not self.tasks.active_task:
            return None
        fsm = self.fsm()
        if fsm is None or fsm.is_empty() or fsm.paused or fsm.completed:
            return None
        stage = fsm.active_stage()
        if stage is None or not stage.condition:
            return None
        messages = self.short_term.get("messages", [])
        last_user = next(
            (m for m in reversed(messages) if m.get("role") == "user"), None
        )
        last_assistant = next(
            (m for m in reversed(messages) if m.get("role") == "assistant"), None
        )
        if last_user is None or last_assistant is None:
            return None
        prompt = (
            f"Вот условие завершения этапа: {stage.condition}. "
            f"Вот последний обмен: {last_user.get('content', '')} / "
            f"{last_assistant.get('content', '')}. "
            'Ответь строго "да" или "нет": выполнено ли условие?'
        )
        result = self.provider.chat(
            [
                {
                    "role": "system",
                    "content": 'Ты проверяешь условие. Отвечай строго "да" или "нет".',
                },
                {"role": "user", "content": prompt},
            ]
        )
        answer = (result.get("content") or "").strip().lower()
        if answer.startswith("да"):
            return True
        if answer.startswith("нет"):
            return False
        return False

    # ------------------------------------------------------------------- память
    def memory_show(self, layer: str) -> dict:
        if layer == "long":
            return self.store.load_long()
        if layer == "short":
            return self.short_term
        if layer == "working":
            if not self.tasks.active_task:
                raise MemoryError("Нет активной задачи — рабочая память недоступна.")
            return self.store.load_working(self.tasks.active_task) or {
                "task": self.tasks.active_task,
                "created_at": None,
                "records": [],
            }
        raise MemoryError(f"Неизвестный слой: {layer}")

    def memory_add(
        self,
        layer: str,
        content: str,
        record_type: Optional[str] = None,
        role: str = "user",
    ) -> dict:
        if layer == "long":
            if record_type not in LONG_TYPES:
                raise MemoryError("Для long укажите тип: decision | knowledge.")
            data = self.store.load_long()
            record = self.store.make_long_record(record_type, content)
            data["records"].append(record)
            self.store.save_long(data)
            return record

        if layer == "working":
            if not self.tasks.active_task:
                raise MemoryError("Нет активной задачи — добавить в рабочую память нельзя.")
            data = self.store.load_working(self.tasks.active_task) or self.store.create_working(
                self.tasks.active_task
            )
            record = self.store.make_working_record(content)
            data["records"].append(record)
            self.store.save_working(self.tasks.active_task, data)
            return record

        if layer == "short":
            record = self.store.make_message(role, content)
            self.short_term.setdefault("messages", []).append(record)
            if self.tasks.active_task:
                self.short_term["task"] = self.tasks.active_task
                self.store.save_short(self.short_term)
            return record

        raise MemoryError(f"Неизвестный слой: {layer}")

    def memory_del(self, layer: str, record_id: str) -> bool:
        if layer == "long":
            data = self.store.load_long()
            removed = self.store.remove_record(data["records"], record_id)
            if removed:
                self.store.save_long(data)
            return removed

        if layer == "working":
            if not self.tasks.active_task:
                raise MemoryError("Нет активной задачи.")
            data = self.store.load_working(self.tasks.active_task)
            if not data:
                return False
            removed = self.store.remove_record(data["records"], record_id)
            if removed:
                self.store.save_working(self.tasks.active_task, data)
            return removed

        if layer == "short":
            removed = self.store.remove_record(
                self.short_term.get("messages", []), record_id
            )
            if removed and self.tasks.active_task:
                self.store.save_short(self.short_term)
            return removed

        raise MemoryError(f"Неизвестный слой: {layer}")

    def memory_clear(self, layer: str) -> None:
        if layer == "long":
            self.store.save_long({"records": []})
            return

        if layer == "working":
            if not self.tasks.active_task:
                raise MemoryError("Нет активной задачи.")
            data = self.store.load_working(self.tasks.active_task) or {
                "task": self.tasks.active_task,
                "created_at": now_iso(),
                "records": [],
            }
            data["records"] = []
            self.store.save_working(self.tasks.active_task, data)
            return

        if layer == "short":
            self.short_term = {"task": self.tasks.active_task, "messages": []}
            if self.tasks.active_task:
                self.store.save_short(self.short_term)
            else:
                self.store.delete_short()
            return

        raise MemoryError(f"Неизвестный слой: {layer}")

    def memory_files(self) -> dict:
        active_profile = self.profiles.active_name()
        return {
            "long": str(self.store.long_path),
            "short": str(self.store.short_path),
            "working": (
                str(self.store.working_path(self.tasks.active_task))
                if self.tasks.active_task
                else None
            ),
            "profiles_dir": str(self.profiles.profiles_dir),
            "active_profile": (
                str(self.profiles.active_profile_path) if active_profile else None
            ),
        }

    def memory_usage(self, layer: str, on_off: str) -> bool:
        if layer not in self.usage:
            raise MemoryError(f"Неизвестный слой: {layer}")
        if on_off not in ("on", "off"):
            raise MemoryError("Укажите on или off.")
        self.usage[layer] = on_off == "on"
        return self.usage[layer]

    # ------------------------------------------------------------------ профили
    def profile_list(self) -> list[str]:
        return self.profiles.list_profiles()

    def profile_current(self) -> Optional[str]:
        return self.profiles.active_name()

    def profile_show(self, name: Optional[str] = None) -> dict:
        return self.profiles.load(name)

    def profile_new(self, name: str) -> dict:
        return self.profiles.create(name)

    def profile_switch(self, name: str) -> str:
        return self.profiles.switch(name)

    def profile_del(self, name: str) -> None:
        self.profiles.delete(name)

    def profile_set(self, name: str, field: str, value: str) -> dict:
        return self.profiles.set_field(name, field, value)

    def profile_unset(self, name: str, field: str) -> dict:
        return self.profiles.unset_field(name, field)

    def profile_add_note(self, name: str, text: str) -> dict:
        return self.profiles.add_note(name, text)

    def profile_del_note(self, name: str, index: int) -> dict:
        return self.profiles.del_note(name, index)



