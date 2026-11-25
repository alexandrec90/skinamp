#!/usr/bin/env python3
"""Build the Windows executable, and with `--pack` the installer and update feed.

    python scripts/build-release.py                    # dist/Skinamp/Skinamp.exe
    python scripts/build-release.py --pack --version 1.2.3

`--pack` needs Velopack's `vpk` tool, which is a .NET tool, so it normally runs in
`.github/workflows/release.yml`. On failure the tool's output goes to
`logs/build-failure.log` and the terminal gets one status line.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "Skinamp"
ENTRY = ROOT / "skinamp" / "__main__.py"
WEB_DATA = ROOT / "skinamp" / "gui" / "web"
FAILURE_LOG = ROOT / "logs" / "build-failure.log"
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+")


def version_from_ref(ref: str) -> str:
    """`refs/tags/v1.2.3` or `v1.2.3` as `1.2.3`, refusing anything else."""
    version = ref.rsplit("/", 1)[-1].removeprefix("v")
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"{ref!r} is not a release tag like v1.2.3")
    return version


def pyinstaller_command(python: str = sys.executable) -> list[str]:
    # --onedir, not --onefile: Velopack packages and diffs a folder of files.
    # --windowed: double-clicking the app must not open a console.
    options: dict[str, str | Path] = {
        "--name": APP_NAME,
        "--distpath": ROOT / "dist",
        "--workpath": ROOT / "build",
        "--specpath": ROOT / "build",
        "--add-data": f"{WEB_DATA};skinamp/gui/web",
        "--collect-all": "velopack",
    }
    return [
        python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        *_flatten(options),
        "--hidden-import=win32com.shell.shell",
        "--hidden-import=win32com.shell.shellcon",
        str(ENTRY),
    ]


def vpk_command(version: str) -> list[str]:
    options: dict[str, str | Path] = {
        "--packId": APP_NAME,
        "--packVersion": version,
        "--packDir": ROOT / "dist" / APP_NAME,
        "--mainExe": f"{APP_NAME}.exe",
        "--outputDir": ROOT / "releases",
    }
    return ["vpk", "pack", *_flatten(options)]


def _flatten(options: dict[str, str | Path]) -> list[str]:
    return [part for option, value in options.items() for part in (option, str(value))]


def run(command: list[str]) -> None:
    """Run a build step, moving any failure's output into the artifact file."""
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return
    FAILURE_LOG.parent.mkdir(exist_ok=True)
    FAILURE_LOG.write_text(
        f"$ {' '.join(command)}\n\n{result.stdout}\n{result.stderr}", encoding="utf-8"
    )
    raise SystemExit(f"{command[0]} failed: see {FAILURE_LOG}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", action="store_true", help="also build the installer")
    parser.add_argument("--version", help="release version, or a tag ref such as v1.2.3")
    args = parser.parse_args()
    if args.pack and not args.version:
        parser.error("--pack needs --version")
    FAILURE_LOG.unlink(missing_ok=True)
    run(pyinstaller_command())
    if args.pack:
        run(vpk_command(version_from_ref(args.version)))
    print(f"Built dist/{APP_NAME}/{APP_NAME}.exe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
