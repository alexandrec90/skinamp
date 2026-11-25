import pytest

from skinamp.paths import AppPaths
from tests.fakes import FakeSystem


@pytest.fixture
def system() -> FakeSystem:
    return FakeSystem()


@pytest.fixture
def paths(tmp_path) -> AppPaths:
    return AppPaths(tmp_path / "data")
