"""The replacement taskbar.

No Windows setting can redraw the taskbar or put a labelled Start button on it, so this
runs RetroBar (Apache-2.0, https://github.com/dremin/RetroBar), an independent project
that replaces the taskbar outright. It is fetched on demand rather than bundled, and its
.NET runtime is unpacked into Skinamp's own data folder: installing .NET properly would
need an admin prompt and could not be undone.

Both downloads are pinned to a version and a hash. Changing a version means changing the
hash in the same commit, which is the point.
"""

import hashlib
import platform
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from skinamp.effects import Effect, KeepTaskbarMode, SetRegistry
from skinamp.paths import AppPaths
from skinamp.system import taskbar
from skinamp.system.api import Refresh, RegValue

CHUNK_BYTES = 1 << 20
DOWNLOAD_TIMEOUT_SECONDS = 60
RETROBAR_MEMBER = "64-bit/RetroBar.exe"


@dataclass(frozen=True)
class Download:
    url: str
    algorithm: str
    digest: str


# The digests below are the publishers' hashes of public archives, not secrets; every line
# of one carries the pragma because detect-secrets reads each line on its own.
RETROBAR = Download(
    f"https://github.com/dremin/RetroBar/releases/download/v{taskbar.RETROBAR_VERSION}/"
    "RetroBar.Portable.zip",
    "sha256",
    "6ab0d0972535e5efedc13c83403b52883edb06881d2d6aa18bf8af379bc7a128",  # pragma: allowlist secret
)
# Two archives, one tree: the desktop zip holds only `shared/Microsoft.WindowsDesktop.App`.
# The host that finds it (`host/fxr`) and the base runtime are in the other.
DOTNET = (
    Download(
        f"https://builds.dotnet.microsoft.com/dotnet/Runtime/{taskbar.DOTNET_VERSION}/"
        f"dotnet-runtime-{taskbar.DOTNET_VERSION}-win-x64.zip",
        "sha512",
        "a176095f1db69b42c81acc60940744078d6bf2d2ac643e418342aa9c81889f4bd13e42f4621b131f9e77e4"  # pragma: allowlist secret
        "bc781ad46e375956219df9a4f979031d2a5a8d93cd",  # pragma: allowlist secret
    ),
    Download(
        f"https://builds.dotnet.microsoft.com/dotnet/WindowsDesktop/{taskbar.DOTNET_VERSION}/"
        f"windowsdesktop-runtime-{taskbar.DOTNET_VERSION}-win-x64.zip",
        "sha512",
        "3214913702264452ac4b283b6fb2f6c14ab748cea36c7561608245c4a7d8cc10436a160032038865d039a0"  # pragma: allowlist secret
        "16eab4975f65f1ae906de7615953fbec760f764ac4",  # pragma: allowlist secret
    ),
)


class DownloadError(Exception):
    """A pinned download failed or did not match its hash."""


def fetch(download: Download, destination: Path) -> None:
    """Download to `destination`, deleting it again unless the hash matches."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.new(download.algorithm)
    try:
        with (
            urllib.request.urlopen(download.url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response,
            destination.open("wb") as output,
        ):
            while chunk := response.read(CHUNK_BYTES):
                digest.update(chunk)
                output.write(chunk)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise DownloadError(f"Could not download {download.url}: {exc}") from exc
    if digest.hexdigest().lower() != download.digest.lower():
        destination.unlink(missing_ok=True)
        raise DownloadError(f"{download.url} did not match its pinned {download.algorithm}")


def install_retrobar(paths: AppPaths) -> None:
    exe = taskbar.retrobar_exe(paths)
    if exe.exists():
        return
    archive = paths.components / "retrobar.zip"
    fetch(RETROBAR, archive)
    exe.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle, bundle.open(RETROBAR_MEMBER) as source:
        with exe.open("wb") as target:
            shutil.copyfileobj(source, target)
    archive.unlink()


def install_dotnet(paths: AppPaths) -> None:
    root = taskbar.dotnet_root(paths)
    if root.exists():
        return
    archive = paths.components / "dotnet.zip"
    partial = root.parent / f"{root.name}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    for download in DOTNET:
        fetch(download, archive)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(partial)
        archive.unlink()
    partial.rename(root)


def prepare(paths: AppPaths) -> None:
    settings = taskbar.retrobar_settings_dir()
    paths.components.mkdir(parents=True, exist_ok=True)
    if not settings.exists():
        # RetroBar creates this folder on first run. Only then is it ours to remove.
        (paths.components / taskbar.SETTINGS_MARKER).touch()
    install_dotnet(paths)
    install_retrobar(paths)


def unsupported_reason(machine: str | None = None) -> str | None:
    architecture = (machine or platform.machine()).lower()
    if architecture in ("amd64", "x86_64"):
        return None
    return f"The retro taskbar needs a 64-bit Intel or AMD PC, not {architecture}"


def effects() -> list[Effect]:
    command = RegValue("sz", taskbar.launch_command())
    return [
        KeepTaskbarMode(),
        SetRegistry(taskbar.RUN_KEY, taskbar.RUN_VALUE, command, Refresh.TASKBAR),
    ]
