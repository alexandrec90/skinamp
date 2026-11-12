# Skinamp

Orchestrate theming on windows and applications.

## Tech Stack

| Layer | Choice |
| --- | --- |
| Language | Python 3.12 |
| Window | pywebview (WebView2) over plain HTML and JavaScript in `skinamp/gui/web/` |
| Packaging | PyInstaller `--onedir`, Velopack |
| Updates | Velopack, from GitHub Releases |
| State | The JSON undo journal in `%LOCALAPPDATA%\SkinampData`; no database |
| Tests | pytest |
| Lint | ruff |

Skinamp is a Windows desktop app with no server, no database and no containers.

## Environment Variables

See `.env.example` for every variable. `.env` is gitignored and holds this
checkout's ports and credentials.

## Tooling

### Scripts and the vendored harness

Both are covered by **`.claude/rules/engineering.md`** — script conventions (pure
importable functions, stdlib-only hooks, tests in the same change), the failure-artifact
rule, and how the `.devkit.toml` seam works. That file is vendored from
[devkit](https://github.com/alexandrec90/devkit) and drift-gated, so it is the
authority; this file does not repeat it.

### VS Code tasks

- Use `"type": "process"` so VS Code monitors the process directly — that is what
  makes the spinner stop and the exit-code icon appear reliably.
- Set `"close": false` in `presentation` so the terminal stays open for review.
- **Wrap with `notify-wrap.py`** for the completion toast; never call `notify.py`
  from inside a script. Notifications are a task-layer concern only.
- Label convention: `"Domain: Title Case Action"`, and **every task carries a
  `detail`** — that is the second line in the quick-pick, and the only place a
  one-click action can state its cost or blast radius.

### Failure artifacts (fix from a file, not from the terminal)

Any task or script whose failures an agent is expected to act on must persist the
failure to a **parseable artifact file** under `logs/`. Never rely on streamed
terminal output — it scrolls away and buries the signal. Keep the terminal to a
status line plus the artifact path; put everything needed to diagnose in the file.
Write the artifact on failure too, not just success, and overwrite per run.

## Testing

**`.claude/rules/engineering.md`** is the authority: tests ship in the same commit,
every testable unit of logic is covered, regression test first, targeted runs locally
and full runs in CI.

Add this project's specifics *below* — fixtures, isolation rules, markers, what to mock
and where — but do not restate the policy above. It is vendored and drift-gated; a copy
here is a fork that will disagree with it the first time either is edited.

- **Mock at one seam: `System`.** `tests/fakes.py` is an in-memory `System`, so everything
  above that boundary runs for real on the Linux gate.
- **`tests/test_win32.py` is the only CI test of real Windows calls.** It runs in the gate's
  Windows job and must never change how the machine looks: registry tests use the scratch
  key from `key_prefix`, everything else only reads.
- **Never run `apply` or `revert` against the real desktop from a test or a session
  without asking.** `python -m skinamp plan retro` is read-only and safe.
- **`local` marker:** a test that needs this workstation's signed-in desktop carries
  `pytest.mark.local`; `addopts` deselects it everywhere and `python scripts/e2e.py` runs
  exactly that tier (`.claude/rules/local-e2e.md`). `tests/test_desktop_e2e.py` is its
  end-to-end test: it runs `python -m skinamp plan retro` read-only, with its data folders
  redirected to a temporary one.

## Guardrails

Baseline guardrails — including the instruction-file feedback loop (**never silently
work around a bad instruction**) — are in `.claude/rules/engineering.md`. Rules for
writing skills and rules themselves are in `.claude/rules/authoring.md`. Cross-reference
this project's own scoped rules here, one line each.

- **Undo is the product.** A change that is not an `Effect` in the journal cannot be undone,
  so nothing changes the machine any other way.
- **The journal format and every shipped effect `kind` are forever.** An update can land
  while a theme is applied, so later releases must keep restoring what earlier ones wrote.
  The golden tests in `tests/test_journal.py` and `tests/test_effects.py` hold this.
- **Skinamp itself never runs elevated.** An elevated process can be another user, with a
  different HKCU. What truly needs admin is a `machine_*` call on `System`, queued for the
  one UAC prompt `run_elevated` brings up, and limited by the allow-list in
  `skinamp/elevated.py`. Say so to the user with `Component.needs_admin`.
- **Test on a real desktop before calling it working.** The fake cannot show what Windows
  ignores. Applying Retro live found per-user `Shell Icons` doing nothing, animation
  settings reading as off over RDP, a cursor reload that always failed, and Windows turning
  Spotlight back off in the middle of an undo. Compare against
  an independent snapshot, not the journal: the journal only knows what it recorded.
- **Original art only.** Never bundle cursors, icons or fonts from any operating system.
