"""Entry point of the executable and of `python -m skinamp`."""

import sys

from skinamp import cli
from skinamp.paths import default_paths


def undo_before_uninstall(_version: str) -> None:
    """Uninstalling must not strand the user on a theme with nothing left to undo it."""
    cli.build_engine(default_paths()).revert()


def run_install_hooks() -> None:
    """Hand over to Velopack first: it may have launched us only to run a hook.

    Only the packaged executable is installed, so a source run has nothing to hand over.
    """
    if not getattr(sys, "frozen", False):
        return
    import velopack

    velopack.App().on_before_uninstall_fast_callback(undo_before_uninstall).run()


def main() -> int:
    run_install_hooks()
    return cli.main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
