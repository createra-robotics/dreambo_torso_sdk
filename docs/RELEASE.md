# Releasing Dreambo Torso as an Installable Product

This document explains how to publish the `dreambo-torso` package so end users can install it on a Raspberry Pi (or any Linux host) and run the daemon as a service.

> **Note on naming:** throughout this doc, `dreambo-torso` (hyphen) refers to the **PyPI distribution name** — what users type into `uv add` / `pip install`. `dreambo_torso` (underscore) refers to the **Python import package** — what shows up in `from dreambo_torso import …` and as the directory `src/dreambo_torso/`. Hyphens are invalid in Python identifiers, so the two forms are intentional and not a typo.

The target user experience is:

```bash
curl -fsSL https://dreambo-torso.example.com/install.sh | bash
# ...daemon is now running and will auto-start on boot.
```

Under the hood, the install script runs `uv tool install dreambo-torso`, drops a `systemd` unit, and starts `dreambo-torso-daemon`.

---

## 1. What is already in place

- **Package metadata** — `pyproject.toml` declares `name = "dreambo-torso"` (PyPI distribution name, hyphenated) and the console script `dreambo-torso-daemon = "dreambo_torso.daemon.app.main:main"` (the import package uses underscores). After install, the binary is on `PATH`.
- **Publish workflow** — `.github/workflows/wheels.yml` fires on GitHub Release creation, builds an sdist + wheel, and publishes to PyPI via **trusted publishing** (OIDC, no API token).

What is missing is: PyPI project setup, a stable version-bump policy, public availability of in-house dependencies, and a Pi bootstrap script.

---

## 2. PyPI publish workflow

### 2.1 One-time PyPI setup

1. Create the `dreambo-torso` project on PyPI to claim the name.
2. On PyPI: **Project → Publishing → Add a new pending publisher** with:

   | Field    | Value                                 |
   | -------- |---------------------------------------|
   | Owner    | `createra-robotics` (or the org used) |
   | Repo     | `dreambo_torso_sdk`                   |
   | Workflow | `wheels.yml`                          |
   | Env      | leave blank (or pin to `release`)     |

   No API token is required — `id-token: write` in the workflow handles auth.

### 2.2 Make every dependency installable from PyPI

Several deps in `pyproject.toml` look in-house. Confirm each is on PyPI, or publish it before tagging a release; otherwise `uv add dreambo-torso` will fail to resolve on a user's Pi.

- `dreambo_motor_controller`
- `motorcom`
- `dreambo-torso-kinematics`
- `servocom`

### 2.3 Version policy

`pyproject.toml` currently has `version = "1.0.0"` (static). PyPI rejects re-uploads of the same version, so:

- **Manual:** bump the `version` field for every release, OR
- **Automatic:** switch to `dynamic = ["version"]` and use `setuptools-scm` so the version is derived from the git tag.

### 2.4 Cut a release

```bash
git tag v1.0.1
git push --tags
gh release create v1.0.1 --generate-notes
```

`wheels.yml` builds and uploads within ~2 minutes. Verify with:

```bash
uv tool install dreambo-torso==1.0.1
dreambo-torso-daemon --help
```

---

## 3. End-user install on Raspberry Pi

### 3.1 Why `uv tool install`, not `uv add`

`uv add` only works inside a uv project. For a daemon that should be globally available and auto-start on boot, **`uv tool install dreambo-torso`** is the right primitive — it gives `dreambo-torso-daemon` on `PATH` in an isolated venv with no surrounding project required.

### 3.2 Bootstrap script — `scripts/install.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. System packages (cannot be installed via pip/uv)
sudo apt update
sudo apt install -y \
  libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev gcc \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
  gstreamer1.0-alsa gstreamer1.0-nice gstreamer1.0-tools \
  gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
  python3-gi python3-gi-cairo \
  libpulse0 libportaudio2 libnice10 \
  pipewire pipewire-pulse wireplumber pulseaudio-utils

# 2. udev rule so non-root users can talk to the motor USB bridge
sudo tee /etc/udev/rules.d/99-dreambo-torso.rules >/dev/null <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="2886", ATTRS{idProduct}=="YYYY", MODE="0666"
EOF
sudo udevadm control --reload && sudo udevadm trigger

# 3. uv (skip if present)
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 4. Install the daemon
uv tool install --python 3.12 dreambo-torso

# 5. User-level systemd unit (no sudo needed for service file)
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/dreambo-torso-daemon.service <<EOF
[Unit]
Description=Dreambo robot daemon
After=network-online.target sound.target

[Service]
ExecStart=%h/.local/bin/dreambo-torso-daemon
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF

# 6. Enable + start; enable-linger keeps the service alive after logout
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now dreambo-torso-daemon.service

echo "Daemon running. Check: systemctl --user status dreambo-torso-daemon"
```

Replace `XXXX` / `YYYY` with the actual USB vendor / product IDs of the motor bridge (`lsusb` with the bridge plugged in, or check `dreambo_motor_controller`).

### 3.3 Hosting the script

GitHub raw works for a quick start:

```
https://raw.githubusercontent.com/createra-robotics/dreambo_torso_sdk/main/scripts/install.sh
```

For production, host tagged copies and point a stable `latest` URL at the most recent tag, so users don't pick up a half-merged `main`.

---

## 4. Design decisions to lock in before first release

### 4.1 System service vs user service

The script above installs a **user** service (`systemctl --user`, no root for unit edits, runs as the logged-in user, requires `enable-linger` to survive logout).

Switch to a **system** service (`/etc/systemd/system/dreambo-torso-daemon.service`) if the daemon must run before any user logs in — for example, a headless Pi where a JS app connects immediately on boot. In that case, create a dedicated `dreambo-torso` user and add it to `dialout`, `audio`, and `video` groups.

### 4.2 Update path

Decide how users get new versions:

- **Manual:** users re-run `uv tool upgrade dreambo-torso`.
- **Automatic:** add a small `dreambo-torso-update.timer` systemd unit that calls `uv tool upgrade` on a schedule.

### 4.3 Version pinning at install time

For reproducible installs, bootstrap should pin a version (`uv tool install dreambo-torso==1.0.1`) rather than always pulling latest. The script above pulls latest; change once a stable release line exists.

---

## 5. Release checklist

- [ ] All in-house dependencies are published to PyPI.
- [ ] `pyproject.toml` version is bumped (or `setuptools-scm` is configured).
- [ ] `CHANGELOG` (if any) updated.
- [ ] PyPI trusted publisher is configured for the repo + workflow.
- [ ] `git tag vX.Y.Z && git push --tags`
- [ ] `gh release create vX.Y.Z --generate-notes`
- [ ] Wheel appears on PyPI (`pip index versions dreambo-torso` or check the project page).
- [ ] Smoke test: on a clean Pi, run `install.sh`, verify `systemctl --user status dreambo-torso-daemon` is `active (running)`.