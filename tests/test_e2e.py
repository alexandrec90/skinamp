"""`scripts/e2e.py`: the local tier's runner and the contract devkit's nightly job reads.

These run in the ordinary suite: the runner is faked, so no desktop and no `local` test.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_e2e() -> ModuleType:
    path = REPO_ROOT / "scripts" / "e2e.py"
    spec = importlib.util.spec_from_file_location("skinamp_e2e_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def e2e(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    script = load_e2e()
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(script, "REPORT", tmp_path / "logs" / "e2e-junit.xml")
    return script


def junit(*cases: str) -> str:
    return f'<?xml version="1.0"?><testsuites><testsuite>{"".join(cases)}</testsuite></testsuites>'


def passed(name: str = "test_ok") -> str:
    return f'<testcase classname="tests.test_desktop_e2e" name="{name}"/>'


def ended(tag: str, name: str, message: str) -> str:
    return (
        f'<testcase classname="tests.test_desktop_e2e" name="{name}">'
        f'<{tag} message="{message}">detail</{tag}></testcase>'
    )


def run_e2e(
    script: ModuleType,
    report: str | None,
    code: int = 0,
    env: dict[str, str] | None = None,
    argv: list[str] | None = None,
) -> tuple[int, list[list[str]]]:
    """Run `main` with a fake pytest that writes `report` and exits `code`."""
    calls: list[list[str]] = []

    def runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if report is not None:
            script.REPORT.write_text(report, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, code, stdout="pytest output\n", stderr="")

    return script.main(argv or [], runner=runner, env=env or {}), calls


# --- pure helpers ------------------------------------------------------------


def test_pytest_argv_selects_the_tier_and_writes_the_report() -> None:
    argv = load_e2e().pytest_argv("py", Path("report.xml"))
    assert argv[:4] == ["py", "-m", "pytest", "tests"]
    assert argv[argv.index("-m", 3) + 1] == "local"
    assert "--junitxml=report.xml" in argv
    assert "no:cacheprovider" in argv


def test_named_ids_replace_the_tests_directory() -> None:
    argv = load_e2e().pytest_argv("py", Path("r.xml"), ["tests/test_x.py::test_y"])
    assert "tests" not in argv
    assert argv[3] == "tests/test_x.py::test_y"
    assert "local" in argv


@pytest.mark.parametrize(
    ("classname", "name", "ident"),
    [
        ("tests.test_desktop_e2e", "test_a", "tests/test_desktop_e2e.py::test_a"),
        ("tests.test_x.TestY", "test_z", "tests/test_x.py::TestY::test_z"),
        ("", "tests.test_broken", "tests.test_broken"),
        ("tests.test_x", "test_p[a b]", "tests/test_x.py::test_p[a_b]"),
    ],
)
def test_pytest_id_names_a_case_as_pytests_summary_does(
    classname: str, name: str, ident: str
) -> None:
    assert load_e2e().pytest_id(classname, name) == ident


def test_venv_python_prefers_the_checkouts_venv(tmp_path: Path) -> None:
    e2e = load_e2e()
    assert e2e.venv_python(tmp_path, "fallback") == "fallback"
    interpreter = tmp_path / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("", encoding="utf-8")
    assert e2e.venv_python(tmp_path, "fallback") == str(interpreter)


def test_an_unreadable_report_is_no_cases(tmp_path: Path) -> None:
    e2e = load_e2e()
    assert e2e.cases(tmp_path / "absent.xml") == []
    broken = tmp_path / "broken.xml"
    broken.write_text("<testsuites><testcase", encoding="utf-8")
    assert e2e.cases(broken) == []


def test_pytests_own_failure_code_survives_a_run_that_executed_nothing() -> None:
    e2e = load_e2e()
    assert e2e.verdict(4, [], strict=False)[0] == 4
    skipped = e2e.Case("tests/test_x.py::test_y", e2e.SKIPPED, "no stack")
    assert e2e.verdict(2, [skipped], strict=True)[0] == 2


def test_a_skip_without_a_message_still_names_a_reason() -> None:
    e2e = load_e2e()
    _, lines = e2e.verdict(0, [e2e.Case("t::a", e2e.PASSED), e2e.Case("t::b", e2e.SKIPPED)], False)
    assert lines == ["SKIPPED t::b - skipped: no reason given"]


# --- main --------------------------------------------------------------------


def test_a_green_run_exits_zero_and_prints_no_failure(
    e2e: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    code, calls = run_e2e(e2e, junit(passed()))
    out = capsys.readouterr().out
    assert code == 0
    assert "FAILED" not in out
    assert "pytest output" in out
    assert "e2e: report in logs/e2e-junit.xml" in out
    assert len(calls) == 1


def test_a_failure_exits_with_pytests_code_and_names_the_test(
    e2e: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = run_e2e(e2e, junit(passed(), ended("failure", "test_bad", "boom")), code=1)
    assert code == 1
    assert "FAILED tests/test_desktop_e2e.py::test_bad - boom" in capsys.readouterr().out


def test_a_fixture_error_is_printed_as_failed(
    e2e: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    run_e2e(e2e, junit(ended("error", "test_down", "daemon not running")), code=1)
    assert "FAILED tests/test_desktop_e2e.py::test_down - daemon" in capsys.readouterr().out


def test_a_skip_is_listed_by_hand_and_fails_under_the_scheduler(
    e2e: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    report = junit(passed(), ended("skipped", "test_s", "no docker"))
    assert run_e2e(e2e, report)[0] == 0
    assert "SKIPPED tests/test_desktop_e2e.py::test_s - skipped: no docker" in (
        capsys.readouterr().out
    )
    assert run_e2e(e2e, report, env={e2e.ENV_FLAG: "1"})[0] == 1
    out = capsys.readouterr().out
    assert "FAILED tests/test_desktop_e2e.py::test_s - skipped: no docker" in out
    assert "skipped under the scheduled run" in out


@pytest.mark.parametrize("report", [None, junit(), junit(ended("skipped", "test_s", "x"))])
def test_a_run_that_executed_nothing_is_red_even_by_hand(
    e2e: ModuleType, capsys: pytest.CaptureFixture[str], report: str | None
) -> None:
    assert run_e2e(e2e, report, code=0)[0] == 1
    assert "no local test executed" in capsys.readouterr().out


def test_a_stale_report_cannot_answer_for_this_run(e2e: ModuleType) -> None:
    e2e.REPORT.parent.mkdir(parents=True)
    e2e.REPORT.write_text(junit(passed()), encoding="utf-8")
    assert run_e2e(e2e, None, code=0)[0] == 1


def test_named_ids_reach_pytest(e2e: ModuleType) -> None:
    _, calls = run_e2e(e2e, junit(passed()), argv=["tests/test_desktop_e2e.py::test_ok"])
    assert "tests/test_desktop_e2e.py::test_ok" in calls[0]


def test_output_a_cp1252_console_cannot_encode_is_escaped(
    e2e: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    run_e2e(e2e, junit(ended("failure", "test_u", "bad \N{RIGHTWARDS ARROW} arrow")), code=1)
    assert "bad \\u2192 arrow" in capsys.readouterr().out
