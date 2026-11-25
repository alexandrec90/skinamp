"""The command line, and with it a way back that needs no window.

`skinamp revert` is the fallback for a desktop too broken to use: it runs from any
terminal, with no web view and no GUI toolkit in the path.
"""

import argparse
import contextlib
import logging
from collections.abc import Sequence
from pathlib import Path

from skinamp import elevated
from skinamp.engine import ApplyFailedError, Engine, RevertIncompleteError
from skinamp.journal import JournalError
from skinamp.paths import AppPaths, default_paths
from skinamp.system import taskbar
from skinamp.system.factory import get_system, run_request
from skinamp.themes import get_theme
from skinamp.updater import Updater

EXIT_OK = 0
EXIT_FAILED = 1


def build_engine(paths: AppPaths) -> Engine:
    return Engine(get_system(paths), paths)


def configure_logging(paths: AppPaths) -> None:
    paths.log.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=paths.log,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skinamp", description="Theme Windows and your apps.")
    commands = parser.add_subparsers(dest="command")
    for name, summary in (
        ("plan", "list what a theme would change, changing nothing"),
        ("apply", "apply a theme"),
    ):
        command = commands.add_parser(name, help=summary)
        command.add_argument("theme")
        command.add_argument("--only", help="comma-separated components, e.g. cursors,icons")
    commands.add_parser("revert", help="undo every change Skinamp made")
    commands.add_parser("status", help="show what is applied")
    commands.add_parser("taskbar-start", help="start the theme's taskbar (run at sign-in)")
    helper = commands.add_parser("elevated-run", help="internal: the admin step of apply and undo")
    helper.add_argument("request", type=Path)
    return parser


def run_elevated_request(request: Path) -> int:
    """Runs as admin, so it writes nothing to the user's log: the parent reports failure."""
    try:
        run_request(request)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # The folder is gone if Skinamp gave up on the prompt; then nobody is reading.
        with contextlib.suppress(OSError):
            request.with_name(elevated.ERROR_FILE).write_text(str(exc), encoding="utf-8")
        return EXIT_FAILED
    return EXIT_OK


def _selection(only: str | None) -> list[str] | None:
    return [part.strip() for part in only.split(",")] if only else None


def _plan(engine: Engine, theme: str, only: str | None) -> int:
    for item in engine.plan(get_theme(theme), _selection(only)):
        print(f"{item.component:10} {item.change}")
    return EXIT_OK


def _apply(engine: Engine, theme: str, only: str | None) -> int:
    try:
        result = engine.apply(get_theme(theme), _selection(only))
    except ApplyFailedError as exc:
        print(f"Failed and rolled back: {exc}")
        for reason in exc.rollback.pending:
            print(f"Still in place: {reason}")
        return EXIT_FAILED
    except RevertIncompleteError as exc:
        print(f"The previous theme is not fully undone: {exc}")
        return EXIT_FAILED
    print(f"{result.theme}: {result.changes} changes ({', '.join(result.applied)})")
    for skipped in result.skipped:
        print(f"Skipped {skipped.component}: {skipped.reason}")
    for warning in result.warnings:
        print(warning)
    return EXIT_OK


def _revert(engine: Engine) -> int:
    result = engine.revert()
    print(f"Undid {result.restored} changes.")
    for reason in sorted(set(result.pending)):
        print(f"Still in place: {reason}")
    for warning in result.warnings:
        print(warning)
    return EXIT_OK if result.complete else EXIT_FAILED


def _status(engine: Engine) -> int:
    status = engine.status()
    print(status.error or f"{status.state}: {status.theme or 'no theme'}, {status.changes} changes")
    return EXIT_FAILED if status.error else EXIT_OK


def _gui(engine: Engine) -> int:
    from skinamp.gui import app

    app.run(engine, Updater())
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "elevated-run":
        return run_elevated_request(args.request)
    paths = default_paths()
    configure_logging(paths)
    if args.command == "taskbar-start":
        taskbar.start(paths)
        return EXIT_OK
    engine = build_engine(paths)
    try:
        match args.command:
            case "plan":
                return _plan(engine, args.theme, args.only)
            case "apply":
                return _apply(engine, args.theme, args.only)
            case "revert":
                return _revert(engine)
            case "status":
                return _status(engine)
            case _:
                return _gui(engine)
    except (JournalError, ValueError) as exc:
        print(exc)
        return EXIT_FAILED
