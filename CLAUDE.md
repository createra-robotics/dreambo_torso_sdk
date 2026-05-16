# Claude Code Instructions

Read `AGENTS.md` in this directory for full instructions on developing Dreambo robot torso applications.

## Related local repositories

Several of this SDK's runtime dependencies are developed as sibling repositories on this machine. When a task requires a change that cannot be made within this repo alone (new API surface, bug in the kinematics solver, missing motor primitive, etc.), edit the appropriate sibling directly rather than working around it here.

- **`dreambo-torso-kinematics`** — `/home/ubuntu/Documents/GitHub/dreambo_torso_kinematics`
  Rust + PyO3. Analytical IK/FK for the Stewart parallel mechanism (legacy head).
- **`dreambo_motor_controller`** — `/home/ubuntu/Documents/GitHub/dreambo_motor_controller`
  Rust + PyO3. High-level controller for arms, nose, and the 3-DM neck (serial + CAN).
- **`motorcom`** — `/home/ubuntu/Documents/GitHub/rust_motorcom`
  Rust + PyO3. SocketCAN driver for Damiao DM-series CAN servos (MIT impedance mode).
- **`servocom`** — `/home/ubuntu/Documents/GitHub/rust_servocom`
  Rust + PyO3. Serial driver for Feetech SCS/STS bus servos.

Quick conventions for working across these repos:
- Each sibling has its own `CLAUDE.md` / `AGENTS.md` / `RELEASE.md`. Read those before editing.
- After making a change in a sibling, bump that sibling's version and republish (see its `RELEASE.md`) before bumping the corresponding pin in this SDK's `pyproject.toml`.
- The installed copy of each sibling lives under `.venv/lib/python*/site-packages/` in this repo. Reading the installed `.pyi` stubs is the fastest way to see the current public API surface from inside this project.

## Debug / development environment

This repo uses [`uv`](https://github.com/astral-sh/uv) to manage its virtual environment. Always run Python tooling, scripts, tests, and linters through the `uv`-managed `.venv` — do not invoke the system Python or create a separate `venv`/`virtualenv`.

- Sync dependencies with `uv sync` (the source of truth is `pyproject.toml` + `uv.lock`).
- Run commands inside the env with `uv run <cmd>` (e.g. `uv run python -m dreambo_torso ...`, `uv run pytest`, `uv run ruff check .`).
- If you need an interactive shell, activate `.venv/bin/activate`; otherwise prefer `uv run` so the lockfile is respected.
- Never add or upgrade a dependency by editing `pyproject.toml` alone — use `uv add` / `uv lock` so `uv.lock` stays in sync.

## Pre-commit / pre-push checks

Before creating any commit or pushing to a remote, run `ruff` locally and fix anything it reports. CI runs the same checks, so catching them locally avoids round-trips through failed pipelines.

Required sequence whenever you are about to `git commit` or `git push`:

1. `ruff check .` — lint the whole repo. Resolve every reported issue (or explicitly justify a `# noqa` if truly unavoidable) before continuing.
2. `ruff format --check .` — verify formatting. If it reports changes, run `ruff format .` and re-stage the affected files.
3. Only after both commands exit cleanly should you proceed with `git commit` and `git push`.

Do not skip these checks with `--no-verify` or by bypassing the pre-commit hook. If a check fails, fix the underlying issue rather than working around it.
