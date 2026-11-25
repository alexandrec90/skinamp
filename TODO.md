# TODO — Skinamp

## Setup

- [ ] Fill in `.env` from `.env.example` (it is gitignored; nothing works without it)
- [ ] Confirm `python scripts/sync-devkit.py --list` shows a stamped `DEVKIT_VERSION`
- [ ] Set `DEVKIT_DIR` in CI so the drift check actually gates — a
      `--check` that prints "nothing to do (skipping)" is checking nothing
      (once `DEVKIT_VERSION` is stamped it fails instead of skipping; to check
      drift on a machine with no devkit clone, `pre-commit run devkit-drift`)

## Before the first release

- [ ] Check Spotlight's "Learn about this image" desktop icon survives a cycle: it was gone
      once Spotlight had been off, and had not returned after an Explorer restart
- [ ] Push a test tag and confirm the release workflow publishes, since `vpk` has never run
- [ ] Install that release, publish a newer one, and confirm the update installs
- [ ] Buy a code-signing certificate, or accept the SmartScreen warning; the UAC prompt
      says "Unknown publisher" until then

## Later

- [ ] Sounds: per-user schemes under `AppEvents`, synthesised rather than copied
- [ ] Publish a Chrome Web Store theme, the only one-click route to a textured one
- [ ] More apps: VS Code, Windows Terminal and Firefox all keep themes in plain files

## Archive

- [x] Replace the placeholder in `skinamp/` with something that does the job
- [x] Delete `tests/test_smoke.py` once real tests exist
- [x] Remove the unused template stack (Docker, Postgres, Alembic)
- [x] One apply or undo at a time: a second copy is refused while the journal is held
- [x] Give up on an admin prompt nobody answers in 2 minutes; a late "Yes" then does nothing
- [x] Full Retro apply and undo on the final build: matches the snapshot, Spotlight kept
