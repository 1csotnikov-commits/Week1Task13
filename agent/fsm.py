"""Конечный автомат (FSM) состояния задачи.

Модель описывает «этапы задачи» (они же «текущий шаг» / «ожидаемое действие» —
это один уровень). Внутри одного этапа отдельного «шага» нет.

Этап состоит из:
- name — короткое имя (используется в командах);
- description — что должно происходить на этапе (текст);
- condition — условие завершения этапа на естественном языке (оценивает LLM);
- expected_action — что ожидается от пользователя/агента на этом этапе (текст);
- status — pending | active | completed;
- order — порядковый номер.

Состояние автомата хранится в поле ``fsm`` файла ``working_<task_name>.json``.
Если этапов нет — поле ``fsm`` отсутствует или равно null, и задача работает как
обычный диалог с рабочей памятью.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

STAGE_STATUSES = ("pending", "active", "completed")


@dataclass
class Stage:
    """Один этап задачи."""

    name: str
    description: str = ""
    condition: str = ""
    expected_action: str = ""
    status: str = "pending"
    order: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "Stage":
        return cls(
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            condition=str(data.get("condition") or ""),
            expected_action=str(data.get("expected_action") or ""),
            status=str(data.get("status") or "pending"),
            order=int(data.get("order") or 0),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "condition": self.condition,
            "expected_action": self.expected_action,
            "status": self.status,
            "order": self.order,
        }


@dataclass
class Fsm:
    """Состояние конечного автомата задачи."""

    stages: list[Stage] = field(default_factory=list)
    current_stage: Optional[str] = None
    paused: bool = False
    completed: bool = False

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["Fsm"]:
        if not data:
            return None
        stages = [Stage.from_dict(s) for s in data.get("stages", [])]
        return cls(
            stages=stages,
            current_stage=data.get("current_stage"),
            paused=bool(data.get("paused", False)),
            completed=bool(data.get("completed", False)),
        )

    def to_dict(self) -> dict:
        return {
            "stages": [s.to_dict() for s in self.stages],
            "current_stage": self.current_stage,
            "paused": self.paused,
            "completed": self.completed,
        }

    def is_empty(self) -> bool:
        return not self.stages

    def ordered_stages(self) -> list[Stage]:
        return sorted(self.stages, key=lambda s: s.order)

    def stage_by_name(self, name: str) -> Optional[Stage]:
        for s in self.stages:
            if s.name == name:
                return s
        return None

    def active_stage(self) -> Optional[Stage]:
        return self.stage_by_name(self.current_stage) if self.current_stage else None

    def next_stage(self) -> Optional[Stage]:
        ordered = self.ordered_stages()
        for i, s in enumerate(ordered):
            if s.name == self.current_stage and i + 1 < len(ordered):
                return ordered[i + 1]
        return None

    def prev_stage(self) -> Optional[Stage]:
        ordered = self.ordered_stages()
        for i, s in enumerate(ordered):
            if s.name == self.current_stage and i - 1 >= 0:
                return ordered[i - 1]
        return None
