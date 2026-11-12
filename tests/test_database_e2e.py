"""The compose database end to end: the local tier `scripts/e2e.py` runs.

Nothing else in the suite starts the stack, so nothing else can say whether
`docker-compose.yml`'s `db` comes up healthy, whether the `DATABASE_URL` in `.env`
agrees with the port compose actually published (the pairing `.env.example` calls the
first to break), whether `migrations/env.py` reaches the database, or whether the psycopg
driver round-trips a row. These tests need the Docker daemon, which no hosted runner has,
so they carry the `local` mark that `addopts` deselects everywhere but that script.

**The stack is left as it was found.** The `db` service is started if it was not running
and stopped again afterwards; one already up is left up, since it is somebody's.

**Nothing here skips** (`.claude/rules/local-e2e.md`): a missing daemon or `.env` fails
the test and names what is missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.local

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICE = "db"
# `docker compose up --wait` holds until the healthcheck passes: five 10 s retries, plus
# an image pull on a machine that has never run `postgres:18`.
UP_TIMEOUT_S = 300
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def read_env_file(path: Path) -> dict[str, str]:
    """`KEY=value` lines of a dotenv file, comments and blanks dropped, quotes stripped."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def compose(*args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    """`docker compose <args>` in the checkout root; a missing CLI fails the test."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail("the `docker` CLI is not on PATH: install or start Docker Desktop")
    return subprocess.run(  # noqa: S603 - fixed compose verbs written in this module
        [docker, "compose", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=NO_WINDOW,
    )


def checked(done: subprocess.CompletedProcess[str], what: str) -> str:
    if done.returncode != 0:
        pytest.fail(f"{what} exited {done.returncode}:\n{done.stdout}\n{done.stderr}")
    return done.stdout


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    """The `DATABASE_URL` this checkout points at, with the `db` service up behind it."""
    env_file = REPO_ROOT / ".env"
    if not env_file.is_file():
        pytest.fail(f"no {env_file.name} in {REPO_ROOT}: copy .env.example to .env")
    url = os.environ.get("DATABASE_URL") or read_env_file(env_file).get("DATABASE_URL", "")
    if not url:
        pytest.fail("DATABASE_URL is set neither in the environment nor in .env")
    checked(compose("version"), "docker compose version (is the Docker daemon running?)")
    running = checked(compose("ps", "--status", "running", "--services"), "docker compose ps")
    was_up = SERVICE in running.split()
    checked(
        compose("up", "-d", "--wait", SERVICE, timeout=UP_TIMEOUT_S),
        f"docker compose up -d --wait {SERVICE}",
    )
    try:
        yield url
    finally:
        if not was_up:
            compose("stop", SERVICE)


def test_database_url_matches_the_port_compose_published(database_url: str) -> None:
    published = checked(compose("port", SERVICE, "5432"), f"docker compose port {SERVICE}")
    port = published.strip().rsplit(":", 1)[-1]
    assert str(make_url(database_url).port) == port, (
        f"DATABASE_URL names port {make_url(database_url).port}, but compose published "
        f"{SERVICE} on {port}: DB_HOST_PORT and DATABASE_URL in .env disagree"
    )


def test_alembic_upgrade_reaches_the_database(database_url: str) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        creationflags=NO_WINDOW,
    )
    assert done.returncode == 0, f"alembic upgrade head failed:\n{done.stdout}\n{done.stderr}"


def test_a_row_round_trips_through_the_driver(database_url: str) -> None:
    marker = uuid.uuid4().hex
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("CREATE TEMPORARY TABLE e2e_probe (marker text NOT NULL)"))
            connection.execute(text("INSERT INTO e2e_probe VALUES (:m)"), {"m": marker})
            read = connection.execute(text("SELECT marker FROM e2e_probe")).scalar_one()
            version = connection.execute(text("SHOW server_version")).scalar_one()
    finally:
        engine.dispose()
    assert read == marker
    # docker-compose.yml pins `postgres:18`; a different major means the URL reached
    # some other server than this checkout's stack.
    assert str(version).split(".")[0] == "18", f"expected the stack's Postgres 18, got {version}"
