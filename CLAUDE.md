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
