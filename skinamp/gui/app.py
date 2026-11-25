"""The window, and the bridge its JavaScript calls.

Bridge methods return plain dicts and report failure as data, because an exception
crossing into the page arrives as an opaque rejection the user cannot act on.
"""

import base64
import io
import logging
import threading
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from skinamp import __version__
from skinamp.engine import ApplyFailedError, Engine, RevertIncompleteError
from skinamp.effects import Json, JsonObject
from skinamp.journal import JournalError
from skinamp.themes import THEMES, get_theme
from skinamp.updater import Updater, UpdateStatus

logger = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).parent / "web"
WINDOW_SIZE = (720, 760)
PREVIEW_SIZE = 64


def data_uri(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.resize((PREVIEW_SIZE, PREVIEW_SIZE), Image.Resampling.NEAREST).save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def describe_theme(theme_id: str) -> JsonObject:
    theme = THEMES[theme_id]
    return {
        "id": theme.id,
        "name": theme.name,
        "description": theme.description,
        "preview": {name: data_uri(image) for name, image in theme.preview().items()},
        "components": [
            {
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "needs_admin": c.needs_admin,
            }
            for c in theme.components
        ],
    }


class Api:
    """Exposed to the page. Public methods only: pywebview publishes every one of them."""

    def __init__(self, engine: Engine, updater: Updater) -> None:
        self._engine = engine
        self._updater = updater
        self._lock = threading.Lock()
        self._update = UpdateStatus("unmanaged")

    def get_state(self) -> JsonObject:
        themes: list[Json] = [describe_theme(theme_id) for theme_id in THEMES]
        return {
            "version": __version__,
            "themes": themes,
            "status": self.get_status(),
            "update": self.get_update(),
        }

    def get_status(self) -> JsonObject:
        return dict(asdict(self._engine.status()))

    def get_update(self) -> JsonObject:
        return dict(asdict(self._update))

    def check_updates(self) -> JsonObject:
        self._update = self._updater.check_and_download()
        return self.get_update()

    def restart_to_update(self) -> None:
        self._updater.restart_into_update()

    def apply(self, theme_id: str, components: list[str]) -> JsonObject:
        with self._lock:
            try:
                result = self._engine.apply(get_theme(theme_id), components)
            except ApplyFailedError as exc:
                rollback = exc.rollback
                return {
                    "ok": False,
                    "error": str(exc),
                    "rolled_back": rollback.complete,
                    "pending": list(rollback.pending),
                }
            except (RevertIncompleteError, JournalError, ValueError) as exc:
                logger.exception("apply refused")
                return {"ok": False, "error": str(exc), "rolled_back": True, "pending": []}
        return {"ok": True, **asdict(result)}

    def revert(self) -> JsonObject:
        with self._lock:
            try:
                result = self._engine.revert()
            except JournalError as exc:
                return {"ok": False, "error": str(exc), "pending": []}
        return {"ok": result.complete, **asdict(result)}


def run(engine: Engine, updater: Updater) -> None:
    import webview

    api = Api(engine, updater)
    width, height = WINDOW_SIZE
    webview.create_window(
        "Skinamp", str(WEB_ROOT / "index.html"), js_api=api, width=width, height=height
    )
    webview.start()
