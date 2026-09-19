"""CLI-интерфейс агента с многослойной памятью.

Запуск:
    python cli.py [--config path/to/config.json] [--agent <name>] [--prompt "..."]
"""
from __future__ import annotations

import argparse
from typing import Optional

from agent.commands import format_debug, format_metrics, process_command, run_stage_check
from agent.config import Config
from agent.errors import AgentError
from agent.manager import AgentManager

try:
    from rich.console import Console

    _console = Console()
    HAS_RICH = True
except ImportError:  # rich опционален
    _console = None
    HAS_RICH = False


def _print(text: str) -> None:
    if HAS_RICH:
        _console.print(text)
    else:
        print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Агент с явной многослойной моделью памяти (profile/long/working/short)."
    )
    parser.add_argument("--config", default="config.json", help="путь к config.json")
    parser.add_argument(
        "--agent", default=None, help="активный агент (имя из config.json)"
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="одноразовый режим: отправить запрос и выйти",
    )
    return parser


def run_once(manager: AgentManager, prompt: str) -> int:
    """Одноразовый режим: один запрос — один ответ."""
    agent = manager.active()
    try:
        reply = agent.ask(prompt)
    except AgentError as exc:
        _print(f"Ошибка: {exc}")
        return 1
    _print(reply)
    if agent.debug_enabled:
        _print(format_debug(agent))
    if agent.metrics_enabled:
        _print(format_metrics(agent))
    return 0


def _prompt_save(agent, reply: str) -> None:
    """CLI-вариант A: спросить, куда сохранить ответ."""
    try:
        choice = input("Сохранить куда? [short/working/long/none]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return

    if choice in ("", "none"):
        return
    if choice == "short":
        _print("Ответ уже сохранён в краткосрочной памяти.")
        return
    if choice == "working":
        try:
            agent.memory_add("working", reply)
            _print("Ответ сохранён в рабочую память.")
        except AgentError as exc:
            _print(f"Ошибка: {exc}")
        return
    if choice == "long":
        try:
            record_type = input("Тип [decision/knowledge]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if record_type not in ("decision", "knowledge"):
            _print("Неверный тип, сохранение отменено.")
            return
        agent.memory_add("long", reply, record_type=record_type)
        _print(f"Ответ сохранён в long ({record_type}).")
        return
    _print("Неизвестный вариант, сохранение отменено.")


def _maybe_advance_stage(agent) -> None:
    """Автоматическая проверка условия текущего этапа после ответа агента."""
    text = run_stage_check(agent, verbose=False)
    if text:
        _print(text)


def _handle_message(manager: AgentManager, agent, raw: str) -> None:
    try:
        reply = agent.ask(raw)
    except AgentError as exc:
        _print(f"Ошибка: {exc}")
        return

    _print(reply)
    if agent.debug_enabled:
        _print(format_debug(agent))
    if agent.metrics_enabled:
        _print(format_metrics(agent))
    if agent.prompt_save:
        _prompt_save(agent, reply)

    _maybe_advance_stage(agent)


def run_interactive(manager: AgentManager) -> None:
    _print("Агент с многослойной памятью. Введите /help для списка команд, /exit для выхода.")
    while True:
        agent = manager.active()
        try:
            raw = input(f"[{agent.name}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            _print("")
            break

        if not raw:
            continue

        if raw.startswith("/"):
            result = process_command(manager, raw)
            if result.text:
                _print(result.text)
            if result.exit_requested:
                break
        else:
            _handle_message(manager, agent, raw)


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = Config.load(args.config)
        manager = AgentManager(config)
        if args.agent:
            manager.switch(args.agent)
    except AgentError as exc:
        _print(f"Ошибка: {exc}")
        return 1

    if args.prompt is not None:
        return run_once(manager, args.prompt)

    run_interactive(manager)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
